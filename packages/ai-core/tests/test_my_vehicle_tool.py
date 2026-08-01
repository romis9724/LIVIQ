"""find_my_vehicle 도구 — 본인 세대 스코프(CRITICAL)·경계 케이스·거리/경과 계산 (H19-2).

SQL은 conftest.FakeSession(쿼리 텍스트 분기)으로, 기하는 실 geometry 함수로 검증한다
(test_parking_tool 관례와 동일). 실 PG·RLS는 apps/api 통합 테스트 담당.
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
from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool
from ai_core.tools.parking import MyVehicleArgs

TENANT = uuid.uuid4()
USER = uuid.uuid4()

CTX = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

# 코어 "401동"(중심 136,164)에서 001면 중심(127,142)까지 ≈ 23.8px → 약 2m(13px/m).
_CORE = {"name": "401동", "x": 100, "y": 100, "w": 72, "h": 128}
_LAYOUT = {
    "spots": [
        {"no": "001", "kind": "일반", "x": 110, "y": 110},
        {"no": "300", "kind": "일반", "x": 600, "y": 600},
    ],
    "cores": [_CORE],
}


# ── fakes ──────────────────────────────────────────────────────────────


def _handler(
    *,
    building_name: str | None = "401",
    vehicles: Sequence[Any] = (),
    has_layout: bool = True,
) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        if "join households" in s:
            assert params["uid"] == USER and params["tid"] == TENANT
            return [row(building_name=building_name)] if building_name else []
        if "from parking_layouts" in s:
            return [row(layout=_LAYOUT)] if has_layout else []
        if "from parking_vehicles" in s:
            # 읽기 전용(규칙 8) — 부수효과 SQL이 섞이면 즉시 실패.
            assert "insert" not in s and "update" not in s and "delete " not in s
            # CRITICAL — 번호판 암호문은 SELECT조차 하지 않는다(규칙 2).
            assert "plate_enc" not in s
            # CRITICAL — 본인 세대 차량만. 타 세대는 SQL 단계에서 배제된다.
            assert "v.household_id = (select u.household_id from users u" in s
            assert "u.id = :uid" in s
            # tenant 격리(규칙 3) — 차량·세대 조회 양쪽에 tenant 조건.
            assert s.count("tenant_id = :tid") == 2
            assert params["uid"] == USER and params["tid"] == TENANT
            return list(vehicles)
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
        building_id: uuid.UUID | None = None,
    ) -> list[RetrievedChunk]:
        return []


def _deps(settings: AiCoreSettings, handler: Any) -> ToolDeps:
    return ToolDeps(
        session=cast(AsyncSession, FakeSession(handler)),
        llm=_noop_llm(settings),
        retriever=cast(Retriever, _NoopRetriever()),
        graph=cast(GraphClient, None),
    )


def _vehicle(
    *, model: str | None = "아이오닉5", spot_no: str | None = "001", hours_ago: float | None = 3.0
) -> Any:
    entry_at = None if hours_ago is None else datetime.now(UTC) - timedelta(hours=hours_ago)
    return row(model=model, spot_no=spot_no, entry_at=entry_at)


def _call() -> ToolCallRequest:
    return ToolCallRequest(id="c-my", name="find_my_vehicle", arguments=json.dumps({}))


async def _run(settings: AiCoreSettings, handler: Any) -> Any:
    return (
        await execute_tool(
            _call(), ctx=CTX, deps=_deps(settings, handler), registry=default_registry()
        )
    ).result


# ── (1) 세대 미배정 → note ────────────────────────────────────────────


async def test_no_household_returns_note(settings: AiCoreSettings) -> None:
    result = await _run(settings, _handler(building_name=None))
    assert result.card is None
    assert "세대 정보를 찾을 수 없습니다" in result.note


# ── (2) 등록 차량 0대 → note(폴백 유도) ───────────────────────────────


async def test_no_registered_vehicle_returns_note(settings: AiCoreSettings) -> None:
    result = await _run(settings, _handler(vehicles=()))
    assert result.card is None
    assert "등록된 차량이 없습니다" in result.note


# ── (3) 등록됐지만 전부 미주차 → 카드 승격 + 빈자리 안내 ────────────────


async def test_all_unparked_promotes_to_card_with_hint(settings: AiCoreSettings) -> None:
    result = await _run(settings, _handler(vehicles=[_vehicle(spot_no=None)]))
    assert result.card is not None  # 확정 근거 → 카드 승격(⓪ 계약)
    assert result.card.source_kind == "tool:find_my_vehicle"
    assert "주차장에 없음" in result.card.quote
    assert "빈자리" in result.card.quote  # 시나리오 RES-1 처리순서 ③


# ── (4) 정상 — 면·경과·거리 ───────────────────────────────────────────


async def test_returns_spot_elapsed_and_distance(settings: AiCoreSettings) -> None:
    result = await _run(settings, _handler(vehicles=[_vehicle(hours_ago=3.0)]))
    assert result.card is not None
    quote = result.card.quote
    assert "- 아이오닉5: 001면 (3시간 전 입차 · 401동 승강기까지 약 2m)" in quote
    assert "데모 데이터" in quote  # 규칙 1 — 출처·데모 명시
    assert "빈자리" not in quote  # 주차돼 있으면 빈자리 안내는 붙이지 않는다


async def test_multiple_vehicles_are_all_listed(settings: AiCoreSettings) -> None:
    vehicles = [
        _vehicle(model="아이오닉5", spot_no="001", hours_ago=0.5),
        _vehicle(model=None, spot_no="300", hours_ago=30.0),
    ]
    result = await _run(settings, _handler(vehicles=vehicles))
    assert result.card is not None
    quote = result.card.quote
    assert "내 차량 2대:" in quote
    assert "- 아이오닉5: 001면 (30분 전 입차" in quote
    assert "- 차량: 300면 (1일 전 입차" in quote  # 차종 없으면 "차량"
    assert "401동 승강기까지 약 52m" in quote  # 300면은 코어에서 멀다


async def test_entry_at_null_says_unknown(settings: AiCoreSettings) -> None:
    result = await _run(settings, _handler(vehicles=[_vehicle(hours_ago=None)]))
    assert result.card is not None
    assert "입차 시각 미상" in result.card.quote


async def test_missing_layout_still_answers_without_distance(settings: AiCoreSettings) -> None:
    result = await _run(settings, _handler(vehicles=[_vehicle()], has_layout=False))
    assert result.card is not None
    assert "001면" in result.card.quote
    assert "승강기까지" not in result.card.quote


# ── (5) 화면용 data — quote와 같은 값(LLM 미노출) ──────────────────────


async def test_card_data_carries_same_values(settings: AiCoreSettings) -> None:
    result = await _run(settings, _handler(vehicles=[_vehicle(hours_ago=3.0)]))
    assert result.card is not None
    data = result.card.data
    assert data == {
        "kind": "my_vehicles",
        "core": "401동",
        "vehicles": [
            {
                "model": "아이오닉5",
                "spotNo": "001",
                "parkedSince": "3시간 전 입차",
                "distanceM": 2,
            }
        ],
    }
    # 번호판은 어떤 경로로도 나가지 않는다(규칙 2).
    assert "plate" not in json.dumps(data, ensure_ascii=False)


# ── (6) 인자·역할 가시성 ───────────────────────────────────────────────


def test_args_model_has_no_fields() -> None:
    """tenant·user·세대는 ToolContext에서만 온다(규칙 3·4) — 인자 축 자체가 없다."""
    assert MyVehicleArgs.model_fields == {}


def test_resident_specs_include_my_vehicle_tool() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("RESIDENT",), graph_available=True)
    }
    assert "find_my_vehicle" in names


def test_manager_specs_exclude_my_vehicle_tool() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("MANAGER",), graph_available=True)
    }
    assert "find_my_vehicle" not in names
