"""find_in_floor_plan 도구 실행 — 본인 세대 스코프·도면 없음·LLM 보조 경로·읽기 전용.

SQL은 conftest.FakeSession(가짜 세션, 쿼리 텍스트 분기)으로 검증한다(실 PG는
apps/api 통합 테스트 담당 — test_tools.py 관례와 동일).
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

TENANT = uuid.uuid4()
USER = uuid.uuid4()
HOUSEHOLD = uuid.uuid4()
UNIT_TYPE_ID = uuid.uuid4()
PLAN_ID = uuid.uuid4()

CTX = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

_LIVING_ROOM_DEVICES = [
    row(device_type="room", room="거실", dir=None),
    row(device_type="콘센트", room="거실", dir="left"),
    row(device_type="콘센트", room="거실", dir="right"),
    row(device_type="화재감지기", room="거실", dir=None),
]


# ── fakes ──────────────────────────────────────────────────────────────


def _plan_handler(
    devices: Sequence[Any],
    *,
    household_id: uuid.UUID | None = HOUSEHOLD,
    label: str | None = "84M(공공임대)",
    unit_type_id: uuid.UUID | None = UNIT_TYPE_ID,
    plan_id: uuid.UUID | None = PLAN_ID,
) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        if "from users" in s:
            assert params["uid"] == USER  # 본인 세대 스코프(CRITICAL) — 항상 ctx.user_id로 조회
            assert params["tid"] == TENANT
            return [row(household_id=household_id)] if household_id else [row(household_id=None)]
        if "from household_geometries" in s:
            assert params["hid"] == household_id
            return [row(unit_type_label=label)] if label else []
        if "from unit_types" in s:
            assert params["name"] == "84M"  # 괄호 이하 정규화 확인
            return [row(id=unit_type_id)] if unit_type_id else []
        if "from floor_plans" in s:
            assert params["utid"] == unit_type_id
            return [row(id=plan_id)] if plan_id else []
        if "from plan_devices" in s:
            assert params["pid"] == plan_id
            return list(devices)
        return []

    return handler


def _forbidden_llm(settings: AiCoreSettings) -> LlmClient:
    """파서 성공 경로에서 LLM이 절대 호출되지 않아야 함(CRITICAL)을 트랜스포트 레벨로 강제."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"파서 성공 경로인데 LLM이 호출됨: {request.url.path}")

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


