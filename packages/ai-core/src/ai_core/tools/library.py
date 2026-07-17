"""도구 구현 6종 (docs/01 §5.2, ADR-0007) — 전부 읽기 전용.

SQL 도구는 retrieval.py와 동일하게 raw `text()` SELECT를 주입 세션으로 실행한다
(ai-core는 liviq_db ORM에 의존하지 않는다 — 계약은 컬럼명뿐). RLS가 1차 방어,
쿼리의 tenant_id·소유권 조건이 2차 방어(이중 방어, 규칙 3·4).

tenant_id·user_id는 항상 `ToolContext`에서 오며 LLM 인자로 받지 않는다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

from pydantic import BaseModel, Field
from sqlalchemy import text

from ai_core.graph import IncidentContext, IncidentHit
from ai_core.llm.client import LlmError
from ai_core.tools.registry import (
    Tool,
    ToolCard,
    ToolContext,
    ToolDeps,
    ToolRegistry,
    ToolResult,
)

# docs/08 도구 결과 상한 — 목록형 도구 결과 행 수 제한(토큰=비용).
MAX_TOOL_ROWS = 20
GRAPH_SEARCH_K = 5
# 점검 임박 판정 창(일).
OVERDUE_WINDOW_DAYS = 7

FACILITY_ROLES = frozenset({"FACILITY", "MANAGER"})
_PERIOD_PATTERN = r"^\d{4}-\d{2}$"


# ── 인자 모델 ────────────────────────────────────────────────────────────────


class QueryArgs(BaseModel):
    query: str = Field(..., min_length=1, description="검색할 자연어 질의")


class GetFeesArgs(BaseModel):
    period: str | None = Field(
        None, pattern=_PERIOD_PATTERN, description="조회할 월(YYYY-MM). 생략 시 최근 확정 월"
    )


class GetFacilitiesArgs(BaseModel):
    status: str | None = Field(None, description="상태 필터(normal|check|fault|risk). 생략 시 전체")


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
        query_vec, tenant_id=ctx.tenant_id, visibilities=ctx.visibilities
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
        work = f" · 최근정비: {', '.join(c.recent_work)}" if c and c.recent_work else ""
        lines.append(f"{facility} 증상: {hit.symptom}{work}")
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


async def _get_fees(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(GetFeesArgs, args)
    urow = (
        await deps.session.execute(_USER_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})
    ).first()
    if urow is None or urow.household_id is None:
        return ToolResult(note="세대가 배정되지 않아 관리비를 조회할 수 없습니다.")
    approved = urow.approved_at.strftime("%Y-%m") if urow.approved_at else "9999-12"

    period = a.period
    if period is None:
        latest = (
            await deps.session.execute(
                _LATEST_FEE_SQL,
                {"tid": ctx.tenant_id, "hid": urow.household_id, "approved": approved},
            )
        ).first()
        if latest is None:
            return ToolResult(note="조회 가능한 관리비 내역이 없습니다.")
        period = latest.period
    elif period < approved:
        return ToolResult(note=f"{period} 관리비는 조회할 수 없습니다(입주 승인 이전).")

    fee = (
        await deps.session.execute(
            _FEE_SQL, {"tid": ctx.tenant_id, "hid": urow.household_id, "period": period}
        )
    ).first()
    if fee is None or fee.total_amount is None:
        return ToolResult(note=f"{period} 관리비 내역이 없습니다.")
    breakdown = {k: int(v) for k, v in (fee.breakdown or {}).items()}
    total = int(fee.total_amount)

    prev_period = _prev_period(period)
    prev_total: int | None = None
    if prev_period >= approved:
        prev = (
            await deps.session.execute(
                _FEE_SQL, {"tid": ctx.tenant_id, "hid": urow.household_id, "period": prev_period}
            )
        ).first()
        prev_total = int(prev.total_amount) if prev and prev.total_amount is not None else None

    return ToolResult(
        card=ToolCard(
            title=f"관리비 {period} 확정 데이터",
            quote=_fee_quote(period, breakdown, total, prev_total),
            source_kind="tool:get_fees",
        )
    )


def _fee_quote(period: str, breakdown: dict[str, int], total: int, prev_total: int | None) -> str:
    top = ", ".join(f"{name} {amount:,}원" for name, amount in list(breakdown.items())[:3])
    quote = f"{period} 합계 {total:,}원 (주요 항목: {top})"
    if prev_total is not None:
        diff = total - prev_total
        sign = "+" if diff >= 0 else ""
        quote += f" · 전월 {prev_total:,}원 대비 {sign}{diff:,}원"
    return quote


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
    if not rows:
        return ToolResult(note="접수한 민원이 없습니다.")
    quote = "; ".join(f"[{r.status}] {r.title}" for r in rows)
    return ToolResult(
        card=ToolCard(title="내 민원 내역", quote=quote, source_kind="tool:get_my_inquiries")
    )


# ── 설비 목록·점검 임박(시설 역할) ───────────────────────────────────────────


async def _get_facilities(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(GetFacilitiesArgs, args)
    sql = "SELECT name, status FROM facilities WHERE tenant_id = :tid AND deleted_at IS NULL"
    params: dict[str, object] = {"tid": ctx.tenant_id, "lim": MAX_TOOL_ROWS}
    if a.status:
        sql += " AND status = :status"
        params["status"] = a.status
    sql += " ORDER BY name LIMIT :lim"
    rows = (await deps.session.execute(text(sql), params)).all()
    if not rows:
        return ToolResult(note="설비 목록이 없습니다.")
    quote = "; ".join(f"{r.name}({r.status})" for r in rows)
    return ToolResult(
        card=ToolCard(title="설비 목록", quote=quote, source_kind="tool:get_facilities")
    )


_OVERDUE_SQL = text(
    "SELECT name, next_check_at FROM facilities "
    "WHERE tenant_id = :tid AND deleted_at IS NULL "
    "AND next_check_at IS NOT NULL AND next_check_at <= :threshold "
    "ORDER BY next_check_at LIMIT :lim"
)


async def _get_overdue_checks(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    threshold = datetime.now(UTC) + timedelta(days=OVERDUE_WINDOW_DAYS)
    rows = (
        await deps.session.execute(
            _OVERDUE_SQL, {"tid": ctx.tenant_id, "threshold": threshold, "lim": MAX_TOOL_ROWS}
        )
    ).all()
    if not rows:
        return ToolResult(note="점검 기한이 임박하거나 초과된 설비가 없습니다.")
    quote = "; ".join(f"{r.name}: {r.next_check_at:%Y-%m-%d}" for r in rows)
    return ToolResult(
        card=ToolCard(
            title="점검 기한 임박·초과 설비",
            quote=quote,
            source_kind="tool:get_overdue_checks",
        )
    )


# ── 레지스트리 조립 ──────────────────────────────────────────────────────────


def default_registry() -> ToolRegistry:
    """운영 도구 6종. 시설 도구는 FACILITY·MANAGER + 그래프 도구는 Neo4j 가용 시만 노출."""
    return ToolRegistry(
        [
            Tool(
                name="search_documents",
                description="공지·규약·회의록 등 단지 문서에서 근거를 검색한다.",
                args_model=QueryArgs,
                run=_search_documents,
            ),
            Tool(
                name="search_facility_graph",
                description="유사 장애·연결 설비·정비 이력을 검색해 원인 후보 근거를 찾는다.",
                args_model=QueryArgs,
                run=_search_facility_graph,
                allowed_roles=FACILITY_ROLES,
                requires_graph=True,
            ),
            Tool(
                name="get_fees",
                description="본인 세대의 월 관리비 항목·합계·전월 대비를 조회한다.",
                args_model=GetFeesArgs,
                run=_get_fees,
            ),
            Tool(
                name="get_my_inquiries",
                description="본인이 접수한 민원의 제목·처리 상태를 조회한다.",
                args_model=NoArgs,
                run=_get_my_inquiries,
            ),
            Tool(
                name="get_facilities",
                description="단지 설비 목록과 현재 상태를 조회한다.",
                args_model=GetFacilitiesArgs,
                run=_get_facilities,
                allowed_roles=FACILITY_ROLES,
            ),
            Tool(
                name="get_overdue_checks",
                description="점검 기한이 임박했거나 초과한 설비를 조회한다.",
                args_model=NoArgs,
                run=_get_overdue_checks,
                allowed_roles=FACILITY_ROLES,
            ),
        ]
    )
