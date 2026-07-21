"""이메일 인증·초대·재설정 토큰 서비스 (ADR-0014).

원문 토큰은 URL로만 전달하고 DB엔 SHA-256 hex만 저장한다(유출 시 원문 복원 불가).
발급은 tenant 컨텍스트 세션에서, 소비(조회)는 클릭 시점 tenant 확정 전이라 auth_lookup
세션에서 이뤄진다 — 소진 표시(used_at)는 호출부가 tenant 컨텍스트 전환 후 기록한다.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import AuthToken

VERIFY_TTL = timedelta(hours=24)
INVITE_TTL = timedelta(days=7)
RESET_TTL = timedelta(hours=1)


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    purpose: str,
    ttl: timedelta,
) -> str:
    """토큰 발급 — 원문 반환(호출부가 링크로만 전달), DB엔 해시만 저장.

    tenant_isolation 하에서 INSERT하므로 세션에 app.tenant_id가 설정돼 있어야 한다.
    """
    raw = secrets.token_urlsafe(32)
    session.add(
        AuthToken(
            tenant_id=tenant_id,
            user_id=user_id,
            purpose=purpose,
            token_hash=_hash_token(raw),
            expires_at=datetime.now(UTC) + ttl,
        )
    )
    await session.flush()
    return raw


async def consume(session: AsyncSession, raw: str, purpose: str) -> AuthToken | None:
    """원문 토큰을 검증·반환. 소진 표시는 하지 않는다(호출부가 tenant 전환 후 used_at 기록).

    purpose 불일치·이미 소진·만료 중 하나라도면 None(호출부가 무효 처리).
    조회는 auth_lookup 세션(전역)에서 가능 — 반환된 tenant_id로 컨텍스트를 전환한다.
    """
    token = await session.scalar(select(AuthToken).where(AuthToken.token_hash == _hash_token(raw)))
    if token is None or token.purpose != purpose or token.used_at is not None:
        return None
    if token.expires_at <= datetime.now(UTC):
        return None
    return token
