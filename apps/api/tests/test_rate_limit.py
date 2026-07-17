"""레이트 리밋 단위 테스트 — 고정 창 카운팅·사용자/단지 분리·비활성·fail-open (H4-1).

check_rate_limit을 직접 호출(DB·LLM 불필요). 무엇이 실패해야 실패하는가:
- 한도 내: 예외 없음. 사용자/단지 카운터가 각 키로 분리 누적되지 않으면 오탐.
- 초과: 429(HTTPException). 상한 로직이 깨지면 통과해버려 실패.
- 0=비활성: 몇 번을 호출해도 예외 없음. 비활성 분기가 빠지면 429로 실패.
- fail-open: Redis 장애를 삼키지 않으면 RedisError가 새어 실패.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from app.rate_limit import check_rate_limit
from fastapi import HTTPException
from redis.exceptions import RedisError

_USER = "22222222-2222-2222-2222-222222222222"
_OTHER_USER = "99999999-9999-9999-9999-999999999999"
_TENANT = "11111111-1111-1111-1111-111111111111"
_NOW = datetime(2026, 7, 17, 12, 34, tzinfo=UTC)


@pytest_asyncio.fixture
async def redis() -> AsyncIterator[object]:
    from fakeredis.aioredis import FakeRedis

    client = FakeRedis(decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


async def _call(redis: object, *, user_id: str = _USER, user_limit: int, tenant_limit: int) -> None:
    await check_rate_limit(
        redis,  # type: ignore[arg-type]
        user_id=user_id,
        tenant_id=_TENANT,
        user_limit=user_limit,
        tenant_limit=tenant_limit,
        now=_NOW,
    )


async def test_within_limit_passes(redis: object) -> None:
    # 상한 2 — 2회까지 통과.
    await _call(redis, user_limit=2, tenant_limit=100)
    await _call(redis, user_limit=2, tenant_limit=100)


async def test_user_limit_exceeded_raises_429(redis: object) -> None:
    await _call(redis, user_limit=2, tenant_limit=100)
    await _call(redis, user_limit=2, tenant_limit=100)
    with pytest.raises(HTTPException) as exc:
        await _call(redis, user_limit=2, tenant_limit=100)  # 3번째 초과
    assert exc.value.status_code == 429
    assert exc.value.headers is not None and exc.value.headers["Retry-After"] == "60"


async def test_tenant_limit_exceeded_across_users_raises_429(redis: object) -> None:
    """단지 카운터는 사용자 무관 누적 — 다른 사용자라도 단지 상한 초과 시 429."""
    # 사용자 상한은 넉넉, 단지 상한 2. 서로 다른 사용자 3명이 1회씩.
    await _call(redis, user_id=_USER, user_limit=100, tenant_limit=2)
    await _call(redis, user_id=_OTHER_USER, user_limit=100, tenant_limit=2)
    with pytest.raises(HTTPException) as exc:
        await _call(
            redis, user_id="88888888-8888-8888-8888-888888888888", user_limit=100, tenant_limit=2
        )
    assert exc.value.status_code == 429


async def test_zero_limits_disable_check(redis: object) -> None:
    """0=비활성 — 몇 번을 호출해도 예외 없음(카운터도 만들지 않음)."""
    for _ in range(5):
        await _call(redis, user_limit=0, tenant_limit=0)
    assert await redis.get(f"rl:user:{_USER}:{_NOW.strftime('%Y%m%d%H%M')}") is None  # type: ignore[attr-defined]


async def test_redis_failure_fails_open() -> None:
    """Redis 장애는 삼키고 통과(fail-open) — 리밋은 가용성 보조 장치."""

    class _BrokenRedis:
        async def incr(self, key: str) -> int:
            raise RedisError("boom")

        async def expire(self, key: str, ttl: int) -> bool:  # pragma: no cover
            raise RedisError("boom")

    await check_rate_limit(
        _BrokenRedis(),  # type: ignore[arg-type]
        user_id=_USER,
        tenant_id=_TENANT,
        user_limit=1,
        tenant_limit=1,
        now=_NOW,
    )  # 예외 없이 반환하면 통과