def _tool_call_llm(settings: AiCoreSettings, elements: list[str], rooms: list[str]) -> LlmClient:
    """LLM 보조 경로 — extract_floor_plan_spec 도구 호출 응답을 고정 반환."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {
                                    "name": "extract_floor_plan_spec",
                                    "arguments": json.dumps({"elements": elements, "rooms": rooms}),
                                },
                            }
                        ],
                    }
                }
            ]
        }
        return httpx.Response(200, json=body)

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


def _deps(llm: LlmClient, handler: Any) -> ToolDeps:
    session = FakeSession(handler)
    return ToolDeps(
        session=cast(AsyncSession, session),
        llm=llm,
        retriever=cast(Retriever, _NoopRetriever()),
        graph=cast(GraphClient, None),
    )


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


def _call(query: str) -> ToolCallRequest:
    return ToolCallRequest(
        id="c-plan", name="find_in_floor_plan", arguments=json.dumps({"query": query})
    )


# ── 파서 성공 경로(LLM 미호출) ───────────────────────────────────────────


async def test_room_and_element_query_returns_card(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler(_LIVING_ROOM_DEVICES))
    result = (
        await execute_tool(
            _call("거실 콘센트 어디야"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is not None
    assert result.card.source_kind == "tool:find_in_floor_plan"
    assert "거실 콘센트 2곳" in result.card.quote
    assert "왼쪽" in result.card.quote and "오른쪽" in result.card.quote


async def test_room_only_query_returns_room_position(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler(_LIVING_ROOM_DEVICES))
    result = (
        await execute_tool(_call("거실이 어디야"), ctx=CTX, deps=deps, registry=default_registry())
    ).result
    assert result.card is not None
    assert "거실 위치" in result.card.quote


async def test_no_match_in_plan_returns_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler(_LIVING_ROOM_DEVICES))
    result = (
        await execute_tool(_call("보일러 어디야"), ctx=CTX, deps=deps, registry=default_registry())
    ).result
    assert result.card is None
    assert "찾지 못했습니다" in result.note


# ── 도면 없음(오류 아님) ─────────────────────────────────────────────────


async def test_no_household_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler(_LIVING_ROOM_DEVICES, household_id=None))
    result = (
        await execute_tool(
            _call("거실 콘센트 어디야"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is None
    assert "준비되지 않았습니다" in result.note


async def test_no_geometry_label_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler(_LIVING_ROOM_DEVICES, label=None))
    result = (
        await execute_tool(
            _call("거실 콘센트 어디야"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert "준비되지 않았습니다" in result.note


async def test_no_matching_unit_type_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler(_LIVING_ROOM_DEVICES, unit_type_id=None))
    result = (
        await execute_tool(
            _call("거실 콘센트 어디야"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert "준비되지 않았습니다" in result.note


async def test_no_floor_plan_row_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler(_LIVING_ROOM_DEVICES, plan_id=None))
    result = (
        await execute_tool(
            _call("거실 콘센트 어디야"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert "준비되지 않았습니다" in result.note


async def test_empty_devices_returns_not_ready_note(settings: AiCoreSettings) -> None:
    deps = _deps(_forbidden_llm(settings), _plan_handler([]))
    result = (
        await execute_tool(
            _call("거실 콘센트 어디야"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert "준비되지 않았습니다" in result.note


# ── LLM 보조(파서 실패 시만 호출·enum 밖 값 폐기) ─────────────────────────


async def test_llm_assist_called_only_when_parser_fails(settings: AiCoreSettings) -> None:
    llm = _tool_call_llm(settings, elements=["콘센트"], rooms=["거실"])
    deps = _deps(llm, _plan_handler(_LIVING_ROOM_DEVICES))
    result = (
        await execute_tool(
            _call("전기 나갔을 때 어디 봐야해"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is not None
    assert "거실 콘센트 2곳" in result.card.quote


async def test_llm_assist_discards_values_outside_known_enum(settings: AiCoreSettings) -> None:
    # "냉장고"·"주방"은 이 도면에 없는 값 — 폐기되고 남은 유효 값만 사용.
    llm = _tool_call_llm(settings, elements=["콘센트", "냉장고"], rooms=["주방"])
    deps = _deps(llm, _plan_handler(_LIVING_ROOM_DEVICES))
    result = (
        await execute_tool(
            _call("전기 나갔을 때 어디 봐야해"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is not None
    # rooms 필터("주방")가 폐기돼 elements(콘센트)만으로 매칭 → 거실 콘센트 2곳 그대로.
    assert "거실 콘센트 2곳" in result.card.quote


async def test_llm_assist_no_usable_result_returns_note(settings: AiCoreSettings) -> None:
    llm = _tool_call_llm(settings, elements=[], rooms=[])
    deps = _deps(llm, _plan_handler(_LIVING_ROOM_DEVICES))
    result = (
        await execute_tool(
            _call("전기 나갔을 때 어디 봐야해"), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is None
    assert "특정하지 못했습니다" in result.note


# ── 역할 가시성(RESIDENT) ──────────────────────────────────────────────


def test_manager_specs_exclude_floor_plan_tool() -> None:
    registry = default_registry()
    names = {s["function"]["name"] for s in registry.specs_for(("MANAGER",), graph_available=True)}
    assert "find_in_floor_plan" not in names


def test_resident_specs_include_floor_plan_tool() -> None:
    registry = default_registry()
    names = {s["function"]["name"] for s in registry.specs_for(("RESIDENT",), graph_available=True)}
    assert "find_in_floor_plan" in names
