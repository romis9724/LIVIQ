"""관리자 운영 도구 2종(H19-3, ADR-0026 결정 2) — 역할 가드·미노출 컬럼·집계·경계.

`find_longterm_parking`(FACILITY·MANAGER) · `summarize_inquiries`(MANAGER·STAFF).

SQL은 conftest.FakeSession(쿼리 텍스트 분기)으로 검증한다 — 집계 자체는 PG의 몫이고
여기서는 **노출 경계(SELECT 목록)·tenant 조건·포매팅·경과 계산**을 본다(test_inquiries_tool 관례).
"""

from __future__ import annotations

import json
import uuid
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
from ai_core.tools.inquiries import SummarizeInquiriesArgs
from ai_core.tools.library import LongtermParkingArgs

TENANT = uuid.uuid4()
USER = uuid.uuid4()

MANAGER_CTX = ToolContext(TENANT, USER, roles=("MANAGER",), visibilities=("ALL", "ADMIN"))
STAFF_CTX = ToolContext(TENANT, USER, roles=("STAFF",), visibilities=("ALL", "ADMIN"))
RESIDENT_CTX = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

NOW = datetime.now(UTC)


# ── fakes ──────────────────────────────────────────────────────────────


def _noop_llm(settings: AiCoreSettings) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"이 도구는 LLM을 호출하지 않는다: {request.url.path}")

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


class _NoopRetriever:
    async def search(
        self,
        query_embedding: Any,
        *,
        tenant_id: uuid.UUID,
        visibilities: Any,
        top_k: int = 8,
        building_id: uuid.UUID | None = None,
    ) -> list[RetrievedChunk]:
        return []


def _deps(settings: AiCoreSettings, session: FakeSession) -> ToolDeps:
    return ToolDeps(
        session=cast(AsyncSession, session),
        llm=_noop_llm(settings),
        retriever=cast(Retriever, _NoopRetriever()),
        graph=cast(GraphClient, None),
    )


def _names(role: str) -> set[str]:
    return {
        s["function"]["name"] for s in default_registry().specs_for((role,), graph_available=True)
    }


# ══ find_longterm_parking ══════════════════════════════════════════════


def _parking_handler(rows: list[Any]) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        assert "from parking_vehicles" in s
        # 읽기 전용(규칙 8).
        assert "insert" not in s and "update" not in s and "delete " not in s
        # 규칙 2 — 번호판 암호문은 SELECT 자체를 하지 않는다(복호·마스킹 실패 경로 제거).
        select_list = s.split(" from parking_vehicles")[0]
        assert "plate_enc" not in select_list
        assert "plate" not in s
        # 외부 차량(세대 미배정) 중 주차 중인 면만.
        assert "household_id is null" in s
        assert "spot_no is not null" in s
        assert params["tid"] == TENANT
        return rows

    return handler


def _parking_call(**args: Any) -> ToolCallRequest:
    return ToolCallRequest(id="c-lp", name="find_longterm_parking", arguments=json.dumps(args))


async def test_longterm_parking_lists_spot_and_elapsed_hours(settings: AiCoreSettings) -> None:
    # SQL이 오래된 순으로 준다 — 카드도 그 순서를 유지한다(경과 내림차순).
    rows = [
        row(spot_no="B-012", entry_at=NOW - timedelta(hours=73, minutes=30)),
        row(spot_no="B-101", entry_at=NOW - timedelta(hours=31, minutes=5)),
    ]
    session = FakeSession(_parking_handler(rows))
    result = (
        await execute_tool(
            _parking_call(hours=24),
            ctx=MANAGER_CTX,
            deps=_deps(settings, session),
            registry=default_registry(),
        )
    ).result

    assert result.card is not None
    quote = result.card.quote
    assert result.card.source_kind == "tool:find_longterm_parking"
    assert quote.startswith("24시간 이상 주차된 외부 차량 2대(오래된 순):")
    # 경과는 도구가 계산한다 — 시간 단위 내림(73h30m → 73, 31h05m → 31).
    assert "- B-012면 (73시간 경과)" in quote
    assert "- B-101면 (31시간 경과)" in quote
    assert quote.index("B-012") < quote.index("B-101")
    # 임계 시각은 요청 시각 - hours(테스트 시각과 초 단위 오차 허용).
    _, params = session.executed[0]
    assert abs((params["threshold"] - (NOW - timedelta(hours=24))).total_seconds()) < 5


