"""도구 레지스트리·도구 6종 단위 테스트 — 역할 가시성·인자 검증·소유권 분기.

SQL 도구는 가짜 세션(conftest.FakeSession)으로 포매팅·분기 로직을 커버한다. 실 PG·RLS·
규칙8(무변경)은 apps/api 통합 테스트가 담당한다.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from conftest import FakeSession, row
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.graph import GraphClient, IncidentContext, IncidentHit
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool
from ai_core.tools.library import GetFeesArgs

TENANT = uuid.uuid4()
USER = uuid.uuid4()
HOUSEHOLD = uuid.uuid4()

CTX_RESIDENT = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))
CTX_MANAGER = ToolContext(TENANT, USER, roles=("MANAGER",), visibilities=("ALL", "ADMIN"))


# ── fakes ──────────────────────────────────────────────────────────────


class FakeRetriever:
    def __init__(self, chunks: Sequence[RetrievedChunk]) -> None:
        self._chunks = list(chunks)
        self.calls: list[dict[str, Any]] = []  # 격리 값(tenant·동)이 실제로 넘어갔는지 검증용

    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        tenant_id: uuid.UUID,
        visibilities: Sequence[str],
        top_k: int = 8,
        building_id: uuid.UUID | None = None,
    ) -> list[RetrievedChunk]:
        self.calls.append({"tenant_id": tenant_id, "building_id": building_id})
        return list(self._chunks)


class FakeGraph:
    def __init__(self, hits: list[IncidentHit], contexts: list[IncidentContext]) -> None:
        self._hits = hits
        self._contexts = contexts

    async def search_incidents(
        self, *, tenant_id: str, query_vector: Sequence[float], k: int
    ) -> list[IncidentHit]:
        return self._hits

    async def expand_incidents(
        self, *, tenant_id: str, pg_ids: Sequence[str]
    ) -> list[IncidentContext]:
        return self._contexts


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="관리규약",
        content="지하주차장은 24시간 개방한다.",
        heading=None,
        page=1,
        clause="제3조",
        score=0.9,
    )


def _embed_llm(settings: AiCoreSettings, *, ok: bool = True) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            if not ok:
                return httpx.Response(400)  # 4xx → LlmError(재시도 없음)
            n = len(json.loads(request.content)["input"])
            data = [
                {"index": i, "embedding": [0.05] * settings.embedding_dimensions} for i in range(n)
            ]
            return httpx.Response(200, json={"data": data})
        return httpx.Response(500)

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


def _deps(
    settings: AiCoreSettings,
    *,
    handler: Any = None,
    chunks: Sequence[RetrievedChunk] = (),
    graph: Any = None,
    embed_ok: bool = True,
) -> ToolDeps:
    session = FakeSession(handler or (lambda sql, params: []))
    return ToolDeps(
        session=cast(AsyncSession, session),
        llm=_embed_llm(settings, ok=embed_ok),
        retriever=cast(Retriever, FakeRetriever(chunks)),
        graph=cast(GraphClient, graph) if graph is not None else None,
    )


def _call(name: str, args: object = None) -> ToolCallRequest:
    arguments = "" if args is None else (args if isinstance(args, str) else json.dumps(args))
    return ToolCallRequest(id=f"c-{name}", name=name, arguments=arguments)


# ── 레지스트리·역할 가시성 ─────────────────────────────────────────────


def test_resident_specs_exclude_facility_tools() -> None:
    registry = default_registry()
    names = {s["function"]["name"] for s in registry.specs_for(("RESIDENT",), graph_available=True)}
    assert "search_documents" in names
    assert "get_fees" in names
    assert "search_facility_graph" not in names
    assert "get_facilities" not in names
    assert "get_overdue_checks" not in names


def test_manager_specs_include_facility_tools() -> None:
    registry = default_registry()
    names = {s["function"]["name"] for s in registry.specs_for(("MANAGER",), graph_available=True)}
    assert {"get_facilities", "get_overdue_checks", "search_facility_graph"} <= names


def test_graph_tool_excluded_when_graph_unavailable() -> None:
    registry = default_registry()
    names = {s["function"]["name"] for s in registry.specs_for(("MANAGER",), graph_available=False)}
    assert "search_facility_graph" not in names
    assert "get_facilities" in names  # 그래프 불필요 시설 도구는 유지


async def test_direct_call_to_hidden_tool_is_denied(settings: AiCoreSettings) -> None:
    registry = default_registry()
    execution = await execute_tool(
        _call("get_facilities", {}),
        ctx=CTX_RESIDENT,
        deps=_deps(settings),
        registry=registry,
    )
    assert execution.ok is False
    assert "사용할 수 없습니다" in execution.result.note


# ── 인자 검증 ──────────────────────────────────────────────────────────


async def test_invalid_period_arg_returns_error_result(settings: AiCoreSettings) -> None:
    execution = await execute_tool(
        _call("get_fees", {"period": "2026/06"}),  # 잘못된 형식
        ctx=CTX_RESIDENT,
        deps=_deps(settings),
        registry=default_registry(),
    )
    assert execution.ok is False
    assert "인자 검증 실패" in execution.result.note


async def test_malformed_json_args_return_error_result(settings: AiCoreSettings) -> None:
    execution = await execute_tool(
        _call("get_fees", "{not-json"),
        ctx=CTX_RESIDENT,
        deps=_deps(settings),
        registry=default_registry(),
    )
    assert execution.ok is False


# ── search_documents ───────────────────────────────────────────────────


async def test_search_documents_returns_chunks(settings: AiCoreSettings) -> None:
    execution = await execute_tool(
        _call("search_documents", {"query": "주차장"}),
        ctx=CTX_RESIDENT,
        deps=_deps(settings, chunks=[_chunk()]),
        registry=default_registry(),
    )
    assert execution.ok is True
    assert len(execution.result.doc_chunks) == 1


async def test_search_documents_passes_context_building_id(settings: AiCoreSettings) -> None:
    """동은 ToolContext에서만 온다(H19-1) — LLM 인자가 아니라 코드가 넘긴다."""
    building = uuid.uuid4()
    deps = _deps(settings, chunks=[_chunk()])
    retriever = cast(FakeRetriever, deps.retriever)
    await execute_tool(
        _call("search_documents", {"query": "8월 공지"}),
        ctx=ToolContext(
            TENANT, USER, roles=("RESIDENT",), visibilities=("ALL",), building_id=building
        ),
        deps=deps,
        registry=default_registry(),
    )
    assert retriever.calls == [{"tenant_id": TENANT, "building_id": building}]


async def test_search_documents_without_building_passes_none(settings: AiCoreSettings) -> None:
    """세대 미배정·관리자는 동이 없다 — None이 그대로 내려가 필터가 꺼진다."""
    deps = _deps(settings, chunks=[_chunk()])
    retriever = cast(FakeRetriever, deps.retriever)
    await execute_tool(
        _call("search_documents", {"query": "8월 공지"}),
        ctx=CTX_MANAGER,
        deps=deps,
        registry=default_registry(),
    )
    assert retriever.calls == [{"tenant_id": TENANT, "building_id": None}]


async def test_search_documents_empty_returns_note(settings: AiCoreSettings) -> None:
    execution = await execute_tool(
        _call("search_documents", {"query": "없는내용"}),
        ctx=CTX_RESIDENT,
        deps=_deps(settings, chunks=[]),
        registry=default_registry(),
    )
    assert execution.result.doc_chunks == ()
    assert "찾지 못했" in execution.result.note


async def test_search_documents_embed_failure_returns_note(settings: AiCoreSettings) -> None:
    execution = await execute_tool(
        _call("search_documents", {"query": "주차"}),
        ctx=CTX_RESIDENT,
        deps=_deps(settings, chunks=[_chunk()], embed_ok=False),
        registry=default_registry(),
    )
    assert "일시적으로" in execution.result.note


# ── get_fees (본인 세대·승인 후 월) ─────────────────────────────────────


def _fee_handler(sql: str, params: dict[str, Any]) -> list[Any]:
    s = sql.lower()
    if "from users" in s:
        return [row(household_id=HOUSEHOLD, approved_at=datetime(2020, 1, 1, tzinfo=UTC))]
    if "order by period desc" in s:
        return [row(period="2026-06")]
    if "from fees" in s:
        if params.get("period") == "2026-06":
            return [
                row(
                    breakdown=[
                        {"name": "일반관리비", "level": 0, "amount": 50000},
                        {"name": "청소비", "level": 1, "amount": 20000},
                        {"name": "합계", "level": 0, "amount": 100000},
                    ],
                    total_amount=100000,
                )
            ]
        if params.get("period") == "2026-05":
            return [
                row(
                    breakdown=[{"name": "일반관리비", "level": 0, "amount": 48000}],
                    total_amount=90000,
                )
            ]
    return []


async def test_get_fees_returns_card_with_prev_diff(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _call("get_fees", {"period": "2026-06"}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=_fee_handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert result.card.source_kind == "tool:get_fees"
    assert "100,000원" in result.card.quote
    assert "90,000원 대비" in result.card.quote  # 전월 대비


async def test_get_fees_defaults_to_latest_period(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _call("get_fees", {}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=_fee_handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None and "2026-06" in result.card.title


async def test_get_fees_no_household_returns_note(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _call("get_fees", {}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=lambda sql, params: []),
            registry=default_registry(),
        )
    ).result
    assert result.card is None
    assert "세대가 배정" in result.note


async def test_get_fees_before_approval_is_blocked(settings: AiCoreSettings) -> None:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        if "from users" in sql.lower():
            return [row(household_id=HOUSEHOLD, approved_at=datetime(2026, 6, 1, tzinfo=UTC))]
        return []

    result = (
        await execute_tool(
            _call("get_fees", {"period": "2026-01"}),  # 승인(2026-06) 이전
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is None
    assert "조회할 수 없습니다" in result.note


# ── get_my_inquiries ───────────────────────────────────────────────────


async def test_get_my_inquiries_lists_own(settings: AiCoreSettings) -> None:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        assert params["uid"] == USER  # 본인 소유권 강제
        return [row(title="누수", status="in_progress"), row(title="소음", status="done")]

    result = (
        await execute_tool(
            _call("get_my_inquiries", {}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert "누수" in result.card.quote and "in_progress" in result.card.quote


async def test_get_my_inquiries_empty_returns_card(settings: AiCoreSettings) -> None:
    # DB가 확인한 "없음"은 확정 근거다 — note가 아니라 인용 가능한 카드(케이스셋 v2 §6-⓪).
    result = (
        await execute_tool(
            _call("get_my_inquiries", {}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=lambda sql, params: []),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert result.card.source_kind == "tool:get_my_inquiries"
    assert "민원이 없습니다" in result.card.quote


# ── get_facilities / get_overdue_checks (시설 역할) ─────────────────────


async def test_get_facilities_with_status_filter(settings: AiCoreSettings) -> None:
    captured: dict[str, Any] = {}

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        captured.update({"sql": sql, "params": params})
        return [row(name="엘리베이터1", status="fault", code="EL-101-01")]

    result = (
        await execute_tool(
            _call("get_facilities", {"status": "fault"}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None and "엘리베이터1(fault)" in result.card.quote
    assert captured["params"]["status"] == "fault"
    assert "status = :status" in captured["sql"]


async def test_get_facilities_quote_includes_counts(settings: AiCoreSettings) -> None:
    # "승강기 몇 대" 류 대수 질문의 정답 근거 — 총수·코드 종류별 수를 집계해 인용한다.
    # LIMIT 잘림(구현 전 MAX_TOOL_ROWS=20 < 설비 37건)이면 대수가 틀린다(케이스셋 v2 §6-⓪).
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        return [
            row(name="승강기1", status="normal", code="EL-101-01"),
            row(name="승강기2", status="normal", code="EL-102-01"),
            row(name="CCTV1", status="normal", code="CM-401-01"),
            row(name="무코드설비", status="normal", code=None),
        ]

    result = (
        await execute_tool(
            _call("get_facilities", {}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert "총 4개" in result.card.quote
    assert "EL 2" in result.card.quote
    assert "CM 1" in result.card.quote


async def test_get_facilities_caps_list_but_counts_all(settings: AiCoreSettings) -> None:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        return [row(name=f"설비{i}", status="normal", code=f"EL-{i:03d}-01") for i in range(25)]

    result = (
        await execute_tool(
            _call("get_facilities", {}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert "총 25개" in result.card.quote  # 집계는 전수
    assert "외 5개" in result.card.quote  # 나열은 20개 상한


async def test_get_facilities_empty_returns_card(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _call("get_facilities", {"status": "fault"}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=lambda sql, params: []),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert result.card.source_kind == "tool:get_facilities"
    assert "fault" in result.card.quote  # 조회 조건 명시
    assert "없습니다" in result.card.quote


async def test_get_overdue_checks_lists_due(settings: AiCoreSettings) -> None:
    due = datetime.now(UTC) + timedelta(days=2)

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        return [row(name="소방펌프", next_check_at=due)]

    result = (
        await execute_tool(
            _call("get_overdue_checks", {}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None and "소방펌프" in result.card.quote


async def test_get_overdue_checks_empty_returns_card(settings: AiCoreSettings) -> None:
    # R22 실측: 빈 결과가 note만 반환 → 인용 근거 없음 → 폴백. "DB가 확인한 없음"은
    # 절대 규칙 1의 확정 도구 결과이므로 카드로 승격한다(케이스셋 v2 §6-⓪, codex HIGH).
    result = (
        await execute_tool(
            _call("get_overdue_checks", {}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=lambda sql, params: []),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert result.card.source_kind == "tool:get_overdue_checks"
    assert "7일" in result.card.quote  # 조회 조건(윈도우) 명시
    assert "없습니다" in result.card.quote


def test_tool_descriptions_match_io_contract() -> None:
    """설명문이 실제 I/O를 넘어서 약속하지 않는다(케이스셋 v2 §6-⓪).

    - get_facilities: SELECT에 위치가 없다 — "위치" 약속 금지. 대수는 집계로 제공.
    - get_overdue_checks: 윈도우는 7일 — "이번 달" 약속 금지.
    - search_facility_graph: 타 도구명 직접 지시 금지(개명·가시성 변경에 취약).
    """
    registry = default_registry()
    specs = {
        s["function"]["name"]: s["function"]["description"]
        for s in registry.specs_for(("MANAGER",), graph_available=True)
    }
    assert "위치" not in specs["get_facilities"]
    assert "이번 달" not in specs["get_overdue_checks"]
    assert "7일" in specs["get_overdue_checks"]
    assert "get_overdue_checks" not in specs["search_facility_graph"]


# ── search_facility_graph ──────────────────────────────────────────────


async def test_search_facility_graph_builds_card(settings: AiCoreSettings) -> None:
    hits = [IncidentHit(pg_id="i1", symptom="누수", score=0.9)]
    contexts = [
        IncidentContext(
            incident_id="i1",
            symptom="누수",
            facility_name="지하펌프",
            facility_status="fault",
            recent_work=("패킹 교체",),
        )
    ]
    result = (
        await execute_tool(
            _call("search_facility_graph", {"query": "누수"}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, graph=FakeGraph(hits, contexts)),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert result.card.source_kind == "tool:search_facility_graph"
    assert "지하펌프(fault)" in result.card.quote
    assert "패킹 교체" in result.card.quote


async def test_search_facility_graph_card_shows_causal_chain(settings: AiCoreSettings) -> None:
    # G1a 다단계 인과 — causal_chain이 채워지면 카드 quote에 선행원인 연쇄가 노출돼야 한다.
    hits = [IncidentHit(pg_id="i1", symptom="진동 재발", score=0.9)]
    contexts = [
        IncidentContext(
            incident_id="i1",
            symptom="진동 재발",
            facility_name="지하펌프",
            facility_status="fault",
            recent_work=(),
            causal_chain=("베어링 마모", "윤활유 부족"),
        )
    ]
    result = (
        await execute_tool(
            _call("search_facility_graph", {"query": "진동"}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, graph=FakeGraph(hits, contexts)),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert "선행원인: 베어링 마모 ← 윤활유 부족" in result.card.quote


async def test_search_facility_graph_without_graph_returns_note(settings: AiCoreSettings) -> None:
    # 그래프 미가용이면 스펙에서 빠지지만, 직접 호출 방어도 확인(graph_available=False).
    registry = default_registry()
    execution = await execute_tool(
        _call("search_facility_graph", {"query": "누수"}),
        ctx=CTX_MANAGER,
        deps=_deps(settings, graph=None),
        registry=registry,
    )
    assert execution.ok is False  # 그래프 불가 → 스펙 제외 = not_visible


async def test_search_facility_graph_no_hits_returns_note(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _call("search_facility_graph", {"query": "없음"}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, graph=FakeGraph([], [])),
            registry=default_registry(),
        )
    ).result
    assert "찾지 못했" in result.note


def test_get_fees_args_optional_period() -> None:
    assert GetFeesArgs.model_validate({}).period is None
    assert GetFeesArgs(period="2026-06").period == "2026-06"
