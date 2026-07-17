"""질의 레이트 리밋 — Redis 고정 창(사용자별·단지별 분당 상한) (docs/08 §8, docs/09 §8.5 H4-1).

AI 질의 폭주·비용 남용 차단. 세션(fail-closed)과 달리 **fail-open** — 리밋은 가용성
보조 장치이지 인가 게이트가 아니다. Redis 장애 시 열어주되 경고 로그를 남긴다.
초과 시 429 + Retry-After 헤더. 상한 0 = 비활성.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import get_settings
from app.deps import RequestContext, get_context
from app.session import get_redis

logger = logging.getLogger("app.rate_limit")

_WINDOW_TTL = 120  # 고정 창(1분) 카운터 TTL — 창 경계 넘겨 여유 후 자연 폐기
_RETRY_AFTER = "60"  # 다음 창까지 대기 안내(고정 창 상한, ponytail: 초 단위 정밀 계산 불필요)


def _window(now: datetime) -> str:
    """분 단위 고정 창 키 세그먼트. now 주입 가능(테스트 결정론)."""
    return now.strftime("%Y%m%d%H%M")


def _too_many() -> HTTPException:
    return HTTPException(
        status_code=429,
        detail="요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        headers={"Retry-After": _RETRY_AFTER},
    )


async def _incr_window(redis: Redis, key: str) -> int:
    """고정 창 카운터 증가 — 첫 증가면 TTL 부여."""
    count = int(await redis.incr(key))
    if count == 1:
        await redis.expire(key, _WINDOW_TTL)
    return count


async def check_rate_limit(
    redis: Redis,
    *,
    user_id: str,
    tenant_id: str,
    user_limit: int,
    tenant_limit: int,
    now: datetime | None = None,
) -> None:
    """사용자·단지 분당 상한 검사. 어느 한쪽이라도 초과하면 429. 둘 다 0=비활성.

    Redis 장애는 삼켜서 통과시킨다(fail-open) — 리밋 불가용이 서비스 중단이 되면 안 된다.
    """
    if user_limit <= 0 and tenant_limit <= 0:
        return
    window = _window(now or datetime.now(UTC))
    try:
        if user_limit > 0 and await _incr_window(redis, f"rl:user:{user_id}:{window}") > user_limit:
            raise _too_many()
        if (
            tenant_limit > 0
            and await _incr_window(redis, f"rl:tenant:{tenant_id}:{window}") > tenant_limit
        ):
            raise _too_many()
    except RedisError as exc:  # 가용성 보조 — 장애 시 열어줌(세션과 다름)
        logger.warning("rate-limit Redis 장애 — fail-open 통과: %s", exc)


async def enforce_rate_limit(
    ctx: Annotated[RequestContext, Depends(get_context)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> None:
    """AI 질의 엔드포인트용 의존성 — 설정 상한으로 check_rate_limit 위임."""
    settings = get_settings()
    await check_rate_limit(
        redis,
        user_id=str(ctx.user_id),
        tenant_id=str(ctx.tenant_id),
        user_limit=settings.rate_limit_user_per_min,
        tenant_limit=settings.rate_limit_tenant_per_min,
    )