async def test_longterm_parking_zero_rows_promotes_to_card(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _parking_call(hours=48),
            ctx=MANAGER_CTX,
            deps=_deps(settings, FakeSession(_parking_handler([]))),
            registry=default_registry(),
        )
    ).result

    assert result.card is not None  # note면 인용 카드가 없어 폴백된다(⓪ 계약)
    assert result.note == ""
    assert "48시간 이상 주차된 외부 차량이 없습니다" in result.card.quote


async def test_longterm_parking_defaults_to_24_hours(settings: AiCoreSettings) -> None:
    session = FakeSession(_parking_handler([]))
    result = (
        await execute_tool(
            _parking_call(),
            ctx=MANAGER_CTX,
            deps=_deps(settings, session),
            registry=default_registry(),
        )
    ).result

    assert result.card is not None
    assert "24시간 이상" in result.card.quote


async def test_longterm_parking_rejects_out_of_range_hours(settings: AiCoreSettings) -> None:
    session = FakeSession(_parking_handler([]))
    for hours in (0, 169):
        execution = await execute_tool(
            _parking_call(hours=hours),
            ctx=MANAGER_CTX,
            deps=_deps(settings, session),
            registry=default_registry(),
        )
        assert execution.detail == "invalid_args"
    assert session.executed == []  # 검증 실패면 쿼리 자체가 안 나간다


def test_longterm_parking_visible_to_facility_roles_only() -> None:
    assert "find_longterm_parking" in _names("MANAGER")
    assert "find_longterm_parking" in _names("FACILITY")
    for role in ("RESIDENT", "STAFF"):
        assert "find_longterm_parking" not in _names(role)


async def test_longterm_parking_denied_for_resident(settings: AiCoreSettings) -> None:
    session = FakeSession(_parking_handler([]))
    execution = await execute_tool(
        _parking_call(),
        ctx=RESIDENT_CTX,
        deps=_deps(settings, session),
        registry=default_registry(),
    )

    assert execution.detail == "not_visible"
    assert execution.result.card is None
    assert session.executed == []  # 스펙 비노출 + 실행 경로 거부(이중 방어, 규칙 4)


def test_longterm_parking_args_have_no_tenant_field() -> None:
    assert set(LongtermParkingArgs.model_fields) == {"hours"}


# ══ summarize_inquiries ════════════════════════════════════════════════

_STATUS_ROWS = [
    row(status=None, cnt=12),  # ROLLUP 총계
    row(status="received", cnt=5),
    row(status="in_progress", cnt=4),
    row(status="done", cnt=3),
]
_CATEGORY_ROWS = [row(category_label="누수", cnt=7), row(category_label=None, cnt=5)]
_PENDING_ROWS = [
    row(
        title="화장실 천장 누수",
        status="received",
        category_label="누수",
        created_at=NOW - timedelta(days=3, hours=4),
    ),
    row(
        title="복도 등 점멸",
        status="assigned",
        category_label=None,
        created_at=NOW - timedelta(days=1),
    ),
]


def _inquiry_handler(
    *,
    status_rows: list[Any] = _STATUS_ROWS,
    category_rows: list[Any] = _CATEGORY_ROWS,
    pending_rows: list[Any] = _PENDING_ROWS,
    dong: str | None = None,
) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        assert "from inquiries i" in s
        # 읽기 전용(규칙 8).
        assert "insert" not in s and "update" not in s and "delete " not in s
        # 규칙 2 — 본문·작성자·동호수는 어느 쿼리의 SELECT 목록에도 없다. 동은 필터
        # (households·buildings 조인)로만 쓰고 값을 내보내지 않는다.
        select_list = s.split(" from inquiries")[0]
        assert "i.body" not in select_list
        assert "author_user_id" not in select_list
        assert "household" not in select_list
        assert "unit_no" not in select_list and "b.name" not in select_list
        # tenant·기간·동은 전부 파라미터.
        assert "i.tenant_id = :tid" in s and "i.deleted_at is null" in s
        assert "i.created_at >= :since" in s
        assert "b.name = cast(:dong as text)" in s
        assert params["tid"] == TENANT and params["dong"] == dong

        if "rollup" in s:
            assert "group by rollup(i.status)" in s  # 총계는 SQL이 센다(파이썬 재계산 없음)
            return status_rows
        if "group by c.label" in s:
            return category_rows
        assert "i.status in ('received', 'assigned', 'reopened')" in s
        assert params["lim"] == 5
        return pending_rows

    return handler


def _inquiry_call(**args: Any) -> ToolCallRequest:
    return ToolCallRequest(id="c-si", name="summarize_inquiries", arguments=json.dumps(args))


