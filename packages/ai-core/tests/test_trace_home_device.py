"""trace_home_device_issue 도구 — 세대 스코프·미모델링/이력없음/이력있음 분기·읽기 전용.

SQL은 conftest.FakeSession(가짜 세션, 쿼리 텍스트 분기)으로, 그래프는 FakeGraph 스텁으로
주입해 도구 로직만 검증한다(test_tools.py·test_floor_plan_tool.py 관례와 동일). 실 PG·RLS·
실 Neo4j 격리는 각각 apps/api 통합 테스트·test_graph.py가 담당한다.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, cast

import httpx
from conftest import FakeSession, row
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.graph import GraphClient, IncidentContext
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool

TENANT = uuid.uuid4()
USER = uuid.uuid4()
HOUSEHOLD = uuid.uuid4()
UNIT_TYPE_ID = uuid.uuid4()
PLAN_ID = uuid.uuid4()
FACILITY_WT = uuid.uuid4()  # 수도 차단밸브 → 급수 계통

CTX = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

# 수도밸브는 급수 설비에 연결, 가스밸브는 미모델링(facility_id NULL).
_DEVICES = [
    row(device_type="수도 차단밸브", facility_id=FACILITY_WT),
    row(device_type="가스밸브", facility_id=None),
    row(device_type="화재감지기", facility_id=None),
]


# ── fakes ──────────────────────────────────────────────────────────────


class FakeGraph:
    def __init__(self, contexts: list[IncidentContext]) -> None:
        self._contexts = contexts
        self.calls: list[list[str]] = []

    async def incidents_for_facilities(
        self, *, tenant_id: str, facility_ids: Sequence[str]
    ) -> list[IncidentContext]:
        self.calls.append(list(facility_ids))
        return self._contexts


def _plan_handler(
    devices: Sequence[Any],
    *,
    household_id: uuid.UUID | None = HOUSEHOLD,
    plan_id: uuid.UUID | None = PLAN_ID,
) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        if "from users" in s:
            assert params["uid"] == USER  # 본인 세대 스코프(CRITICAL) — 항상 ctx.user_id로만 해석
            assert params["tid"] == TENANT
            return [row(household_id=household_id)] if household_id else [row(household_id=None)]
        if "from household_geometries" in s:
            return [row(unit_type_label="84M(공공임대)")]
        if "from unit_types" in s:
            return [row(id=UNIT_TYPE_ID)]
        if "from floor_plans" in s:
            return [row(id=plan_id)] if plan_id else []
        if "from plan_devices" in s:
            assert params["pid"] == plan_id
            return list(devices)
        return []

    return handler


def _noop_llm(settings: AiCoreSettings) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"이 도구는 LLM을 호출하지 않는다: {request.url.path}")

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


class _NoopRetriever:
    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        tenant_id: uuid.UUID,
        visibilities: Sequence[str],
        top_k: int = 8,
    ) -> list[RetrievedChunk]:
        return []


def _deps(settings: AiCoreSettings, handler: Any, graph: Any) -> ToolDeps:
    return ToolDeps(
        session=cast(AsyncSession, FakeSession(handler)),
        llm=_noop_llm(settings),
        retriever=cast(Retriever, _NoopRetriever()),
        graph=cast(GraphClient, graph) if graph is not None else None,
    )


def _call(query: str) -> ToolCallRequest:
    return ToolCallRequest(
        id="c-trace", name="trace_home_device_issue", arguments=json.dumps({"query": query})
    )


def _ctx(**over: Any) -> IncidentContext:
    base: dict[str, Any] = {
        "incident_id": "i1",
        "symptom": "단수",
        "facility_name": "급수펌프",
        "facility_status": "normal",
        "recent_work": ("펌프 점검",),
    }
    base.update(over)
    return IncidentContext(**base)


# ── (1) 평면도 없음 → note ────────────────────────────────────────────


async def test_no_household_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(settings, _plan_handler(_DEVICES, household_id=None), FakeGraph([]))
    result = (
        await execute_tool(
            _call("우리 집 수도 안 나와요"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is None
    assert "평면도가 준비되지" in result.note


# ── (2) 미모델링 기기(facility_id NULL) → 미모델링 note ─────────────────


async def test_unmodeled_device_returns_no_facility_note(settings: AiCoreSettings) -> None:
    graph = FakeGraph([])
    deps = _deps(settings, _plan_handler(_DEVICES), graph)
    # "가스밸브"는 facility_id NULL — 연결 계통 없음(미모델링)
    result = (
        await execute_tool(
            _call("가스밸브가 이상해요"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is None
    assert "연결된 공용 설비 계통 정보가 없습니다" in result.note
    assert graph.calls == []  # 미모델링이면 그래프 조회를 하지 않는다


# ── (3) facility 있고 이력 없음 → 카드 승격(note 아님) ───────────────────


async def test_no_history_promotes_to_card(settings: AiCoreSettings) -> None:
    graph = FakeGraph([])  # 연결 계통은 있으나 장애 이력 없음
    deps = _deps(settings, _plan_handler(_DEVICES), graph)
    result = (
        await execute_tool(
            _call("수도밸브 쪽에 문제가 있어요"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is not None  # 확정 근거 → 카드 승격(⓪ 계약)
    assert result.card.source_kind == "tool:trace_home_device_issue"
    assert "과거 장애 이력이 없습니다" in result.card.quote
    assert graph.calls == [[str(FACILITY_WT)]]  # 급수 계통만 조회


# ── (4) 이력 있음 → 카드에 증상·원인·조치·인과 연쇄 ─────────────────────


async def test_history_returns_card_with_cause_resolution_chain(settings: AiCoreSettings) -> None:
    contexts = [
        _ctx(
            symptom="단수",
            root_cause="부스터펌프 정지",
            resolution="펌프 재기동 및 임펠러 교체",
            causal_chain=("수위센서 오작동",),
            recent_work=("펌프 점검", "센서 교체"),
        )
    ]
    deps = _deps(settings, _plan_handler(_DEVICES), FakeGraph(contexts))
    result = (
        await execute_tool(
            _call("수도가 안 나와요"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is not None
    quote = result.card.quote
    assert "급수펌프(normal) 증상: 단수" in quote
    assert "원인: 부스터펌프 정지" in quote
    assert "조치: 펌프 재기동 및 임펠러 교체" in quote
    assert "선행원인: 수위센서 오작동" in quote
    assert "최근정비: 펌프 점검, 센서 교체" in quote


# ── (5) 세대 스코프 — user_id로만 해석(다른 세대 지정 불가) ──────────────


async def test_scope_resolved_only_by_user_id(settings: AiCoreSettings) -> None:
    # _plan_handler가 users 조회 시 uid==USER·tid==TENANT를 강제 assert한다. LLM 인자에
    # 세대·설비가 없으므로(TraceHomeDeviceArgs는 query 1개) 서버가 user_id로만 스코프를 정한다.
    graph = FakeGraph([_ctx()])
    deps = _deps(settings, _plan_handler(_DEVICES), graph)
    result = (
        await execute_tool(_call("수도 문제"), ctx=CTX, deps=deps, registry=default_registry())
    ).result
    assert result.card is not None  # user_id로 해석된 세대의 급수 계통 조회 성공
    assert graph.calls == [[str(FACILITY_WT)]]


# ── 그래프 미가용 방어 ──────────────────────────────────────────────────


async def test_graph_unavailable_direct_call_denied(settings: AiCoreSettings) -> None:
    # requires_graph=True → graph_available=False면 스펙 제외 + 직접 호출도 거부(not_visible).
    execution = await execute_tool(
        _call("수도 문제"),
        ctx=CTX,
        deps=_deps(settings, _plan_handler(_DEVICES), None),
        registry=default_registry(),
    )
    assert execution.ok is False


# ── 역할 가시성(RESIDENT 전용 + 그래프 필요) ────────────────────────────


def test_resident_specs_include_trace_tool() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("RESIDENT",), graph_available=True)
    }
    assert "trace_home_device_issue" in names


def test_manager_specs_exclude_trace_tool() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("MANAGER",), graph_available=True)
    }
    assert "trace_home_device_issue" not in names


def test_trace_tool_excluded_when_graph_unavailable() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("RESIDENT",), graph_available=False)
    }
    assert "trace_home_device_issue" not in names
