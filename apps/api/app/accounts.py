"""계정 수명주기 서비스 — 소프트 삭제 + PII 비식별 (H7-6, ADR-0014 개정).

삭제는 복구 불가가 정본: 행은 남기되(감사·FK 보존) 식별 가능한 것을 전부 말소한다.
login_id(케이드 HMAC)·password_hash·pii_vault 암호문/해시 말소 + 전 세션 revoke.
부분 유니크(uq_users_login_id_active)가 deleted_at IS NULL만 검사하므로 같은
이메일 재가입·재초대가 가능하다. 호출부가 tenant 컨텍스트(set_config)와 인가를 책임진다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.session import SessionStore
from liviq_db.models import PiiVault, User


async def soft_delete_user(session: AsyncSession, session_store: SessionStore, user: User) -> None:
    """소프트 삭제 + PII 비식별 + 전 세션 즉시 revoke(ADR-0011)."""
    if user.pii_ref is not None:
        vault = await session.scalar(
            select(PiiVault).where(
                PiiVault.id == user.pii_ref, PiiVault.tenant_id == user.tenant_id
            )
        )
        if vault is not None:
            vault.name_enc = None
            vault.phone_enc = None
            vault.email_enc = None
            vault.birth_date_enc = None
            vault.name_hash = None
            vault.phone_hash = None
            vault.birth_date_hash = None

    user.login_id = None
    user.password_hash = None
    user.status = "withdrawn"
    user.deleted_at = datetime.now(UTC)
    await session.flush()
    await session_store.revoke_all_for_user(str(user.tenant_id), str(user.id))
