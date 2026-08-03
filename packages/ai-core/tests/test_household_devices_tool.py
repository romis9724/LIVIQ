"""find_household_devices(관리자 세대 평면도 도구, H20-17) — 대상 세대 결정·격리·역할.

CRITICAL 축은 셋이다:
- 대상 세대는 `ctx.target_unit`(코드가 정한 값)만 — LLM 인자로는 세대를 못 고른다(규칙 4).
- 입주민에게는 노출도 실행도 되지 않는다(입주민 도구는 본인 세대 전용 그대로).
- 모든 조회에 tenant_id가 실린다(규칙 3 — RLS와 이중 방어).

SQL은 conftest.FakeSession(쿼리 텍스트 분기)으로 검증한다(실 PG는 apps/api 담당).
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
from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool
from ai_core.tools.floor_plan import HOUSEHOLD_DEVICES_TOOL, find_household_devices_tool

TENANT = uuid.uuid4()
USER = uuid.uuid4()
UNIT_TYPE_ID = uuid.uuid4()
PLAN_ID = uuid.uuid4()
TARGET = ("402", 201)

MANAGER_CTX = ToolContext(
    TENANT, USER, roles=("MANAGER",), visibilities=("ALL",), target_unit=TARGET
)

_DEVICES = [
    row(device_type="room", room="현관", dir=None),
    row(device_type="분전함", room="현관", dir="left"),
    row(device_type="콘센트", room="거실", dir="left"),
    row(device_type="콘센트", room="거실", dir="right"),
]


# ── fakes ──────────────────────────────────────────────────────────────


def _handler(
    devices: Sequence[Any],
    *,
    household_found: bool = True,
    unit_type_id: uuid.UUID | None = None,
    label: str | None = "84M(공공임대)",
    plan_id: uuid.UUID | None = PLAN_ID,
) -> Any:
    """동·호수 → 세대 → (타입) → 도면 → 장치. tenant_id는 모든 단계에서 확인한다."""

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        assert params["tid"] == TENANT, f"tenant_id 누락(규칙 3): {sql}"
        if "from households h" in s:
            assert params["dong"] == TARGET[0]
            assert params["ho"] == TARGET[1]
            if not household_found:
                return []
            return [row(unit_type_id=unit_type_id, unit_type_label=label)]
        if "from unit_types" in s:
            assert params["name"] == "84M"  # 괄호 이하 정규화
            return [row(id=UNIT_TYPE_ID)]
        if "from floor_plans" in s:
            assert params["utid"] == UNIT_TYPE_ID
            return [row(id=plan_id)] if plan_id else []
        if "from plan_devices" in s:
            assert params["pid"] == plan_id
            return list(devices)
        return []

    return handler


def _forbidden_llm(settings: AiCoreSettings) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"파서 성공 경로인데 LLM이 호출됨: {request.url.path}")

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


class _NoopRetriever:
    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        tenant_id: uuid.UUID,
        visibilities: Sequence[str],
        top_k: int = 8,
        building_id: uuid.UUID | None = None,
    ) -> list[RetrievedChunk]:
        return []


def _deps(llm: LlmClient, handler: Any) -> ToolDeps:
    return ToolDeps(
        session=cast(AsyncSession, FakeSession(handler)),
        llm=llm,
        retriever=cast(Retriever, _NoopRetriever()),
        graph=cast(GraphClient, None),
    )


def _call(query: str) -> ToolCallRequest:
    return ToolCallRequest(
        id="c-hh", name=HOUSEHOLD_DEVICES_TOOL, arguments=json.dumps({"query": query})
    )


async def _run(ctx: ToolContext, deps: ToolDeps, query: str) -> Any:
    return (
        await execute_tool(_call(query), ctx=ctx, deps=deps, registry=default_registry())
    ).result


# ── 정상 경로 ──────────────────────────────────────────────────────────


async def test_returns_card_for_target_unit(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES))

    result = await _run(MANAGER_CTX, deps, "두꺼비집 어디?")

    assert result.card is not None
    assert result.card.source_kind == f"tool:{HOUSEHOLD_DEVICES_TOOL}"
    assert result.card.quote.startswith("402동 201호 · ")
    assert "현관 분전함 1곳: 왼쪽" in result.card.quote


async def test_card_data_carries_unit_and_highlight_labels(settings: AiCoreSettings) -> None:
    """화면 딥링크가 쓰는 확정값(ADR-0025 §6) — 동·호수와 강조 라벨을 서버가 확정한다."""
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES))

    result = await _run(MANAGER_CTX, deps, "거실 콘센트 어디 있어?")

    assert result.card.data == {
        "kind": "home_devices",
        "dong": "402",
        "ho": 201,
        "labels": ["거실 콘센트"],
    }


async def test_household_without_unit_type_falls_back_to_geometry_label(
    settings: AiCoreSettings,
) -> None:
    """세대에 타입이 안 붙어 있으면 트윈 업로드 라벨로 되짚는다(입주민 경로와 동일)."""
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES, unit_type_id=None))

    result = await _run(MANAGER_CTX, deps, "두꺼비집 어디?")

    assert result.card is not None


async def test_household_with_unit_type_skips_label_lookup(settings: AiCoreSettings) -> None:
    deps = _deps(
        _forbidden_llm(settings), _handler(_DEVICES, unit_type_id=UNIT_TYPE_ID, label=None)
    )

    result = await _run(MANAGER_CTX, deps, "두꺼비집 어디?")

    assert result.card is not None


# ── 대상 세대가 없거나 도면이 없을 때(오류 아님 — 지어내지 않는다) ────────


async def test_missing_target_unit_returns_note(settings: AiCoreSettings) -> None:
    """CRITICAL — 동·호수를 코드가 확정하지 못했으면 조회하지 않는다(임의 세대 금지)."""
    ctx = ToolContext(TENANT, USER, roles=("MANAGER",), visibilities=("ALL",))
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES))

    result = await _run(ctx, deps, "402동 201호 두꺼비집 어디?")

    assert result.card is None
    assert "확인되지 않아" in result.note


async def test_unknown_household_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES, household_found=False))

    result = await _run(MANAGER_CTX, deps, "두꺼비집 어디?")

    assert result.card is None
    assert "준비되지 않았습니다" in result.note


async def test_no_floor_plan_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES, plan_id=None))

    result = await _run(MANAGER_CTX, deps, "두꺼비집 어디?")

    assert result.card is None
    assert "준비되지 않았습니다" in result.note


async def test_no_match_returns_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES))

    result = await _run(MANAGER_CTX, deps, "보일러 어디?")

    assert result.card is None
    assert "찾지 못했습니다" in result.note


# ── 역할 가시성·격리(CRITICAL) ─────────────────────────────────────────


async def test_resident_cannot_execute_even_with_target_unit(settings: AiCoreSettings) -> None:
    """CRITICAL 인가(규칙 4) — 입주민 세션은 타 세대 평면도를 조회할 수 없다.

    레지스트리 가시성이 1차 방어라 실행 자체가 거부된다(도구 몸통의 역할 가드는 2차).
    """
    ctx = ToolContext(
        TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"), target_unit=TARGET
    )
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES))

    execution = await execute_tool(
        _call("두꺼비집 어디?"), ctx=ctx, deps=deps, registry=default_registry()
    )

    assert execution.detail == "not_visible"
    assert execution.result.card is None


async def test_tool_body_rejects_non_office_roles(settings: AiCoreSettings) -> None:
    """2차 방어(규칙 4) — 레지스트리를 우회해 몸통을 직접 불러도 역할을 다시 본다."""
    tool = find_household_devices_tool()
    ctx = ToolContext(
        TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"), target_unit=TARGET
    )
    deps = _deps(_forbidden_llm(settings), _handler(_DEVICES))

    result = await tool.run(ctx, deps, tool.args_model.model_validate({"query": "두꺼비집 어디?"}))

    assert result.card is None
    assert "권한이 없습니다" in result.note


def test_resident_specs_exclude_household_devices_tool() -> None:
    registry = default_registry()
    names = {s["function"]["name"] for s in registry.specs_for(("RESIDENT",), graph_available=True)}
    assert HOUSEHOLD_DEVICES_TOOL not in names


def test_office_specs_include_household_devices_tool() -> None:
    """노출 여부의 최종 결정은 라우터(동·호수 확정 시만)지만, 역할 집합은 관리사무소다."""
    registry = default_registry()
    for role in ("MANAGER", "STAFF"):
        names = {s["function"]["name"] for s in registry.specs_for((role,), graph_available=True)}
        assert HOUSEHOLD_DEVICES_TOOL in names, role
