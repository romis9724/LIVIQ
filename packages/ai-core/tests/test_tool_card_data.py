"""ToolCard.data — 화면 전용 구조화 페이로드 스냅샷 (ADR-0025 §6).

도구 4종(관리비·주차·시설·유사민원)이 내는 `data`의 모양을 못 박는다. 프론트(H18-3)가
`kind`로 분기하므로 키가 바뀌면 화면이 조용히 빈다.

**불변식: `data`는 LLM에 가지 않는다.** 여기서는 `llm_text()`·quote에 data가 섞이지
않는 것만 보고, 프롬프트 전량 검사는 test_orchestrator가 담당한다(규칙 5·8).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
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

CTX_RESIDENT = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))
CTX_MANAGER = ToolContext(TENANT, USER, roles=("MANAGER",), visibilities=("ALL", "ADMIN"))


# ── fakes ──────────────────────────────────────────────────────────────


def _noop_llm(settings: AiCoreSettings) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"이 도구들은 LLM을 호출하지 않는다: {request.url.path}")

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


def _call(name: str, args: object) -> ToolCallRequest:
    return ToolCallRequest(id=f"c-{name}", name=name, arguments=json.dumps(args))


async def _data(
    settings: AiCoreSettings, name: str, args: object, handler: Any, ctx: ToolContext
) -> dict[str, Any]:
    result = (
        await execute_tool(
            _call(name, args), ctx=ctx, deps=_deps(settings, handler), registry=default_registry()
        )
    ).result
    assert result.card is not None
    # 불변식: LLM에 되먹이는 텍스트는 title+quote뿐 — data는 어디에도 섞이지 않는다.
    assert result.card.data is not None
    assert "kind" in result.card.data  # 프론트 분기 키(필수)
    assert json.dumps(result.card.data, ensure_ascii=False) not in result.llm_text()
    return result.card.data


# ── get_fees → fee_table ───────────────────────────────────────────────


def _fee_handler(sql: str, params: dict[str, Any]) -> list[Any]:
    s = sql.lower()
    if "from users" in s:
        return [row(household_id=HOUSEHOLD, approved_at=datetime(2020, 1, 1, tzinfo=UTC))]
    if "from fees" in s:
        if params.get("period") == "2026-06":
            return [
                row(
                    breakdown=[
                        {"name": "일반관리비", "level": 0, "amount": 50000},
                        {"name": "인건비", "level": 1, "amount": 30000},  # 하위 항목 — 표에서 제외
                        {"name": "청소비", "level": 0, "amount": 20000},
                        {"name": "합계", "level": 0, "amount": 100000},  # total과 중복 — 제외
                    ],
                    total_amount=100000,
                )
            ]
        if params.get("period") == "2026-05":
            return [row(breakdown=[], total_amount=90000)]
    return []


async def test_get_fees_data_is_a_fee_table_with_total_and_diff(
    settings: AiCoreSettings,
) -> None:
    data = await _data(settings, "get_fees", {"period": "2026-06"}, _fee_handler, CTX_RESIDENT)
    assert data == {
        "kind": "fee_table",
        "period": "2026-06",
        "rows": [
            {"name": "일반관리비", "amount": 50000},
            {"name": "청소비", "amount": 20000},
        ],
        "total": 100000,
        "prev_total": 90000,
        "diff": 10000,
    }


async def test_get_fees_data_matches_quote_numbers(settings: AiCoreSettings) -> None:
    """화면 값(data)과 LLM에 준 값(quote)이 같은 숫자여야 한다 — 규칙 5(단일 출처)."""
    result = (
        await execute_tool(
            _call("get_fees", {"period": "2026-06"}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, _fee_handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None and result.card.data is not None
    assert f"{result.card.data['total']:,}원" in result.card.quote
    assert f"{result.card.data['prev_total']:,}원 대비" in result.card.quote


# ── find_nearest_available_parking → parking_spots ─────────────────────

_LAYOUT = {
    "spots": [
        {"no": "001", "kind": "일반", "x": 110, "y": 110},
        {"no": "002", "kind": "일반", "x": 300, "y": 300},
    ],
    "cores": [{"name": "401동", "x": 100, "y": 100, "w": 72, "h": 128}],
}


def _parking_handler(sql: str, params: dict[str, Any]) -> list[Any]:
    s = sql.lower()
    if "from users" in s:
        return [row(building_name="401")]
    if "from parking_layouts" in s:
        return [row(layout=_LAYOUT)]
    if "from parking_vehicles" in s:
        return [row(spot_no="001")]  # 001 점유 → 002만 남는다
    return []


async def test_parking_data_lists_spot_no_kind_and_distance(settings: AiCoreSettings) -> None:
    data = await _data(
        settings,
        "find_nearest_available_parking",
        {"ev_preferred": False},
        _parking_handler,
        CTX_RESIDENT,
    )
    assert data["kind"] == "parking_spots"
    assert [s["no"] for s in data["spots"]] == ["002"]  # 001은 점유 중
    spot = data["spots"][0]
    assert spot["kind"] == "일반"
    assert isinstance(spot["distance_m"], (int, float))


async def test_parking_data_distance_matches_quote(settings: AiCoreSettings) -> None:
    """면번호·거리는 도구가 확정한 값 — 화면과 LLM에 같은 값이 간다(규칙 8)."""
    result = (
        await execute_tool(
            _call("find_nearest_available_parking", {"ev_preferred": False}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, _parking_handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None and result.card.data is not None
    spot = result.card.data["spots"][0]
    assert f"{spot['no']}면" in result.card.quote
    assert f"약 {spot['distance_m']}m" in result.card.quote


# ── get_facilities → facility_status ───────────────────────────────────


def _facility_handler(sql: str, params: dict[str, Any]) -> list[Any]:
    return [
        row(name="승강기1", status="normal", code="EL-101-01"),
        row(name="승강기2", status="fault", code="EL-102-01"),
        row(name="CCTV1", status="normal", code="CM-401-01"),
    ]


async def test_facility_data_counts_by_status_and_lists_items(settings: AiCoreSettings) -> None:
    data = await _data(settings, "get_facilities", {}, _facility_handler, CTX_MANAGER)
    assert data == {
        "kind": "facility_status",
        "total": 3,
        "status_counts": {"normal": 2, "fault": 1},
        "items": [
            {"name": "승강기1", "status": "normal", "code": "EL-101-01"},
            {"name": "승강기2", "status": "fault", "code": "EL-102-01"},
            {"name": "CCTV1", "status": "normal", "code": "CM-401-01"},
        ],
    }


async def test_facility_data_total_matches_quote_count(settings: AiCoreSettings) -> None:
    """총수는 전수 집계 — 화면 카운트와 LLM에 준 카운트가 갈라지면 안 된다."""
    result = (
        await execute_tool(
            _call("get_facilities", {}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, _facility_handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None and result.card.data is not None
    assert f"총 {result.card.data['total']}개" in result.card.quote


# ── search_similar_inquiries → inquiry_cases ───────────────────────────


def _inquiry_handler(sql: str, params: dict[str, Any]) -> list[Any]:
    return [
        row(
            title="화장실 천장 누수",
            status="done",
            category_label="누수",
            is_mine=False,
            reply_body="위층 배관 이음부를 교체했습니다.",
        ),
        row(
            title="세탁실 배수 역류",
            status="in_progress",
            category_label=None,
            is_mine=True,
            reply_body=None,
        ),
    ]


async def test_inquiry_data_lists_title_category_and_resolution(
    settings: AiCoreSettings,
) -> None:
    data = await _data(
        settings, "search_similar_inquiries", {"query": "누수"}, _inquiry_handler, CTX_RESIDENT
    )
    assert data == {
        "kind": "inquiry_cases",
        "cases": [
            {
                "title": "화장실 천장 누수",
                "category": "누수",
                "status": "완료",
                "resolution": "위층 배관 이음부를 교체했습니다.",
                "is_mine": False,
            },
            {
                "title": "세탁실 배수 역류",
                "category": "분류없음",
                "status": "처리중",
                "resolution": "관리사무소가 처리 중",
                "is_mine": True,
            },
        ],
    }


async def test_inquiry_data_carries_no_author_or_address(settings: AiCoreSettings) -> None:
    """노출 범위는 quote와 동일 — 작성자·동호수·본문은 애초에 SELECT하지 않는다(규칙 2)."""
    data = await _data(
        settings, "search_similar_inquiries", {"query": "누수"}, _inquiry_handler, CTX_RESIDENT
    )
    keys = {key for case in data["cases"] for key in case}
    assert keys == {"title", "category", "status", "resolution", "is_mine"}
