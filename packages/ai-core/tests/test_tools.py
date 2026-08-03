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
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.graph import GraphClient, IncidentContext, IncidentHit
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool
from ai_core.tools.library import MIN_PEER_SAMPLE, GetFeesArgs

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


def _embed_llm(
    settings: AiCoreSettings, *, ok: bool = True, embedded: list[str] | None = None
) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            if not ok:
                return httpx.Response(400)  # 4xx → LlmError(재시도 없음)
            inputs = json.loads(request.content)["input"]
            if embedded is not None:
                embedded.extend(inputs)
            n = len(inputs)
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
    embedded: list[str] | None = None,
) -> ToolDeps:
    session = FakeSession(handler or (lambda sql, params: []))
    return ToolDeps(
        session=cast(AsyncSession, session),
        llm=_embed_llm(settings, ok=embed_ok, embedded=embedded),
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


async def test_search_documents_embeds_expanded_life_synonyms(settings: AiCoreSettings) -> None:
    """'두꺼비집'은 문서에 없는 말이다(H20-7) — 임베딩 텍스트만 표준어로 넓힌다."""
    embedded: list[str] = []
    await execute_tool(
        _call("search_documents", {"query": "두꺼비집 점검 주기"}),
        ctx=CTX_RESIDENT,
        deps=_deps(settings, chunks=[_chunk()], embedded=embedded),
        registry=default_registry(),
    )
    assert embedded == ["두꺼비집 점검 주기 (분전함)"]


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


# ── get_fees 여러 달 조회·평균 (2026-08-01 사고 회귀) ───────────────────


def _multi_fee_handler(
    totals: dict[str, int], *, approved: datetime = datetime(2020, 1, 1, tzinfo=UTC)
) -> Any:
    """요청 월 중 totals에 있는 달만 행으로 돌려주는 가짜 세션.

    avg_total은 실제로는 SQL 윈도우 집계(`avg(...) OVER ()`)가 내는 값이라, 가짜 세션이
    그 자리를 대신 채운다 — 도구 코드는 이 값을 그대로 싣기만 해야 한다(파이썬 산술 금지).
    """

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        if "from users" in s:
            return [row(household_id=HOUSEHOLD, approved_at=approved)]
        if "any(:periods)" in s:
            found = [p for p in params["periods"] if p in totals]
            avg = round(sum(totals[p] for p in found) / len(found)) if found else None
            return [row(period=p, total_amount=totals[p], avg_total=avg) for p in found]
        return []

    return handler


async def _multi_fee_result(settings: AiCoreSettings, handler: Any, period: str) -> Any:
    return (
        await execute_tool(
            _call("get_fees", {"period": period}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result


async def test_get_fees_multi_month_average_is_confirmed_by_the_tool(
    settings: AiCoreSettings,
) -> None:
    """여러 달을 물으면 도구가 평균을 확정해 카드에 담는다 — 모델이 나눌 거리가 없다.

    사고 재현: 단일 월만 받던 시절 "6,7월 평균"에 모델이 7월 값 하나를 2로 나눠 답했다.
    """
    handler = _multi_fee_handler({"2026-06": 100_000, "2026-07": 120_000})
    result = await _multi_fee_result(settings, handler, "2026-06,2026-07")
    assert result.card is not None
    assert "2026-06 합계 100,000원" in result.card.quote
    assert "2026-07 합계 120,000원" in result.card.quote
    assert "2개월 평균 총액 110,000원" in result.card.quote
    assert result.card.data is not None
    assert result.card.data["months"] == [
        {"period": "2026-06", "total": 100_000},
        {"period": "2026-07", "total": 120_000},
    ]
    assert result.card.data["average_total"] == 110_000
    # 평균을 "합계" 칸에 넣지 않는다 — 화면이 total을 합계로 읽는다.
    assert result.card.data["total"] is None


async def test_get_fees_multi_month_refuses_average_when_a_month_is_missing(
    settings: AiCoreSettings,
) -> None:
    """요청한 달이 하나라도 비면 평균을 내지 않고, 뭐가 없는지 카드에 밝힌다."""
    handler = _multi_fee_handler({"2026-07": 120_000})  # 6월 데이터 없음
    result = await _multi_fee_result(settings, handler, "2026-06,2026-07")
    assert result.card is not None
    assert "평균 총액" not in result.card.quote
    assert "2026-06 관리비 내역이 없어 평균을 내지 않았습니다" in result.card.quote
    assert result.card.data is not None
    assert result.card.data["average_total"] is None
    assert result.card.data["missing_periods"] == ["2026-06"]


async def test_get_fees_multi_month_excludes_pre_approval_month_and_says_so(
    settings: AiCoreSettings,
) -> None:
    """승인 이전 달은 빼되(FR-FEE-03) 조용히 빼지 않는다 — 뺀 사실이 카드에 남는다."""
    handler = _multi_fee_handler(
        {"2026-06": 100_000, "2026-07": 120_000},
        approved=datetime(2026, 7, 1, tzinfo=UTC),
    )
    result = await _multi_fee_result(settings, handler, "2026-06,2026-07")
    assert result.card is not None
    assert "2026-06는 입주 승인 이전이라 제외했습니다" in result.card.quote
    assert "평균 총액" not in result.card.quote  # 한 달만 남으면 평균이 아니다
    assert result.card.data is not None
    assert result.card.data["excluded_periods"] == ["2026-06"]
    assert result.card.data["months"] == [{"period": "2026-07", "total": 120_000}]


async def test_get_fees_multi_month_all_before_approval_returns_note(
    settings: AiCoreSettings,
) -> None:
    handler = _multi_fee_handler({"2026-06": 100_000}, approved=datetime(2026, 12, 1, tzinfo=UTC))
    result = await _multi_fee_result(settings, handler, "2026-06,2026-07")
    assert result.card is None
    assert "입주 승인 이전" in result.note


async def test_get_fees_multi_month_no_data_returns_note(settings: AiCoreSettings) -> None:
    result = await _multi_fee_result(settings, _multi_fee_handler({}), "2026-06,2026-07")
    assert result.card is None
    assert "관리비 내역이 없습니다" in result.note


# ── get_fees 같은 평형 평균 비교 (ADR-0026 결정 3) ──────────────────────


def _peer_handler(avg_total: object, sample_size: int) -> Any:
    """_fee_handler + 같은 평형 평균 집계 응답. sample_size로 표본 하한 분기를 만든다."""

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        if "household_geometries" in sql.lower():
            return [row(unit_type="84M", avg_total=avg_total, sample_size=sample_size)]
        return _fee_handler(sql, params)

    return handler


async def _fee_card(settings: AiCoreSettings, handler: Any) -> Any:
    result = (
        await execute_tool(
            _call("get_fees", {"period": "2026-06"}),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    return result.card


async def test_get_fees_adds_peer_average_when_sample_is_enough(
    settings: AiCoreSettings,
) -> None:
    card = await _fee_card(settings, _peer_handler(avg_total=95000, sample_size=MIN_PEER_SAMPLE))
    # 평균·표본수는 SQL 집계값 그대로, 차액만 확정값끼리의 뺄셈(규칙 5).
    assert "같은 평형(84M) 10세대 평균 95,000원 대비 +5,000원" in card.quote
    assert card.data is not None
    assert card.data["peer"] == {
        "unit_type": "84M",
        "avg_total": 95000,
        "sample_size": 10,
        "diff": 5000,
    }


async def test_get_fees_omits_peer_average_below_min_sample(settings: AiCoreSettings) -> None:
    """표본 하한 미달 = 비교 거부(소표본 역산 방지) — 본인 값은 정상 반환한다."""
    card = await _fee_card(
        settings, _peer_handler(avg_total=95000, sample_size=MIN_PEER_SAMPLE - 1)
    )
    assert "평형" not in card.quote
    assert "100,000원" in card.quote  # 본인 세대 값은 그대로
    assert card.data is not None and "peer" not in card.data


async def test_get_fees_omits_peer_average_without_geometry(settings: AiCoreSettings) -> None:
    """평형 미상(household_geometries 없음)이면 집계가 0행 — 비교만 생략, 폴백 아님."""
    card = await _fee_card(settings, _fee_handler)  # geometry 쿼리는 빈 결과
    assert "평형" not in card.quote
    assert "100,000원" in card.quote
    assert card.data is not None and "peer" not in card.data


async def test_get_fees_omits_peer_average_when_avg_is_null(settings: AiCoreSettings) -> None:
    card = await _fee_card(settings, _peer_handler(avg_total=None, sample_size=50))
    assert card.data is not None and "peer" not in card.data


async def test_peer_average_sql_is_tenant_scoped_and_aggregate_only(
    settings: AiCoreSettings,
) -> None:
    """격리(규칙 3)와 미노출(ADR-0026)을 SQL 문자열로 못박는다 — 개별 세대 금액 SELECT 금지."""
    deps = _deps(settings, handler=_peer_handler(avg_total=95000, sample_size=30))
    await execute_tool(
        _call("get_fees", {"period": "2026-06"}),
        ctx=CTX_RESIDENT,
        deps=deps,
        registry=default_registry(),
    )
    session = cast(FakeSession, deps.session)
    peer_sql, peer_params = next(
        (sql, params) for sql, params in session.executed if "household_geometries" in sql
    )
    assert peer_params["tid"] == TENANT
    assert peer_sql.count("tenant_id = :tid") == 3  # me·geometry·fees 전부 같은 단지로 제한
    select_clause = peer_sql.split("SELECT me.unit_type")[1].split("FROM me")[0]
    assert "household_id" not in select_clause  # 세대 식별자 미노출
    assert "f.total_amount" not in select_clause.replace("avg(f.total_amount)", "")


# ── get_fees 동·단지 평균 (H20-1) ───────────────────────────────────────

SCOPE_ITEMS = (("공용관리비", 81_468), ("전기료", 42_000))


def _scope_handler(
    *,
    avg_total: object = 141_034,
    sample_size: int = 62,
    items: Sequence[tuple[str, int]] = SCOPE_ITEMS,
) -> Any:
    """동·단지 평균 집계 응답. 평균·표본수는 SQL이 낸 값 자리를 가짜 세션이 대신 채운다."""

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        if "max(period)" in s:
            return [row(period="2026-07")]
        if "jsonb_array_elements" in s:
            return [row(name=name, avg_amount=amount) for name, amount in items]
        if "count(*) as sample_size" in s:
            return [row(avg_total=avg_total, sample_size=sample_size)]
        return []

    return handler


async def _scope_result(settings: AiCoreSettings, handler: Any, args: dict[str, Any]) -> Any:
    return (
        await execute_tool(
            _call("get_fees", args),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result


async def test_get_fees_scope_dong_returns_average_of_that_building(
    settings: AiCoreSettings,
) -> None:
    """ "402동 관리비는?" — 그 동의 평균 총액·항목 평균. 본인 세대 조회는 아예 없다."""
    result = await _scope_result(
        settings, _scope_handler(), {"scope": "402동", "period": "2026-07"}
    )
    assert result.card is not None
    assert result.card.source_kind == "tool:get_fees"
    assert "402동 2026-07 관리비 평균 총액 141,034원" in result.card.quote
    assert "표본 62세대" in result.card.quote
    assert "공용관리비 81,468원" in result.card.quote
    assert result.card.data is not None
    assert result.card.data["scope"] == {"kind": "dong", "label": "402동", "sample_size": 62}
    assert result.card.data["total"] == 141_034
    assert result.card.data["rows"] == [
        {"name": "공용관리비", "amount": 81_468},
        {"name": "전기료", "amount": 42_000},
    ]
    # 본인 세대 전용 키는 넣지 않는다 — 집계에는 전월 대비·같은 평형 비교가 없다.
    assert "prev_total" not in result.card.data and "peer" not in result.card.data


async def test_get_fees_scope_complex_returns_tenant_wide_average(
    settings: AiCoreSettings,
) -> None:
    result = await _scope_result(settings, _scope_handler(), {"scope": "전체"})
    assert result.card is not None
    assert "단지 전체 2026-07 관리비 평균 총액 141,034원" in result.card.quote  # 기간 미지정=최신
    assert result.card.data is not None
    assert result.card.data["scope"] == {
        "kind": "complex",
        "label": "단지 전체",
        "sample_size": 62,
    }


async def test_get_fees_scope_below_min_sample_refuses_average(settings: AiCoreSettings) -> None:
    """표본 하한 미달 = 평균 거부(소표본 역산 방지). 숫자는 어디에도 안 나간다."""
    result = await _scope_result(
        settings,
        _scope_handler(sample_size=MIN_PEER_SAMPLE - 1),
        {"scope": "402동", "period": "2026-07"},
    )
    assert result.card is not None
    assert "표본이 적어" in result.card.quote
    assert "141,034" not in result.card.quote
    assert result.card.data is None


async def test_get_fees_scope_unknown_dong_says_no_data(settings: AiCoreSettings) -> None:
    """없는 동은 추측하지 않는다(규칙 1) — 집계 0행이면 "데이터가 없다"가 근거다."""
    result = await _scope_result(
        settings,
        _scope_handler(avg_total=None, sample_size=0),
        {"scope": "999동", "period": "2026-07"},
    )
    assert result.card is not None
    assert "999동" in result.card.quote and "데이터가 없" in result.card.quote
    assert "141,034" not in result.card.quote
    assert result.card.data is None


async def test_scope_average_sql_is_tenant_scoped_and_aggregate_only(
    settings: AiCoreSettings,
) -> None:
    """격리(규칙 3)·미노출(CRITICAL)을 SQL 문자열로 못박는다 — 개별 세대 값 SELECT 금지."""
    deps = _deps(settings, handler=_scope_handler())
    await execute_tool(
        _call("get_fees", {"scope": "402동", "period": "2026-07"}),
        ctx=CTX_RESIDENT,
        deps=deps,
        registry=default_registry(),
    )
    session = cast(FakeSession, deps.session)
    assert not any("from users" in sql.lower() for sql, _ in session.executed)  # 소유권 조회 없음
    for sql, params in session.executed:
        assert params["tid"] == TENANT
        assert "f.tenant_id = :tid" in sql
        select_clause = sql.split("SELECT")[1].split("FROM")[0]
        assert "household_id" not in select_clause  # 세대 식별자 미노출
        assert "f.total_amount" not in select_clause.replace("avg(f.total_amount)", "")


async def test_get_fees_scope_complex_sql_has_no_building_filter(
    settings: AiCoreSettings,
) -> None:
    deps = _deps(settings, handler=_scope_handler())
    await execute_tool(
        _call("get_fees", {"scope": "단지"}),
        ctx=CTX_RESIDENT,
        deps=deps,
        registry=default_registry(),
    )
    session = cast(FakeSession, deps.session)
    aggregates = [sql for sql, _ in session.executed if "avg(" in sql]
    assert aggregates and all("buildings" not in sql for sql in aggregates)


def test_get_fees_args_normalize_scope() -> None:
    """8B 표기 흔들림 흡수 — 숫자만·전체 동의어·null 리터럴."""
    assert GetFeesArgs(scope="402").scope == "402동"
    # dev 실측: 단독 "아파트"도 전체 평균 의도다.
    from ai_core.tools.fees_common import COMPLEX_SCOPE

    assert GetFeesArgs(scope="아파트").scope == COMPLEX_SCOPE
    assert GetFeesArgs(scope="아파트 평균").scope == COMPLEX_SCOPE
    assert GetFeesArgs(scope=" 402동 ").scope == "402동"
    for whole in ("전체", "단지", "단지 전체", "모든 동", "아파트 전체"):
        assert GetFeesArgs(scope=whole).scope == COMPLEX_SCOPE
    for literal in ("null", "None", "", "  "):
        assert GetFeesArgs.model_validate({"scope": literal}).scope is None
    assert GetFeesArgs.model_validate({}).scope is None


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
    assert result.card is not None and "상태=fault" in result.card.quote
    assert captured["params"]["status"] == "fault"
    assert "status = :status" in captured["sql"]


async def test_get_facilities_quote_includes_counts(settings: AiCoreSettings) -> None:
    # "승강기 몇 대" 류 대수 질문의 정답 근거 — 총수·코드 종류별 수를 집계해 인용한다.
    # LIMIT 잘림(구현 전 MAX_TOOL_ROWS=20 < 설비 37건)이면 대수가 틀린다(케이스셋 v2 §6-⓪).
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        return [
            row(name="승강기1", status="normal", code="EL-101-01", kind_label="승강기"),
            row(name="승강기2", status="normal", code="EL-102-01", kind_label="승강기"),
            row(name="CCTV1", status="normal", code="CM-401-01", kind_label="커뮤니티"),
            # 라벨·코드가 없는 행도 집계에서 빠지지 않는다(LEFT JOIN 미스·백필 전 행).
            row(name="무코드설비", status="normal", code=None, kind_label=None),
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
    # 계통은 한글명(codes FACILITY_SYSTEM) + 약어 — 약어만 주면 답변이 "EL: 12개"가 된다.
    assert "승강기(EL) 2개" in result.card.quote
    assert "커뮤니티(CM) 1개" in result.card.quote
    assert "기타 1개" in result.card.quote
    assert "normal 4개" in result.card.quote  # 상태별 집계도 근거에 들어간다


async def test_get_facilities_quote_has_no_name_list(settings: AiCoreSettings) -> None:
    """근거는 집계만 — 설비명 나열 금지(H20-16).

    이름을 20개 실었더니 8B가 목록을 되풀이하는 답변을 냈다(2026-08-03 dev 실측).
    화면 카드(data.items)에는 그대로 남는다 — 프롬프트에 안 실릴 뿐이다.
    """

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
    assert "설비0" not in result.card.quote and "설비1" not in result.card.quote
    assert result.card.data is not None and len(result.card.data["items"]) == 20


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
        return [row(name="소방펌프", next_check_at=due)] if "<= :threshold" in sql else []

    result = (
        await execute_tool(
            _call("get_overdue_checks", {}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None and "소방펌프" in result.card.quote


async def test_get_overdue_checks_lists_next_scheduled_check(settings: AiCoreSettings) -> None:
    """ADM-3 — 임박 창 밖의 다음 점검 예정일도 근거로 낸다(H19-4 ②)."""
    later = datetime.now(UTC) + timedelta(days=60)

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        if "next_check_at > :threshold" in sql:
            return [row(name="승강기1", next_check_at=later)]
        return []

    result = (
        await execute_tool(
            _call("get_overdue_checks", {}),
            ctx=CTX_MANAGER,
            deps=_deps(settings, handler=handler),
            registry=default_registry(),
        )
    ).result
    assert result.card is not None
    assert f"다음 점검 예정: 승강기1: {later:%Y-%m-%d}" in result.card.quote
    assert "없습니다" in result.card.quote  # 임박·초과는 없음(확정 조회)


async def test_get_overdue_checks_empty_returns_card(settings: AiCoreSettings) -> None:
    # R22 실측: 빈 결과가 note만 반환 → 인용 근거 없음 → 폴백. "DB가 확인한 없음"은
    # 절대 규칙 1의 확정 도구 결과이므로 카드로 승격한다(케이스셋 v2 §6-⓪, codex HIGH).
    # 첫마을 시드는 next_check_at이 전부 NULL이라 임박·예정 둘 다 비는데, 이때 "점검
    # 없음"이 아니라 **예정일 미등록**이라고 말해야 한다(규칙 1 — 없는 일정 지어내기 금지).
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
    assert "예정일 미등록" in result.card.quote
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


def test_tool_descriptions_exclude_leaking_categories() -> None:
    """실측에서 샌 질문 범주를 설명에 배제로 못박는다(H17-1·R31 관례, 표적은 R36 잔여 실패).

    - get_facilities: 사양·설계 수치(0048 "수전용량") — SELECT에 없는 값이다.
    - get_recent_notices: 특정 주제의 일정(0332 "이번 달 실내소독") — 목록 도구가 아니다.
    - trace_home_device_issue: 신고·접수형(IQ-03·IQ-06·GR-0027) — 유사 민원 쪽이다.
    """
    registry = default_registry()
    facility_specs = {
        s["function"]["name"]: s["function"]["description"]
        for s in registry.specs_for(("MANAGER",), graph_available=True)
    }
    resident_specs = {
        s["function"]["name"]: s["function"]["description"]
        for s in registry.specs_for(("RESIDENT",), graph_available=True)
    }
    assert "수전용량" in facility_specs["get_facilities"]
    assert "일정" in resident_specs["get_recent_notices"]
    assert "신고" in resident_specs["trace_home_device_issue"]
    # 배제는 대안 경로를 함께 줘야 재라우팅된다 — 도구명이 아니라 자연어로(R22 관례).
    for name, specs in (
        ("get_facilities", facility_specs),
        ("get_recent_notices", resident_specs),
    ):
        assert "문서 검색" in specs[name]
        assert "search_documents" not in specs[name]


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
    assert GetFeesArgs.model_validate({}).requested_periods() == []
    assert GetFeesArgs(period="2026-06").requested_periods() == ["2026-06"]


def test_get_fees_args_null_literal_means_omitted() -> None:
    """8B가 "생략"을 문자열 "null"로 넘긴다(2026-08-01 로컬 실측 — 패턴 검증 실패로
    카드 0 → no_evidence 폴백). 리터럴 null/none/빈 문자열은 미지정으로 접는다."""
    for literal in ("null", "None", "NULL", "", "  "):
        assert GetFeesArgs.model_validate({"period": literal}).period is None


def test_get_fees_args_accept_comma_separated_months() -> None:
    """여러 달은 쉼표로 — 중복은 합치고 오름차순으로 정규화한다(공백 허용)."""
    assert GetFeesArgs(period="2026-07, 2026-06").requested_periods() == ["2026-06", "2026-07"]
    assert GetFeesArgs(period="2026-06,2026-06").requested_periods() == ["2026-06"]
    for bad in ("2026/06", "2026-06;2026-07", "6월"):
        try:
            GetFeesArgs(period=bad)
        except ValidationError:
            continue
        raise AssertionError(f"형식 검증이 통과하면 안 됨: {bad}")


def test_fee_quote_includes_detail_items_for_item_questions() -> None:
    """세부 항목(전기료 등)이 quote에 실려야 항목 질의가 근거를 갖는다(사용자 요구 3).

    화면 표는 level 0 그대로이므로 detail은 quote 전용이다.
    """
    from ai_core.tools.fees_common import fee_detail_items as _fee_detail_items
    from ai_core.tools.library import _fee_quote

    raw = [
        {"name": "공용관리비", "level": 0, "amount": 91362},
        {"name": "일반관리비", "level": 1, "amount": 47281},
        {"name": "공과금중 전기료", "level": 2, "amount": 12345},
        {"name": "급여", "level": 3, "amount": 30559},  # level 3 제외
        {"name": "상여금", "level": 2, "amount": 0},  # 0원 제외
        {"name": "합계", "level": 0, "amount": 176601},
    ]
    detail = _fee_detail_items(raw)
    assert ("공과금중 전기료", 12345) in detail
    assert all(name not in ("급여", "상여금", "합계") for name, _ in detail)

    quote = _fee_quote("2026-07", [("공용관리비", 91362)], 176601, None, None, detail=detail)
    assert "공과금중 전기료 12,345원" in quote
    # detail 없으면 기존 문구 그대로(회귀 없음).
    assert "세부 항목" not in _fee_quote("2026-07", [("공용관리비", 91362)], 176601, None, None)


def test_get_fees_scope_folds_self_synonyms_to_none() -> None:
    """모델이 본인 질문에 scope='본인 세대'를 채우는 dev 실측 — 본인 동의어는 미지정.

    1인칭 대명사까지 넓힌 건 "나의 관리비는?"이 scope="나"(동 이름 취급)로 샌 실측 때문.
    """
    for word in (
        "본인 세대",
        "본인",
        "우리 집",
        "세대",
        "나",
        "나의",
        "나의 집",
        "저",
        "저희",
        "우리",
        "내",
    ):
        assert GetFeesArgs(scope=word).scope is None, word
    # 동·전체 정규화는 불변.
    assert GetFeesArgs(scope="402").scope == "402동"
