"""Redis 서버 세션 스토어 (ADR-0011).

세션 ID만 httpOnly 쿠키로 전달하고 상태는 Redis가 소유한다. 절대 수명 24h·
idle 2h 슬라이딩, 상태 전환 시 즉시 revoke. Redis 장애는 예외로 전파 →
호출부(get_context)가 401 fail-closed 처리한다(로그인 화면으로).
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, cast

from fastapi import Depends
from redis.asyncio import Redis

from app.config import get_settings


async def _resolve[T](result: Awaitable[T] | T) -> T:
    """redis-py 스텁이 동기/비동기 겸용이라 반환이 `Awaitable[T] | T` — 여기서 흡수."""
    if isinstance(result, Awaitable):
        return await cast("Awaitable[T]", result)
    return result


SESSION_ABSOLUTE_TTL = timedelta(hours=24)  # 절대 수명 — 슬라이딩으로도 못 넘김
SESSION_IDLE_TTL = timedelta(hours=2)  # idle 만료 — 조회 시마다 연장(슬라이딩)
OAUTH_STATE_TTL = 600  # PKCE code_verifier 임시 보관(콜백까지) — 10분

_SESSION_PREFIX = "session:"
_USER_SESSIONS_PREFIX = "user_sessions:"
_OAUTH_STATE_PREFIX = "oauth_state:"


@dataclass(frozen=True)
class SessionData:
    """세션 값. kind=onboarding(users 행 없는 신규 로그인)은 tenant/user가 비고,
    google_sub만 있다 — 온보딩 제출에서 사용. status는 계정 상태(상태별 차단 판정용)."""

    tenant_id: str
    user_id: str
    roles: tuple[str, ...]
    kind: str = "user"
    status: str = "active"
    google_sub: str | None = None


def _session_key(session_id: str) -> str:
    return f"{_SESSION_PREFIX}{session_id}"


def _user_sessions_key(tenant_id: str, user_id: str) -> str:
    return f"{_USER_SESSIONS_PREFIX}{tenant_id}:{user_id}"


def _oauth_state_key(state: str) -> str:
    return f"{_OAUTH_STATE_PREFIX}{state}"


class SessionStore:
    """Redis 기반 세션 저장소. `decode_responses=True` 클라이언트를 주입받는다."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def create(
        self, tenant_id: str, user_id: str, roles: list[str], status: str = "active"
    ) -> str:
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        expires_at = now + SESSION_ABSOLUTE_TTL.total_seconds()
        value = json.dumps(
            {
                "kind": "user",
                "tenant_id": tenant_id,
                "user_id": user_id,
                "roles": list(roles),
                "status": status,
                "created_at": now,
                "expires_at": expires_at,  # 절대 만료 판정은 값 기준(TTL은 idle)
            }
        )
        idle = int(SESSION_IDLE_TTL.total_seconds())
        absolute = int(SESSION_ABSOLUTE_TTL.total_seconds())
        set_key = _user_sessions_key(tenant_id, user_id)
        await self._redis.set(_session_key(session_id), value, ex=idle)
        await _resolve(self._redis.sadd(set_key, session_id))  # revoke_all 인덱스
        await _resolve(self._redis.expire(set_key, absolute))
        return session_id

    async def create_onboarding(self, google_sub: str) -> str:
        """users 행 없는 신규 로그인용 세션 — tenant 미정, 온보딩 제출까지만 유효.
        revoke_all 인덱스에 넣지 않는다(user_id 없음 — idle 만료로 자연 폐기)."""
        session_id = secrets.token_urlsafe(32)
        now = time.time()
        value = json.dumps(
            {
                "kind": "onboarding",
                "google_sub": google_sub,
                "created_at": now,
                "expires_at": now + SESSION_ABSOLUTE_TTL.total_seconds(),
            }
        )
        await self._redis.set(
            _session_key(session_id), value, ex=int(SESSION_IDLE_TTL.total_seconds())
        )
        return session_id

    async def get(self, session_id: str) -> SessionData | None:
        key = _session_key(session_id)
        raw = await self._redis.get(key)
        if raw is None:
            return None
        payload = json.loads(raw)
        now = time.time()
        expires_at = float(payload["expires_at"])
        if now >= expires_at:  # 절대 만료 — idle이 남아도 폐기
            await self._redis.delete(key)
            return None
        # idle 슬라이딩 — 단, 절대 만료를 넘기지 않도록 남은 수명으로 캡
        ttl = min(int(SESSION_IDLE_TTL.total_seconds()), int(expires_at - now))
        if ttl > 0:
            await _resolve(self._redis.expire(key, ttl))
        return SessionData(
            tenant_id=payload.get("tenant_id", ""),
            user_id=payload.get("user_id", ""),
            roles=tuple(payload.get("roles", ())),
            kind=payload.get("kind", "user"),
            status=payload.get("status", "active"),
            google_sub=payload.get("google_sub"),
        )

    async def save_oauth_state(
        self, state: str, code_verifier: str, ttl: int = OAUTH_STATE_TTL
    ) -> None:
        await self._redis.set(_oauth_state_key(state), code_verifier, ex=ttl)

    async def pop_oauth_state(self, state: str) -> str | None:
        """1회용 — state CSRF 방어(재사용 불가). GETDEL로 조회·삭제를 원자적으로."""
        return await _resolve(self._redis.getdel(_oauth_state_key(state)))

    async def revoke(self, session_id: str) -> None:
        await self._redis.delete(_session_key(session_id))

    async def revoke_all_for_user(self, tenant_id: str, user_id: str) -> None:
        set_key = _user_sessions_key(tenant_id, user_id)
        session_ids = await _resolve(self._redis.smembers(set_key))
        keys = [_session_key(sid) for sid in session_ids]
        if keys:
            await self._redis.delete(*keys)
        await self._redis.delete(set_key)


_redis: Redis | None = None


def get_redis() -> Redis:  # pragma: no cover — 앱 수명 연결(테스트는 오버라이드)
    global _redis
    if _redis is None:
        _redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


def get_session_store(redis: Annotated[Redis, Depends(get_redis)]) -> SessionStore:
    return SessionStore(redis)
