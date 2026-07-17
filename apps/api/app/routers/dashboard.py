"""dashboard — 운영 대시보드 집계(docs/01 §13, docs/09 §8.5 H4-3, FR-ADM-06).

MANAGER 전용 단일 엔드포인트. 별도 집계 테이블·뷰 없이 SQL 즉석 집계(파일럿 규모).
모든 쿼리에 tenant_id 필터(RLS 이중 방어, 규칙 3). 캐시 카운터는 H4-2가 Redis에
적재한 hits/misses를 그대로 읽는다(없으면 0).
"""

from __future__ import annotations

import datetime
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import RequestContext, get_tenant_session, require_roles
from app.schemas.dashboard import AiStats, BudgetStats, CacheStats, DashboardStatsOut
from app.session import get_redis
from liviq_db.models import Facility, Inquiry, Message

logger = logging.getLogger("app.dashboard")

router = APIRouter(prefix="/admin/dashboard", tags=["dashboard"])

# 상태별 카운트는 값이 0이어도 키가 존재하도록 기본값을 깐다(프런트 매핑 단순화).
_INQUIRY_STATUSES = ("received", "assigned", "in_progress", "done")
_FACILITY_STATUSES = ("normal", "check", "fault", "risk")


def _rate(numerator: int, denominator: int) -> float | None:
    """분모 0이면 null(0 나누기 회피) — 프런트는 '—' 표기."""
    return numerator / denominator if denominator else None


def _avg(value: object) -> float | None:
    return float(value) if value is not None else None  # type: ignore[arg-type]


@router.get("/stats", response_model=DashboardStatsOut)
async def dashboard_stats(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> DashboardStatsOut:
    cutoff = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)

    # AI 통계 — 기간 내 assistant 메시지 1회 스캔으로 카운트·평균·필터 집계.
    ai_row = (
        await session.execute(
            select(
                func.count(),
                func.avg(Message.token_input),
                func.avg(Message.token_output),
                func.count().filter(Message.status == "answered"),
                func.count().filter(Message.status == "fallback"),
                func.count().filter(Message.review_status.is_not(None)),
            ).where(
                Message.tenant_id == ctx.tenant_id,
                Message.role == "assistant",
                Message.created_at >= cutoff,
            )
        )
    ).one()
    total, avg_in, avg_out, answered, fallback, needs_review = ai_row
    ai = AiStats(
        query_count=total,
        avg_token_input=_avg(avg_in),
        avg_token_output=_avg(avg_out),
        answer_rate=_rate(answered, total),
        fallback_rate=_rate(fallback, total),
        needs_review_rate=_rate(needs_review, total),
    )

    # 캐시 적중률 — H4-2 Redis 카운터(없으면 0).
    hits = int(await redis.get(f"cache:hits:{ctx.tenant_id}") or 0)
    misses = int(await redis.get(f"cache:misses:{ctx.tenant_id}") or 0)
    cache = CacheStats(hits=hits, misses=misses, hit_rate=_rate(hits, hits + misses))

    # 일일 토큰 예산 — 오늘(UTC 자정 기준) assistant 입출력 토큰 합계 vs env 예산.
    # 경고만(NFR-COST-01): 초과해도 질의를 막지 않는다. 조회 시점 기록으로 충분(별도 크론 없음).
    budget = await _budget_stats(session, ctx.tenant_id)

    # 민원 상태 분포 — 기간 내 생성(soft delete 제외).
    inquiries = dict.fromkeys(_INQUIRY_STATUSES, 0)
    inq_rows = await session.execute(
        select(Inquiry.status, func.count())
        .where(
            Inquiry.tenant_id == ctx.tenant_id,
            Inquiry.deleted_at.is_(None),
            Inquiry.created_at >= cutoff,
        )
        .group_by(Inquiry.status)
    )
    for status, count in inq_rows.all():
        inquiries[status] = count

    # 시설 상태 분포 — 시점 스냅샷(전체, soft delete 제외 · 기간 무관).
    facilities = dict.fromkeys(_FACILITY_STATUSES, 0)
    fac_rows = await session.execute(
        select(Facility.status, func.count())
        .where(Facility.tenant_id == ctx.tenant_id, Facility.deleted_at.is_(None))
        .group_by(Facility.status)
    )
    for status, count in fac_rows.all():
        facilities[status] = count

    return DashboardStatsOut(
        days=days, ai=ai, cache=cache, budget=budget, inquiries=inquiries, facilities=facilities
    )


async def _budget_stats(session: AsyncSession, tenant_id: object) -> BudgetStats:
    """오늘(UTC) 토큰 합계를 env 예산과 대조. 초과 시 구조화 warning(차단 없음)."""
    limit = get_settings().llm_daily_token_budget
    enabled = limit > 0
    midnight = datetime.datetime.now(datetime.UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    used = int(
        await session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        func.coalesce(Message.token_input, 0)
                        + func.coalesce(Message.token_output, 0)
                    ),
                    0,
                )
            ).where(
                Message.tenant_id == tenant_id,
                Message.role == "assistant",
                Message.created_at >= midnight,
            )
        )
        or 0
    )
    exceeded = enabled and used > limit
    if exceeded:
        logger.warning(
            "daily-token-budget 초과 — tenant=%s used=%d budget=%d (경고만·차단 없음)",
            tenant_id,
            used,
            limit,
        )
    return BudgetStats(enabled=enabled, budget=limit, used_today=used, exceeded=exceeded)