async def test_summarize_reports_counts_and_pending_list(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _inquiry_call(days=7),
            ctx=MANAGER_CTX,
            deps=_deps(settings, FakeSession(_inquiry_handler())),
            registry=default_registry(),
        )
    ).result

    assert result.card is not None
    quote = result.card.quote
    assert result.card.source_kind == "tool:summarize_inquiries"
    # 총 건수는 ROLLUP 총계 행 그대로, 상태·유형은 한글 라벨.
    assert quote.startswith("최근 7일 접수 민원 12건")
    assert "- 상태별: 미배정 5건, 처리중 4건, 완료 3건" in quote
    assert "- 유형별: 누수 7건, 분류없음 5건" in quote
    # 미처리 목록은 제목·분류·상태·경과일까지만. 목록은 상한 5건으로 잘리므로 머리말에
    # 건수를 쓰지 않는다(상태별 집계 수치와 어긋난 숫자가 답변에 섞이는 것을 막는다).
    assert "미처리 우선 목록(오래된 순):" in quote
    assert "미처리 2건" not in quote
    assert "- [누수] 화장실 천장 누수 (미배정 · 3일 경과)" in quote
    assert "- [분류없음] 복도 등 점멸 (배정됨 · 1일 경과)" in quote


async def test_summarize_filters_by_dong(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _inquiry_call(days=30, dong="404"),
            ctx=STAFF_CTX,
            deps=_deps(settings, FakeSession(_inquiry_handler(dong="404"))),
            registry=default_registry(),
        )
    ).result

    assert result.card is not None
    assert result.card.quote.startswith("최근 30일 · 404동 접수 민원 12건")


async def test_summarize_zero_rows_promotes_to_card(settings: AiCoreSettings) -> None:
    """존재하지 않는 동·빈 기간 — ROLLUP 총계가 0이면 집계·목록 쿼리는 나가지 않는다."""
    session = FakeSession(_inquiry_handler(status_rows=[row(status=None, cnt=0)], dong="999"))
    result = (
        await execute_tool(
            _inquiry_call(dong="999"),
            ctx=MANAGER_CTX,
            deps=_deps(settings, session),
            registry=default_registry(),
        )
    ).result

    assert result.card is not None  # note면 인용 카드가 없어 폴백된다(⓪ 계약)
    assert result.note == ""
    assert result.card.quote == "최근 7일 · 999동에 접수된 민원이 없습니다."
    assert len(session.executed) == 1


async def test_summarize_pending_absent_says_so(settings: AiCoreSettings) -> None:
    result = (
        await execute_tool(
            _inquiry_call(),
            ctx=MANAGER_CTX,
            deps=_deps(settings, FakeSession(_inquiry_handler(pending_rows=[]))),
            registry=default_registry(),
        )
    ).result

    assert result.card is not None
    assert "미처리(미배정·배정됨·재확인) 민원은 없습니다." in result.card.quote


async def test_summarize_rejects_out_of_range_days(settings: AiCoreSettings) -> None:
    session = FakeSession(_inquiry_handler())
    for days in (0, 91):
        execution = await execute_tool(
            _inquiry_call(days=days),
            ctx=MANAGER_CTX,
            deps=_deps(settings, session),
            registry=default_registry(),
        )
        assert execution.detail == "invalid_args"
    assert session.executed == []


def test_summarize_visible_to_office_roles_only() -> None:
    for role in ("MANAGER", "STAFF"):
        assert "summarize_inquiries" in _names(role)
    for role in ("RESIDENT", "FACILITY", "SYS_ADMIN"):
        assert "summarize_inquiries" not in _names(role)


async def test_summarize_denied_for_resident(settings: AiCoreSettings) -> None:
    session = FakeSession(_inquiry_handler())
    execution = await execute_tool(
        _inquiry_call(),
        ctx=RESIDENT_CTX,
        deps=_deps(settings, session),
        registry=default_registry(),
    )

    assert execution.detail == "not_visible"
    assert execution.result.card is None
    assert session.executed == []


async def test_summarize_tenant_comes_from_context_not_llm_args(settings: AiCoreSettings) -> None:
    session = FakeSession(_inquiry_handler())
    # LLM이 tenant_id를 주입하려 해도 인자 모델이 흘려보내지 않는다(규칙 3·4).
    call = ToolCallRequest(
        id="c-si",
        name="summarize_inquiries",
        arguments=json.dumps({"days": 7, "tenant_id": str(uuid.uuid4())}),
    )
    await execute_tool(
        call, ctx=MANAGER_CTX, deps=_deps(settings, session), registry=default_registry()
    )

    for _, params in session.executed:
        assert params["tid"] == TENANT


def test_summarize_args_have_no_tenant_field() -> None:
    assert set(SummarizeInquiriesArgs.model_fields) == {"days", "dong"}
