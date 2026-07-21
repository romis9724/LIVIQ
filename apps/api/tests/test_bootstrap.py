"""부트스트랩 SYS_ADMIN 스크립트 — 계정 생성·멱등·재발급 (H7-2, ADR-0014).

scripts/bootstrap_sys_admin.py의 순수 로직(bootstrap_sys_admin)만 실 PG로 검증한다.
임시 비밀번호는 Argon2id 해시로만 저장(평문 0)·must_change_password=True가 CRITICAL.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from app.pii import PiiCrypto
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Tenant, User, UserRole

# scripts/는 패키지가 아니라 import path에 직접 추가한다(스크립트 실행 관행).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import bootstrap_sys_admin as boot  # type: ignore[import-not-found]  # noqa: E402

_KEK = base64.b64encode(b"0" * 32).decode()
_EMAIL = "admin@example.com"


def _crypto() -> PiiCrypto:
    return PiiCrypto(_KEK)


async def test_bootstrap_creates_sys_admin_in_system_tenant(db_session: AsyncSession) -> None:
    crypto = _crypto()
    outcome = await boot.bootstrap_sys_admin(db_session, crypto, _EMAIL, reset_password=False)

    assert outcome.created is True
    assert outcome.temp_password is not None

    tenant = await db_session.scalar(select(Tenant).where(Tenant.id == boot.SYSTEM_TENANT_ID))
    assert tenant is not None and tenant.name == boot.SYSTEM_TENANT_NAME

    user = await db_session.scalar(select(User).where(User.id == outcome.user_id))
    assert user is not None
    assert user.status == "active"
    assert user.must_change_password is True
    assert user.email_verified_at is not None
    # 비밀번호는 Argon2id 해시만(평문 미포함) — login_id는 keyed HMAC(평문 이메일 아님).
    assert user.password_hash is not None and user.password_hash.startswith("$argon2id$")
    assert outcome.temp_password not in user.password_hash
    assert user.login_id == crypto.hmac_hash(_EMAIL)

    role = await db_session.scalar(select(UserRole.role).where(UserRole.user_id == outcome.user_id))
    assert role == "SYS_ADMIN"


async def test_bootstrap_idempotent_leaves_account_unchanged(db_session: AsyncSession) -> None:
    crypto = _crypto()
    first = await boot.bootstrap_sys_admin(db_session, crypto, _EMAIL, reset_password=False)
    hash_before = await db_session.scalar(
        select(User.password_hash).where(User.id == first.user_id)
    )

    second = await boot.bootstrap_sys_admin(db_session, crypto, _EMAIL, reset_password=False)

    assert second.created is False
    assert second.temp_password is None  # 재발급 아님 — 안내만
    assert second.user_id == first.user_id
    hash_after = await db_session.scalar(select(User.password_hash).where(User.id == first.user_id))
    assert hash_after == hash_before  # 비밀번호 불변

    # SYS_ADMIN 계정은 정확히 1개(중복 생성 없음).
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(
            t=str(boot.SYSTEM_TENANT_ID)
        )
    )
    count = await db_session.scalar(
        select(func.count()).select_from(UserRole).where(UserRole.role == "SYS_ADMIN")
    )
    assert count == 1


async def test_bootstrap_reset_password_reissues_temp(db_session: AsyncSession) -> None:
    crypto = _crypto()
    first = await boot.bootstrap_sys_admin(db_session, crypto, _EMAIL, reset_password=False)
    hash_before = await db_session.scalar(
        select(User.password_hash).where(User.id == first.user_id)
    )

    reset = await boot.bootstrap_sys_admin(db_session, crypto, _EMAIL, reset_password=True)

    assert reset.created is False
    assert reset.temp_password is not None  # 새 임시 비밀번호
    assert reset.user_id == first.user_id
    user = await db_session.scalar(select(User).where(User.id == first.user_id))
    assert user is not None
    assert user.password_hash != hash_before  # 실제 교체
    assert user.must_change_password is True  # 재발급도 변경 강제
