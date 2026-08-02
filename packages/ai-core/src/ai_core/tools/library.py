"""도구 구현 15종 (docs/01 §5.2, ADR-0007) — 전부 읽기 전용. 평면도 도구는 floor_plan.py.

SQL 도구는 retrieval.py와 동일하게 raw `text()` SELECT를 주입 세션으로 실행한다
(ai-core는 liviq_db ORM에 의존하지 않는다 — 계약은 컬럼명뿐). RLS가 1차 방어,
쿼리의 tenant_id·소유권 조건이 2차 방어(이중 방어, 규칙 3·4).

tenant_id·user_id는 항상 `ToolContext`에서 오며 LLM 인자로 받지 않는다.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple, cast

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

from ai_core.graph import IncidentContext, IncidentHit
from ai_core.llm.client import LlmError
from ai_core.tools.clarify import ask_clarification_tool
from ai_core.tools.floor_plan import find_in_floor_plan_tool
from ai_core.tools.inquiries import search_similar_inquiries_tool, summarize_inquiries_tool
from ai_core.tools.notices import get_recent_notices_tool
from ai_core.tools.parking import find_my_vehicle_tool, find_nearest_available_parking_tool
from ai_core.tools.registry import (
    Tool,
    ToolCard,
    ToolContext,
    ToolDeps,
    ToolRegistry,
    ToolResult,
)
from ai_core.tools.trace_home_device import trace_home_device_issue_tool

# docs/08 도구 결과 상한 — 목록형 도구 결과 행 수 제한(토큰=비용).
MAX_TOOL_ROWS = 20
GRAPH_SEARCH_K = 5
# 점검 임박 판정 창(일).
OVERDUE_WINDOW_DAYS = 7

# 다음 정기점검 예정일(ADM-3) — 임박 창 밖의 향후 점검을 가까운 순으로 몇 건 덧붙인다.
UPCOMING_CHECK_ROWS = 5
# 같은 평형 평균 비교의 표본 하한(ADR-0026 결정 3). 미달이면 비교를 생략한다 — 소표본
# 평균은 본인 값과 함께 특정 세대 금액을 역산시킨다(n=2면 상대 세대 금액이 그대로 나온다).
# 첫마을 4단지는 322세대이고 소수 평형(59C)도 수십 세대라, 10이면 역산은 불가능하면서
# 비교는 거의 항상 성립한다.
MIN_PEER_SAMPLE = 10

FACILITY_ROLES = frozenset({"FACILITY", "MANAGER"})
# 조회할 월 — 한 달(2026-06) 또는 쉼표로 나열한 여러 달(2026-06,2026-07).
# 배열 인자가 아니라 쉼표 문자열인 이유: 8B는 배열 인자 생성에 약하고, 인자 개수가 늘수록
# 라우팅이 함께 무너진다(R22 계열 — LongtermParkingArgs와 같은 판단). 필드 이름을 그대로
# 두면 기존 단일 월 호출·골든셋도 한 글자도 안 바뀐다.
_PERIOD_PATTERN = r"^\d{4}-\d{2}(\s*,\s*\d{4}-\d{2})*$"
# 평균은 2개월 이상일 때만 의미가 있다(1개월 평균 = 그 달 합계).
MIN_AVERAGE_MONTHS = 2

# 집계 범위(H20-1) — "전체"·"단지" 같은 사용자 어휘를 접어 넣는 내부 표기(동 이름과 절대
# 겹치지 않는 값). scope가 이 값이면 동 조인 없이 단지 전체를 집계한다.
COMPLEX_SCOPE = "__complex__"
_COMPLEX_SCOPE_WORDS = frozenset(
    {"전체", "단지", "단지전체", "전체단지", "전체동", "모든동", "아파트전체", "우리단지", "전세대"}
)

# 장기주차 기준 시간(H19-3) — 기본 하루, 상한 7일. 상한이 없으면 모델이 큰 값을 넣어
# 사실상 필터가 사라진다(경계 검증은 Pydantic이 담당, 규칙: 경계 입력 검증).
LONGTERM_PARKING_DEFAULT_HOURS = 24
LONGTERM_PARKING_MIN_HOURS = 1
LONGTERM_PARKING_MAX_HOURS = 168


# ── 인자 모델 ────────────────────────────────────────────────────────────────


class QueryArgs(BaseModel):
    query: str = Field(..., min_length=1, description="검색할 자연어 질의")


class GetFeesArgs(BaseModel):
    period: str | None = Field(
        default=None,
        pattern=_PERIOD_PATTERN,
        description=(
            "조회할 월(YYYY-MM). 여러 달을 물으면 쉼표로 전부 나열한다"
            "(예: 2026-06,2026-07) — 평균·합계는 이 도구가 계산해 돌려준다. "
            "생략 시 최근 확정 월"
        ),
    )
    scope: str | None = Field(
        default=None,
        description=(
            "평균을 낼 범위. 특정 동이면 동 이름(예: 402동), 단지 전체면 '전체'. "
            "생략하면 본인 세대 관리비"
        ),
    )

    @field_validator("period", mode="before")
    @classmethod
    def _fold_null_literal(cls, value: object) -> object:
        # 8B가 "생략"을 문자열 "null"로 넘긴다(2026-08-01 실측: {"period":"null"} →
        # 패턴 검증 실패 → 카드 0 → no_evidence 폴백). 리터럴 null/none/빈 값은 미지정으로.
        if isinstance(value, str) and value.strip().lower() in ("", "null", "none"):
            return None
        return value

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value: object) -> object:
        """표기 흔들림을 세 갈래로 접는다 — 미지정 · 단지 전체 · "<동>동"."""
        if not isinstance(value, str):
            return value
        raw = value.strip()
        if raw.lower() in ("", "null", "none"):
            return None
        if raw.replace(" ", "") in _COMPLEX_SCOPE_WORDS:
            return COMPLEX_SCOPE
        return f"{raw}동" if raw.isdigit() else raw

    def requested_periods(self) -> list[str]:
        """요청 월 목록(중복 제거·오름차순). 빈 목록 = 미지정(최근 확정 월)."""
        if not self.period:
            return []
        return sorted({p.strip() for p in self.period.split(",")})


class GetFacilitiesArgs(BaseModel):
    status: str | None = Field(None, description="상태 필터(normal|check|fault|risk). 생략 시 전체")


class LongtermParkingArgs(BaseModel):
    # 인자는 이것 하나뿐 — 8B는 인자가 늘수록 라우팅·인자 생성이 함께 무너진다
    # (R22 계열, tools/notices.py와 같은 판단). 동·차종 필터는 요청이 관측되면 그때(YAGNI).
    hours: int = Field(
        LONGTERM_PARKING_DEFAULT_HOURS,
        ge=LONGTERM_PARKING_MIN_HOURS,
        le=LONGTERM_PARKING_MAX_HOURS,
        description="기준 경과 시간(시간). 하루 이상이면 24, 사흘 이상이면 72. 생략 시 24",
    )


class NoArgs(BaseModel):
    pass


# ── 문서 검색 ────────────────────────────────────────────────────────────────


async def _search_documents(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(QueryArgs, args)
    try:
        query_vec = (await deps.llm.embed([a.query]))[0]
    except LlmError:
        return ToolResult(note="문서 검색을 일시적으로 사용할 수 없습니다.")
    chunks = await deps.retriever.search(
        query_vec,
        tenant_id=ctx.tenant_id,
        visibilities=ctx.visibilities,
        # 동별로 쪼개진 공지는 로그인 세대의 동만 근거로 삼는다(H19-1) — None이면 전 동 검색.
        building_id=ctx.building_id,
    )
    if not chunks:
        return ToolResult(note="관련 문서를 찾지 못했습니다.")
    return ToolResult(doc_chunks=tuple(chunks))


# ── 시설 그래프 ──────────────────────────────────────────────────────────────


async def _search_facility_graph(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(QueryArgs, args)
    if deps.graph is None:
        return ToolResult(note="시설 그래프를 사용할 수 없습니다.")
    try:
        query_vec = (await deps.llm.embed([a.query]))[0]
    except LlmError:
        return ToolResult(note="시설 그래프 검색을 일시적으로 사용할 수 없습니다.")
    tenant = str(ctx.tenant_id)
    hits = await deps.graph.search_incidents(
        tenant_id=tenant, query_vector=query_vec, k=GRAPH_SEARCH_K
    )
    if not hits:
        return ToolResult(note="유사 장애 이력을 찾지 못했습니다.")
    contexts = await deps.graph.expand_incidents(tenant_id=tenant, pg_ids=[h.pg_id for h in hits])
    return ToolResult(
        card=ToolCard(
            title="유사 장애·정비 이력",
            quote=_graph_quote(hits, contexts),
            source_kind="tool:search_facility_graph",
        )
    )


def _graph_quote(hits: list[IncidentHit], contexts: list[IncidentContext]) -> str:
    ctx_by_id = {c.incident_id: c for c in contexts}
    lines: list[str] = []
    for hit in hits:
        c = ctx_by_id.get(hit.pg_id)
        facility = (
            f"{c.facility_name}({c.facility_status})" if c and c.facility_name else "시설미상"
        )
        # 다단계 인과(G1a) — expand가 causal_chain을 채우면 카드에 노출한다(trace_quote 표기 일관).
        # 없으면 생략(하위호환).
        chain = f" · 선행원인: {' ← '.join(c.causal_chain)}" if c and c.causal_chain else ""
        work = f" · 최근정비: {', '.join(c.recent_work)}" if c and c.recent_work else ""
        lines.append(f"{facility} 증상: {hit.symptom}{chain}{work}")
    return " / ".join(lines)


# ── 관리비(본인 세대·승인 후 월만, 규칙 5) ───────────────────────────────────

# ponytail: _prev_period는 apps/api fees 라우터에도 있다 — 5줄 헬퍼라 패키지 경계
# 넘어 import하지 않고 재정의(ai-core는 apps.api에 의존 불가). 계약 변경 시 양쪽 수정.
_USER_SQL = text("SELECT household_id, approved_at FROM users WHERE id = :uid AND tenant_id = :tid")
_LATEST_FEE_SQL = text(
    "SELECT period FROM fees "
    "WHERE tenant_id = :tid AND household_id = :hid AND period >= :approved "
    "ORDER BY period DESC LIMIT 1"
)
_FEE_SQL = text(
    "SELECT breakdown, total_amount FROM fees "
    "WHERE tenant_id = :tid AND household_id = :hid AND period = :period"
)
# 여러 달 조회(2026-08-01 사고 대응) — 월별 확정값과 **평균을 한 번에 SQL이 낸다**.
# 파이썬도 LLM도 나눗셈을 하지 않는다(규칙 5): 인자가 단일 월뿐이던 시절 "6,7월 평균"에
# 모델이 7월 값 하나를 받아 2로 나눠 답했다(공용관리비 81,468 → 40,734). 평균을 도구가
# 확정해 카드에 실으면 모델이 계산할 여지 자체가 없다.
_FEES_MULTI_SQL = text(
    "SELECT period, total_amount, round(avg(total_amount) OVER ()) AS avg_total "
    "FROM fees "
    "WHERE tenant_id = :tid AND household_id = :hid AND period = ANY(:periods) "
    "ORDER BY period"
)
# 같은 단지·같은 평형의 같은 월 평균(ADR-0026 결정 3) — **집계값만** SELECT한다. 개별 세대
# 금액은 어떤 경로로도 나가지 않는다. 평형 키는 unit_type_label "84M(공공임대)" → "84M"
# (seed_fees_demo._unit_type_of와 같은 규칙). 본인 세대 geometry가 없거나 라벨이 비면
# me.unit_type이 NULL이라 조인이 성립하지 않고 → 결과 0행 = 비교 생략.
_PEER_AVG_SQL = text(
    "WITH me AS ("
    "  SELECT nullif(btrim(split_part(unit_type_label, '(', 1)), '') AS unit_type"
    "  FROM household_geometries WHERE tenant_id = :tid AND household_id = :hid"
    ") "
    "SELECT me.unit_type AS unit_type, round(avg(f.total_amount)) AS avg_total, "
    "       count(*) AS sample_size "
    "FROM me "
    "JOIN household_geometries g ON g.tenant_id = :tid "
    "  AND nullif(btrim(split_part(g.unit_type_label, '(', 1)), '') = me.unit_type "
    "JOIN fees f ON f.tenant_id = :tid AND f.household_id = g.household_id "
    "  AND f.period = :period "
    "GROUP BY me.unit_type"
)


# 동·단지 평균(H20-1) — 본인 세대와 무관한 **집계 전용** 쿼리다. SELECT에 세대 식별자도
# 개별 금액도 없고, 표본수가 함께 나와 소표본이면 호출부가 평균을 거부한다.
# buildings.name은 접미사 없는 "402"(seed_households_xlsx 규칙)라 "402동" 표기도 함께 받는다.
_SCOPE_DONG_JOIN = (
    " JOIN households h ON h.tenant_id = :tid AND h.id = f.household_id"
    " JOIN buildings b ON b.tenant_id = :tid AND b.id = h.building_id"
    " AND b.name = ANY(:dong)"
)
_SCOPE_WHERE = " WHERE f.tenant_id = :tid AND f.period = :period"


def _scope_sql(join: str) -> tuple[TextClause, TextClause]:
    """(총액 평균, 항목별 평균) 한 쌍 — 동 조인 유무만 다르다.

    항목 평균은 breakdown(JSONB 배열)을 SQL이 직접 펼쳐 avg를 낸다(H19-4와 같은 계열):
    파이썬도 LLM도 더하거나 나누지 않는다(규칙 5). 구 dict 포맷 행은 unnest가 깨지므로
    `jsonb_typeof = 'array'`로 걸러내고, '합계'는 총액과 중복이라 뺀다(_breakdown_items 규칙).
    """
    total = text(
        "SELECT round(avg(f.total_amount))::bigint AS avg_total, count(*) AS sample_size"
        " FROM fees f" + join + _SCOPE_WHERE
    )
    items = text(
        "SELECT elem->>'name' AS name,"
        " round(avg((elem->>'amount')::numeric))::bigint AS avg_amount"
        " FROM fees f"
        + join
        + " CROSS JOIN LATERAL jsonb_array_elements(f.breakdown) AS elem"
        + _SCOPE_WHERE
        + " AND jsonb_typeof(f.breakdown) = 'array'"
        " AND (elem->>'level')::int = 0 AND elem->>'name' <> '합계'"
        " GROUP BY 1 ORDER BY 1"
    )
    return total, items


_SCOPE_DONG_TOTAL_SQL, _SCOPE_DONG_ITEMS_SQL = _scope_sql(_SCOPE_DONG_JOIN)
_SCOPE_COMPLEX_TOTAL_SQL, _SCOPE_COMPLEX_ITEMS_SQL = _scope_sql("")
# 범위 평균의 "최근 확정 월" — 본인 세대가 아니라 단지 전체의 최신 월이다.
_LATEST_SCOPE_PERIOD_SQL = text("SELECT max(period) AS period FROM fees WHERE tenant_id = :tid")


class PeerAverage(NamedTuple):
    """같은 평형 평균 비교 결과 — 전부 집계값(세대 식별 정보 없음)."""

    unit_type: str
    avg_total: int
    sample_size: int
    diff: int


async def _get_fees(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(GetFeesArgs, args)
    if a.scope:
        # 범위 평균은 본인 세대와 무관한 집계 — 소유권·승인월 조회 자체가 없다(H20-1).
        return await _fees_scope_average(deps, ctx, a)
    urow = (
        await deps.session.execute(_USER_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})
    ).first()
    if urow is None or urow.household_id is None:
        return ToolResult(note="세대가 배정되지 않아 관리비를 조회할 수 없습니다.")
    approved = urow.approved_at.strftime("%Y-%m") if urow.approved_at else "9999-12"

    requested = a.requested_periods()
    if len(requested) > 1:
        return await _fees_multi_month(deps, ctx, urow.household_id, requested, approved)
    return await _fees_single_month(
        deps, ctx, urow.household_id, requested[0] if requested else None, approved
    )


async def _fees_single_month(
    deps: ToolDeps,
    ctx: ToolContext,
    household_id: Any,
    period: str | None,
    approved: str,
) -> ToolResult:
    """한 달 조회(기존 계약 그대로) — 항목·합계·전월 대비·같은 평형 평균."""
    if period is None:
        latest = (
            await deps.session.execute(
                _LATEST_FEE_SQL,
                {"tid": ctx.tenant_id, "hid": household_id, "approved": approved},
            )
        ).first()
        if latest is None:
            return ToolResult(note="조회 가능한 관리비 내역이 없습니다.")
        period = latest.period
    elif period < approved:
        return ToolResult(note=f"{period} 관리비는 조회할 수 없습니다(입주 승인 이전).")

    fee = (
        await deps.session.execute(
            _FEE_SQL, {"tid": ctx.tenant_id, "hid": household_id, "period": period}
        )
    ).first()
    if fee is None or fee.total_amount is None:
        return ToolResult(note=f"{period} 관리비 내역이 없습니다.")
    breakdown = _breakdown_items(fee.breakdown)
    total = int(fee.total_amount)

    prev_period = _prev_period(period)
    prev_total: int | None = None
    if prev_period >= approved:
        prev = (
            await deps.session.execute(
                _FEE_SQL, {"tid": ctx.tenant_id, "hid": household_id, "period": prev_period}
            )
        ).first()
        prev_total = int(prev.total_amount) if prev and prev.total_amount is not None else None

    peer = await _peer_average(deps, ctx, household_id, period, total)

    return ToolResult(
        card=ToolCard(
            title=f"관리비 {period} 확정 데이터",
            quote=_fee_quote(period, breakdown, total, prev_total, peer),
            source_kind="tool:get_fees",
            data=_fee_data(period, breakdown, total, prev_total, peer),
        )
    )


async def _fees_multi_month(
    deps: ToolDeps,
    ctx: ToolContext,
    household_id: Any,
    requested: list[str],
    approved: str,
) -> ToolResult:
    """여러 달 조회 — 월별 확정값 + **SQL이 낸 평균**만 낸다(규칙 5).

    빠진 달을 조용히 넘기지 않는다. 승인 이전이라 뺀 달·데이터가 없는 달은 카드에 적고,
    요청한 달이 하나라도 비면 **평균 자체를 내지 않는다** — 있는 달로만 낸 평균은
    "6,7월 평균"을 물은 사용자에게 거짓말이다(이번 사고의 본질).
    """
    excluded = [p for p in requested if p < approved]
    eligible = [p for p in requested if p >= approved]
    if not eligible:
        return ToolResult(
            note=f"{', '.join(requested)} 관리비는 조회할 수 없습니다(입주 승인 이전)."
        )
    rows = (
        await deps.session.execute(
            _FEES_MULTI_SQL, {"tid": ctx.tenant_id, "hid": household_id, "periods": eligible}
        )
    ).all()
    months = [(str(r.period), int(r.total_amount)) for r in rows if r.total_amount is not None]
    if not months:
        return ToolResult(note=f"{', '.join(eligible)} 관리비 내역이 없습니다.")
    found = {p for p, _ in months}
    missing = [p for p in eligible if p not in found]
    # 평균은 요청한 달이 전부 있을 때만. avg_total은 SQL 윈도우 집계값 그대로다.
    avg_total = (
        int(rows[0].avg_total)
        if not missing and len(months) >= MIN_AVERAGE_MONTHS and rows[0].avg_total is not None
        else None
    )
    return ToolResult(
        card=ToolCard(
            title=f"관리비 {', '.join(requested)} 확정 데이터",
            quote=_fee_months_quote(months, avg_total, missing, excluded),
            source_kind="tool:get_fees",
            data=_fee_months_data(requested, months, avg_total, missing, excluded),
        )
    )


def _fee_months_quote(
    months: list[tuple[str, int]],
    avg_total: int | None,
    missing: list[str],
    excluded: list[str],
) -> str:
    """LLM이 보는 유일한 관리비 텍스트. 평균은 **이미 계산된 값**으로만 들어간다.

    개별 월 금액과 평균을 함께 주되, 모델이 할 일은 인용뿐이다(재계산 금지는 프롬프트 규칙 6).
    """
    quote = "; ".join(f"{period} 합계 {total:,}원" for period, total in months)
    if avg_total is not None:
        quote += f" · {len(months)}개월 평균 총액 {avg_total:,}원"
    if missing:
        quote += f" · {', '.join(missing)} 관리비 내역이 없어 평균을 내지 않았습니다"
    if excluded:
        quote += f" · {', '.join(excluded)}는 입주 승인 이전이라 제외했습니다"
    return quote


def _fee_months_data(
    requested: list[str],
    months: list[tuple[str, int]],
    avg_total: int | None,
    missing: list[str],
    excluded: list[str],
) -> dict[str, Any]:
    """화면용 다중 월 관리비 표 — 단일 월 `_fee_data`의 확장(kind 동일, 키 additive).

    단일 월 키(rows·total·prev_total·diff)는 형태만 유지하고 비운다. `total`에 평균을 넣지
    않는 이유가 사고의 교훈이다 — 화면은 total을 "합계"로 읽는다. 평균은 average_total
    하나뿐이고, 못 냈으면 None이라 화면이 평균 줄을 그리지 않는다(프론트가 대신 계산 금지).
    """
    return {
        "kind": "fee_table",
        "period": ", ".join(requested),
        "rows": [],
        "total": None,
        "prev_total": None,
        "diff": None,
        "months": [{"period": period, "total": total} for period, total in months],
        "average_total": avg_total,
        "missing_periods": missing,
        "excluded_periods": excluded,
    }


async def _fees_scope_average(deps: ToolDeps, ctx: ToolContext, args: GetFeesArgs) -> ToolResult:
    """동·단지 범위의 월 평균(H20-1) — 총액 평균 + 항목별 평균, 전부 SQL 집계값.

    개별 세대 금액·식별자는 quote·data 어느 쪽에도 실리지 않는다(CRITICAL). 표본이
    `MIN_PEER_SAMPLE` 미만이면 평균 자체를 내지 않고(소표본 역산 방지), 0행이면 "데이터
    없음"을 근거로 돌려준다 — 없는 동을 추측하지 않는다(규칙 1).
    """
    scope = args.scope or ""
    is_complex = scope == COMPLEX_SCOPE
    label = "단지 전체" if is_complex else scope
    period = await _scope_period(deps, ctx, args)
    if period is None:
        return ToolResult(note="조회 가능한 관리비 내역이 없습니다.")

    params: dict[str, Any] = {"tid": ctx.tenant_id, "period": period}
    if not is_complex:
        params["dong"] = _dong_names(scope)
    total_sql, items_sql = (
        (_SCOPE_COMPLEX_TOTAL_SQL, _SCOPE_COMPLEX_ITEMS_SQL)
        if is_complex
        else (_SCOPE_DONG_TOTAL_SQL, _SCOPE_DONG_ITEMS_SQL)
    )

    row = (await deps.session.execute(total_sql, params)).first()
    sample_size = int(row.sample_size) if row is not None and row.sample_size is not None else 0
    if sample_size == 0 or row is None or row.avg_total is None:
        return _scope_card(label, f"{label} {period} 관리비 데이터가 없습니다.")
    if sample_size < MIN_PEER_SAMPLE:
        return _scope_card(
            label, f"{label} {period} 관리비는 표본이 적어 평균을 제공하지 않습니다."
        )

    avg_total = int(row.avg_total)
    items = [
        (str(r.name), int(r.avg_amount))
        for r in (await deps.session.execute(items_sql, params)).all()
        if r.avg_amount is not None
    ][:MAX_TOOL_ROWS]
    return ToolResult(
        card=ToolCard(
            title=f"{label} {period} 관리비 평균",
            quote=_scope_quote(label, period, avg_total, sample_size, items),
            source_kind="tool:get_fees",
            data={
                "kind": "fee_table",
                "period": period,
                "rows": [{"name": name, "amount": amount} for name, amount in items],
                "total": avg_total,
                "scope": {
                    "kind": "complex" if is_complex else "dong",
                    "label": label,
                    "sample_size": sample_size,
                },
            },
        )
    )


async def _scope_period(deps: ToolDeps, ctx: ToolContext, args: GetFeesArgs) -> str | None:
    """범위 평균의 대상 월. 여러 달을 물었으면 가장 최근 달 하나만 낸다.

    ponytail: 범위×다중 월 조합은 H20-1 범위 밖(설계 ⑥) — 요청이 관측되면 그때.
    """
    requested = args.requested_periods()
    if requested:
        return requested[-1]
    latest = (await deps.session.execute(_LATEST_SCOPE_PERIOD_SQL, {"tid": ctx.tenant_id})).first()
    return str(latest.period) if latest is not None and latest.period else None


def _dong_names(scope: str) -> list[str]:
    """ "402동" → ["402", "402동"] — buildings.name 표기 흔들림을 둘 다 받는다."""
    bare = scope.removesuffix("동").strip()
    return [bare, scope] if bare and bare != scope else [scope]


def _scope_card(label: str, quote: str) -> ToolResult:
    """평균을 못 내는 경우의 근거 카드 — 숫자는 싣지 않고 이유만 남긴다.

    note가 아니라 카드인 이유: DB가 확인한 "없음/거부"는 확정 근거라 인용할 수 있어야
    한다(get_my_inquiries와 같은 판단 — note면 카드 0으로 폴백된다, R22 실측).
    """
    return ToolResult(
        card=ToolCard(title=f"{label} 관리비 평균", quote=quote, source_kind="tool:get_fees")
    )


def _scope_quote(
    label: str, period: str, avg_total: int, sample_size: int, items: list[tuple[str, int]]
) -> str:
    """LLM이 보는 유일한 텍스트 — 집계값과 표본수뿐(개별 세대 금액 없음)."""
    quote = f"{label} {period} 관리비 평균 총액 {avg_total:,}원 (표본 {sample_size}세대)"
    if items:
        quote += " · 항목 평균: " + ", ".join(f"{name} {amount:,}원" for name, amount in items)
    return quote


async def _peer_average(
    deps: ToolDeps, ctx: ToolContext, household_id: Any, period: str, total: int
) -> PeerAverage | None:
    """같은 단지·같은 평형의 같은 월 평균. 평형 미상·표본 하한 미달이면 None(비교 생략).

    평균·표본수는 SQL 집계가 낸 값 그대로다 — 파이썬이 다시 계산하지 않는다(규칙 5).
    """
    row = (
        await deps.session.execute(
            _PEER_AVG_SQL,
            {"tid": ctx.tenant_id, "hid": household_id, "period": period},
        )
    ).first()
    if row is None or row.avg_total is None or int(row.sample_size) < MIN_PEER_SAMPLE:
        return None
    avg_total = int(row.avg_total)
    return PeerAverage(
        unit_type=str(row.unit_type),
        avg_total=avg_total,
        sample_size=int(row.sample_size),
        diff=total - avg_total,
    )


def _breakdown_items(raw: object) -> list[tuple[str, int]]:
    """fees.breakdown(H8-7 리스트 `[{name,level,amount}]`) → (항목명, 금액) 목록.

    상위 항목(level 0)만, '합계'는 total과 중복이라 제외. 구 dict 포맷도 방어적으로 수용
    (과거 시드·외부 적재 데이터가 남아 있을 수 있다).
    """
    if isinstance(raw, dict):
        return [(str(k), int(v)) for k, v in raw.items()]
    items: list[tuple[str, int]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if not name or name == "합계" or int(entry.get("level", 0)) != 0:
            continue
        items.append((name, int(entry.get("amount", 0))))
    return items


def _fee_quote(
    period: str,
    breakdown: list[tuple[str, int]],
    total: int,
    prev_total: int | None,
    peer: PeerAverage | None,
) -> str:
    top = ", ".join(f"{name} {amount:,}원" for name, amount in breakdown[:3])
    quote = f"{period} 합계 {total:,}원 (주요 항목: {top})"
    if prev_total is not None:
        diff = total - prev_total
        sign = "+" if diff >= 0 else ""
        quote += f" · 전월 {prev_total:,}원 대비 {sign}{diff:,}원"
    if peer is not None:
        sign = "+" if peer.diff >= 0 else ""
        quote += (
            f" · 같은 평형({peer.unit_type}) {peer.sample_size}세대 평균 "
            f"{peer.avg_total:,}원 대비 {sign}{peer.diff:,}원"
        )
    return quote


def _fee_data(
    period: str,
    breakdown: list[tuple[str, int]],
    total: int,
    prev_total: int | None,
    peer: PeerAverage | None,
) -> dict[str, Any]:
    """화면용 관리비 표(ADR-0025 §6) — quote와 달리 **전 항목**을 값 그대로 싣는다.

    quote는 상위 3개만 담아 LLM 토큰을 아끼지만, 화면 표는 잘리면 안 된다. LLM은 이 dict를
    보지 않으므로 여기서 늘려도 비용이 늘지 않는다(규칙 5·8 — 숫자 재작성 경로 없음).

    `peer`(같은 평형 평균)는 비교가 성립할 때만 실린다 — 표본 하한 미달·평형 미상이면
    키 자체가 없다(ADR-0026 결정 3). 개별 세대 금액은 어떤 키로도 싣지 않는다.
    """
    data: dict[str, Any] = {
        "kind": "fee_table",
        "period": period,
        "rows": [{"name": name, "amount": amount} for name, amount in breakdown],
        "total": total,
        "prev_total": prev_total,
        "diff": None if prev_total is None else total - prev_total,
    }
    if peer is not None:
        data["peer"] = {
            "unit_type": peer.unit_type,
            "avg_total": peer.avg_total,
            "sample_size": peer.sample_size,
            "diff": peer.diff,
        }
    return data


def _prev_period(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


# ── 본인 민원 ────────────────────────────────────────────────────────────────

_INQUIRIES_SQL = text(
    "SELECT title, status FROM inquiries "
    "WHERE tenant_id = :tid AND author_user_id = :uid AND deleted_at IS NULL "
    "ORDER BY created_at DESC LIMIT :lim"
)


async def _get_my_inquiries(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    rows = (
        await deps.session.execute(
            _INQUIRIES_SQL, {"tid": ctx.tenant_id, "uid": ctx.user_id, "lim": MAX_TOOL_ROWS}
        )
    ).all()
    # DB가 확인한 "없음"은 확정 근거 — note면 인용 카드가 없어 폴백된다(R22 실측, v2 §6-⓪).
    if not rows:
        quote = "접수한 민원이 없습니다."
    else:
        quote = "; ".join(f"[{r.status}] {r.title}" for r in rows)
    return ToolResult(
        card=ToolCard(title="내 민원 내역", quote=quote, source_kind="tool:get_my_inquiries")
    )


# ── 설비 목록·점검 임박(시설 역할) ───────────────────────────────────────────


async def _get_facilities(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(GetFacilitiesArgs, args)
    # LIMIT 없이 전수 조회 — MAX_TOOL_ROWS(20) < 설비 수(첫마을 37)면 대수 집계가 틀린다
    # (v2 §6-⓪, cursor HIGH). ponytail: 단지당 설비는 수백 규모라 메모리 집계로 충분,
    # 수천 규모가 되면 SQL GROUP BY로 이관.
    sql = "SELECT name, status, code FROM facilities WHERE tenant_id = :tid AND deleted_at IS NULL"
    params: dict[str, object] = {"tid": ctx.tenant_id}
    if a.status:
        sql += " AND status = :status"
        params["status"] = a.status
    sql += " ORDER BY name"
    rows = (await deps.session.execute(text(sql), params)).all()
    condition = f"상태={a.status} " if a.status else ""
    if not rows:
        # DB가 확인한 "없음"은 확정 근거 — 조회 조건을 명시해 카드로 승격(v2 §6-⓪).
        quote = f"{condition}설비가 없습니다."
        return ToolResult(
            card=ToolCard(
                title="설비 목록",
                quote=quote,
                source_kind="tool:get_facilities",
                data=_facility_data([]),
            )
        )
    # 대수 질문의 근거: 총수 + 코드 접두(EL-401-01 → EL) 종류별 수. 나열은 상한으로 자른다.
    kind_counts = Counter((r.code or "기타").split("-")[0] for r in rows)
    counts = " ".join(f"{kind} {n}" for kind, n in kind_counts.most_common())
    listed = "; ".join(f"{r.name}({r.status})" for r in rows[:MAX_TOOL_ROWS])
    overflow = f" 외 {len(rows) - MAX_TOOL_ROWS}개" if len(rows) > MAX_TOOL_ROWS else ""
    quote = f"{condition}총 {len(rows)}개 — 종류별: {counts}. {listed}{overflow}"
    return ToolResult(
        card=ToolCard(
            title="설비 목록",
            quote=quote,
            source_kind="tool:get_facilities",
            data=_facility_data(rows),
        )
    )


def _facility_data(rows: Sequence[Any]) -> dict[str, Any]:
    """화면용 설비 현황(ADR-0025 §6) — 상태별 카운트 + 목록.

    quote는 코드 접두(종류)로 세지만 화면 카드는 **상태**로 센다(정상/점검/고장이 한눈에
    보여야 한다). 총수는 전수 조회 결과 그대로라 quote의 총수와 항상 일치한다.
    """
    status_counts = Counter(str(r.status) for r in rows)
    return {
        "kind": "facility_status",
        "total": len(rows),
        "status_counts": dict(status_counts.most_common()),
        "items": [
            {"name": r.name, "status": r.status, "code": r.code} for r in rows[:MAX_TOOL_ROWS]
        ],
    }


_OVERDUE_SQL = text(
    "SELECT name, next_check_at FROM facilities "
    "WHERE tenant_id = :tid AND deleted_at IS NULL "
    "AND next_check_at IS NOT NULL AND next_check_at <= :threshold "
    "ORDER BY next_check_at LIMIT :lim"
)
# 임박 창 **밖**의 향후 점검 — "다음 점검 언제야?"(ADM-3)의 근거. 임박 목록과 LIMIT를
# 나눠 쓴다(한 쿼리로 합치면 임박 건이 상한을 채웠을 때 예정일이 통째로 잘린다).
_UPCOMING_SQL = text(
    "SELECT name, next_check_at FROM facilities "
    "WHERE tenant_id = :tid AND deleted_at IS NULL "
    "AND next_check_at IS NOT NULL AND next_check_at > :threshold "
    "ORDER BY next_check_at LIMIT :lim"
)


async def _get_overdue_checks(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    threshold = datetime.now(UTC) + timedelta(days=OVERDUE_WINDOW_DAYS)
    rows = (
        await deps.session.execute(
            _OVERDUE_SQL, {"tid": ctx.tenant_id, "threshold": threshold, "lim": MAX_TOOL_ROWS}
        )
    ).all()
    upcoming = (
        await deps.session.execute(
            _UPCOMING_SQL,
            {"tid": ctx.tenant_id, "threshold": threshold, "lim": UPCOMING_CHECK_ROWS},
        )
    ).all()
    return ToolResult(
        card=ToolCard(
            title="점검 일정(임박·초과 + 다음 예정)",
            quote=_check_quote(rows, upcoming),
            source_kind="tool:get_overdue_checks",
        )
    )


# ── 외부 차량 장기주차(시설 역할, H19-3 · ADR-0026 결정 2) ───────────────────

# household_id IS NULL = 입주민 명부에 없는 외부 차량, spot_no IS NOT NULL = 주차 중(H16).
# **plate_enc(차량번호 암호문)는 SELECT 자체를 하지 않는다** — 면 번호와 경과 시간이면 현장
# 확인에 충분하고, 안 읽으면 복호·마스킹 실패 경로도 없다(규칙 2 · search_similar_inquiries 선례).
_LONGTERM_PARKING_SQL = text(
    "SELECT spot_no, entry_at FROM parking_vehicles "
    "WHERE tenant_id = :tid AND household_id IS NULL "
    "AND spot_no IS NOT NULL AND entry_at IS NOT NULL AND entry_at <= :threshold "
    "ORDER BY entry_at LIMIT :lim"
)


async def _find_longterm_parking(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(LongtermParkingArgs, args)
    now = datetime.now(UTC)
    rows = (
        await deps.session.execute(
            _LONGTERM_PARKING_SQL,
            {
                "tid": ctx.tenant_id,
                "threshold": now - timedelta(hours=a.hours),
                "lim": MAX_TOOL_ROWS,
            },
        )
    ).all()
    # 0건도 DB가 확인한 확정 근거 — note면 인용 카드가 없어 폴백된다(⓪ 계약, R22 실측).
    if not rows:
        quote = f"{a.hours}시간 이상 주차된 외부 차량이 없습니다."
    else:
        # 건수 머리말은 inquiries·notices와 같은 이유 — 목록만 주면 8B가 근거의 존재를 놓친다.
        listed = "\n".join(
            f"- {r.spot_no}면 ({_elapsed_hours(now, r.entry_at)}시간 경과)" for r in rows
        )
        quote = f"{a.hours}시간 이상 주차된 외부 차량 {len(rows)}대(오래된 순):\n{listed}"
    return ToolResult(
        card=ToolCard(
            title="외부 차량 장기주차",
            quote=quote,
            source_kind="tool:find_longterm_parking",
        )
    )


def _elapsed_hours(now: datetime, entry_at: datetime) -> int:
    """입차 후 경과 시간(시간, 내림). 계산은 도구가 확정한다 — LLM은 시간을 재계산하지 않는다."""
    return int((now - entry_at).total_seconds() // 3600)


def _check_quote(rows: Sequence[Any], upcoming: Sequence[Any]) -> str:
    """임박·초과 목록 + 다음 점검 예정일.

    DB가 확인한 "없음"도 확정 근거라 카드로 낸다(R22 실측, v2 §6-⓪). 다만 둘 다 비었으면
    "점검이 없다"가 아니라 **예정일이 등록되지 않았다**고 말해야 한다 — 첫마을 시드는
    next_check_at이 전부 NULL이라, 없는 일정을 지어내면 규칙 1 위반이다.
    """
    listed = "; ".join(f"{r.name}: {r.next_check_at:%Y-%m-%d}" for r in rows)
    next_listed = "; ".join(f"{r.name}: {r.next_check_at:%Y-%m-%d}" for r in upcoming)
    if not rows and not upcoming:
        return "점검 예정일이 등록된 설비가 없습니다 — 다음 점검 예정일 미등록(일정 미상)."
    parts = [
        f"{OVERDUE_WINDOW_DAYS}일 이내 기한 임박·초과: {listed}"
        if rows
        else f"{OVERDUE_WINDOW_DAYS}일 이내 점검 예정이거나 기한을 넘긴 설비가 없습니다."
    ]
    if next_listed:
        parts.append(f"다음 점검 예정: {next_listed}")
    return " / ".join(parts)


# ── 레지스트리 조립 ──────────────────────────────────────────────────────────


def default_registry() -> ToolRegistry:
    """운영 도구 15종. 시설 도구는 FACILITY·MANAGER, 민원 집계는 MANAGER·STAFF,
    그래프 도구는 Neo4j 가용 시만 노출.

    되묻기(ask_clarification)는 전 역할 노출이지만 실행되지 않는다 — 오케스트레이터가
    이름으로 판별해 되묻고 종료한다(ADR-0025 §4).
    """
    return ToolRegistry(
        [
            ask_clarification_tool(),
            find_in_floor_plan_tool(),
            trace_home_device_issue_tool(),
            find_nearest_available_parking_tool(),
            find_my_vehicle_tool(),
            search_similar_inquiries_tool(),
            summarize_inquiries_tool(),
            get_recent_notices_tool(),
            Tool(
                name="search_documents",
                # get_recent_notices와 갈리는 축은 "목록이냐 내용이냐"다 — 뒷문장 한 줄만
                # 덧대 내용 질의 쪽을 못박는다(기존 문구는 그대로 — 라우팅 회귀 위험).
                description=(
                    "공지·규약·회의록 등 단지 문서에서 근거를 검색한다. "
                    "점검 일자·규정처럼 문서에 뭐라고 적혀 있는지를 물을 때 쓴다."
                ),
                args_model=QueryArgs,
                run=_search_documents,
            ),
            Tool(
                name="search_facility_graph",
                # "정비 이력"이 get_overdue_checks의 "점검"과 의미상 겹쳐, 점검 기한 질문이
                # 전부 이 도구로 샜다(H15-2 R22 실측 0/3). 이 도구는 **과거 장애의 원인 추적**
                # 전용임을 명시하고, 기한·일정 질문은 배제한다.
                description=(
                    "이미 발생한 증상의 원인 후보를 과거 장애·정비 이력과 연결 설비에서 찾는다. "
                    "고장·이상 증상이 있을 때 쓴다 — 앞으로 해야 할 점검 기한·일정 질문에는 "
                    "쓰지 않는다."
                ),
                args_model=QueryArgs,
                run=_search_facility_graph,
                allowed_roles=FACILITY_ROLES,
                requires_graph=True,
            ),
            Tool(
                name="get_fees",
                # 평균 비교는 별도 도구가 아니라 이 도구의 결과에 붙는다(ADR-0026 결정 3 —
                # 도구 수는 8B 라우팅 예산). "다른 세대와 비교" 질의가 이리로 오도록 명시.
                description=(
                    "본인 세대의 월 관리비 항목·합계·전월 대비와 "
                    "같은 평형 세대 평균 대비를 조회한다. "
                    "여러 달의 평균·비교를 물으면 그 달을 모두 나열해 한 번에 조회한다 — "
                    "직접 더하거나 나누지 않는다. "
                    "scope에 '402동' 같은 동 이름이나 '전체'를 주면 그 범위의 평균 관리비"
                    "(총액·항목별)를 조회한다. 특정 동·전체 평균 질문에만 scope를 쓰고, "
                    "본인 관리비 질문에는 쓰지 않는다."
                ),
                args_model=GetFeesArgs,
                run=_get_fees,
            ),
            Tool(
                name="get_my_inquiries",
                # 신고형 질의를 받는 search_similar_inquiries와 갈라지는 지점은 "이미 접수한
                # 내 건"이다 — 그 어휘를 설명에 명시해야 8B가 둘을 구분한다(2026-08-01 실측).
                description=(
                    "내가 이미 접수한 민원의 제목과 처리 상태를 조회한다. "
                    "'내 민원', '접수한 민원'의 진행 상황을 물을 때 쓴다."
                ),
                args_model=NoArgs,
                run=_get_my_inquiries,
            ),
            Tool(
                name="get_facilities",
                # 설비 현황 질문("승강기 몇 대", "어떤 설비", "상태")이 문서 검색으로 새지
                # 않도록 용례를 명시한다 — 파일럿 실측에서 대수 질문이 라우팅되지 않았다.
                # 용례 5개로 늘린 확장판을 실측했으나 기각(H15-2 R22): 3/7 → 2~3/7로 변화
                # 없음. 오라우팅은 설명 부족이 아니라 모델이 "설비 정보는 문서에 있다"고
                # 판단하는 문제라 설명을 늘려도 안 바뀐다 — 프롬프트 길이만 비용. 중복 제거는
                # 통하고(get_overdue_checks 0/3→3/3) 용례 추가는 안 통한다는 대비 사례.
                # 배제 문장은 R36 실측 — "우리 단지 수전용량은?"(0048)이 이리로 새고 빈손으로
                # 끝났다. SELECT에는 사양 컬럼이 없다(설계 수치는 문서에만 있다).
                description=(
                    "단지 공용 설비(승강기·펌프·소방·CCTV·충전기 등)의 목록·대수·"
                    "현재 상태를 조회한다. 설비가 몇 대인지, 어떤 설비가 있는지, 상태가 "
                    "어떤지 묻는 질문에 사용한다. 수전용량·설계 수치처럼 문서에 적힌 사양을 "
                    "묻는 질문에는 쓰지 않는다 — 문서 검색을 쓴다."
                ),
                args_model=GetFacilitiesArgs,
                run=_get_facilities,
                allowed_roles=FACILITY_ROLES,
            ),
            Tool(
                name="get_overdue_checks",
                # 용례를 명시한다 — 설명이 한 줄일 때 이 도구는 한 번도 선택되지 않았다(R22 0/3).
                # 윈도우는 7일 — "이번 달"을 약속하면 월말에 정답이 어긋난다(v2 §6-⓪).
                description=(
                    "점검 기한이 지났거나 7일 이내로 임박한 설비와 그 다음 점검 예정일을 "
                    "조회한다. 점검 기한·일정을 묻는 질문에 사용한다 — '점검 기한이 지난 "
                    "설비', '점검이 임박한 설비', '다음 점검은 언제'."
                ),
                args_model=NoArgs,
                run=_get_overdue_checks,
                allowed_roles=FACILITY_ROLES,
            ),
            Tool(
                name="find_longterm_parking",
                # 경계는 두 축이다(R22 — 의미 중복이 라우팅을 무너뜨린다):
                # ①빈자리 찾기(find_nearest_available_parking) ②내 차 위치. 둘 다 "주차"
                # 어휘를 공유하므로, 이 도구는 **외부 차량·장기·단속** 어휘만 쓰고 나머지는
                # 명시적으로 배제한다.
                description=(
                    "입주민 명부에 없는 외부 차량이 오래 세워져 있는 주차면을 찾는다"
                    "(면 번호·경과 시간, 오래 세워진 순). 장기 주차·방치 차량 단속·"
                    "무단 주차 점검을 물을 때 쓴다 — 주차할 빈자리를 찾거나 특정 차량이 "
                    "어디 있는지 묻는 질문에는 쓰지 않는다."
                ),
                args_model=LongtermParkingArgs,
                run=_find_longterm_parking,
                allowed_roles=FACILITY_ROLES,
            ),
        ]
    )
