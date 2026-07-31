"""find_nearest_available_parking 도구 — 세대→동 해석·배치도/점유 조회·최근접 top_k·읽기 전용.

점유는 parking_vehicles.spot_no(H16 — 별도 테이블 폐기, ADR-0023 개정).

SQL은 conftest.FakeSession(쿼리 텍스트 분기)으로, 기하는 실 geometry 함수로 검증한다
(test_floor_plan_tool·test_trace_home_device 관례와 동일). 실 PG·RLS는 apps/api 통합 테스트 담당.
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

CTX = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

# 코어 "401동" 근처에 일반·전기차·장애인 면 + 먼 일반 면. 좌표는 코어(x=100)에서의 거리 순.
_CORE = {"name": "401동", "x": 100, "y": 100, "w": 72, "h": 128}
_SPOTS = [
    {"no": "001", "kind": "일반", "x": 110, "y": 110},  # 가장 가까움
    {"no": "002", "kind": "장애인", "x": 120, "y": 110},  # 항상 제외
    {"no": "003", "kind": "전기차", "x": 130, "y": 110},  # ev_preferred일 때만
    {"no": "004", "kind": "일반", "x": 300, "y": 300},  # 멀지만 일반
    {"no": "005", "kind": "일반", "x": 600, "y": 600},  # 가장 멂
]
_LAYOUT = {"spots": _SPOTS, "cores": [_CORE]}


# ── fakes ──────────────────────────────────────────────────────────────


def _handler(
    *,
    building_name: str | None = "401",
    has_layout: bool = True,
    occupied: Sequence[str] = (),
) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        if "from users" in s:
            assert params["uid"] == USER  # 세대 스코프(CRITICAL) — 항상 ctx.user_id로 해석
            assert params["tid"] == TENANT
            return [row(building_name=building_name)] if building_name else []
        if "from parking_layouts" in s:
            return [row(layout=_LAYOUT)] if has_layout else []
        if "from parking_vehicles" in s:
            assert "spot_no is not null" in s  # 미주차 차량(spot_no NULL)은 점유가 아니다
            return [row(spot_no=no) for no in occupied]
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


def _deps(settings: AiCoreSettings, handler: Any) -> ToolDeps:
    return ToolDeps(
        session=cast(AsyncSession, FakeSession(handler)),
        llm=_noop_llm(settings),
        retriever=cast(Retriever, _NoopRetriever()),
        graph=cast(GraphClient, None),
    )


def _call(*, ev_preferred: bool = False) -> ToolCallRequest:
    return ToolCallRequest(
        id="c-park",
        name="find_nearest_available_parking",
        arguments=json.dumps({"ev_preferred": ev_preferred}),
    )


# ── (1) 세대 미해결 → note ────────────────────────────────────────────


async def test_no_household_returns_note(settings: AiCoreSettings) -> None:
    deps = _deps(settings, _handler(building_name=None))
    result = (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result
    assert result.card is None
    assert "세대 정보를 찾을 수 없습니다" in result.note


# ── (2) 배치도 없음 → note ────────────────────────────────────────────


async def test_no_layout_returns_note(settings: AiCoreSettings) -> None:
    deps = _deps(settings, _handler(has_layout=False))
    result = (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result
    assert result.card is None
    assert "주차장 배치도가 없습니다" in result.note


# ── (3) 빈자리 없음 → 카드 승격(note 아님) ──────────────────────────────


async def test_no_available_spot_promotes_to_card(settings: AiCoreSettings) -> None:
    # 일반 면 전부 점유 + 전기차 미선호 → 후보 없음.
    deps = _deps(settings, _handler(occupied=("001", "004", "005")))
    result = (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result
    assert result.card is not None  # 확정 근거 → 카드 승격(⓪ 계약)
    assert result.card.source_kind == "tool:find_nearest_available_parking"
    assert "가까운 빈 주차자리가 없습니다" in result.card.quote


# ── (4) 정상 top_k — 거리순·장애인 제외·데모 명시 ────────────────────────


async def test_returns_nearest_spots_sorted(settings: AiCoreSettings) -> None:
    deps = _deps(settings, _handler())
    result = (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result
    assert result.card is not None
    quote = result.card.quote
    # 일반 면만·거리 오름차순: 001 → 004 → 005. 장애인(002)·전기차(003) 제외.
    assert "① 001면 (일반" in quote
    assert "② 004면 (일반" in quote
    assert "③ 005면 (일반" in quote
    assert "002면" not in quote and "003면" not in quote
    assert "데모 데이터" in quote  # 규칙 1 — 출처·데모 명시


# ── (5) ev_preferred → 전기차 면 포함 ──────────────────────────────────


async def test_ev_preferred_includes_ev_spot(settings: AiCoreSettings) -> None:
    deps = _deps(settings, _handler())
    result = (
        await execute_tool(
            _call(ev_preferred=True), ctx=CTX, deps=deps, registry=default_registry()
        )
    ).result
    assert result.card is not None
    quote = result.card.quote
    # 전기차(003)가 후보에 포함되고 거리순으로 001·003·004 상위 3면.
    assert "003면 (전기차" in quote
    assert "002면" not in quote  # 장애인은 여전히 제외


# ── 역할 가시성(RESIDENT 전용) ─────────────────────────────────────────


def test_resident_specs_include_parking_tool() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("RESIDENT",), graph_available=True)
    }
    assert "find_nearest_available_parking" in names


def test_manager_specs_exclude_parking_tool() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("MANAGER",), graph_available=True)
    }
    assert "find_nearest_available_parking" not in names
