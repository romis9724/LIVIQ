"""최초 SYS_ADMIN 부트스트랩 — 시스템 테넌트 + 시스템 관리자 계정 생성 (H7-2, ADR-0014).

설치 시 1회 실행한다. 고정 시스템 테넌트(00000000-...-000000000000, "LIVIQ 시스템")를 upsert하고
그 소속으로 SYS_ADMIN 계정을 만든다 — 임시 비밀번호를 생성해 **stdout에 출력**하고
must_change_password=True로 첫 로그인 시 변경을 강제한다(변경 전 다른 엔드포인트 접근 불가).

이메일은 PII다 — 평문 컬럼 금지(pii_vault.email_enc 암호화 + login_id=이메일 keyed HMAC,
routers/auth.py 정규화·해시 경로 재사용). 비밀번호는 Argon2id 해시만 저장.

멱등: 같은 이메일이 이미 있으면 변경 없이 안내만 한다. 임시 비밀번호 재발급은
`--reset-password` 플래그로만 수행한다.

실행법(seed 실행 관행 — 루트 .env 로드):

    cd apps/api
    uv run --no-sync --env-file ../../.env python scripts/bootstrap_sys_admin.py \\
        --email admin@example.com

    # 임시 비밀번호 재발급(기존 계정)
    uv run --no-sync --env-file ../../.env python scripts/bootstrap_sys_admin.py \\
        --email admin@example.com --reset-password
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import secrets
import uuid
from dataclasses import dataclass

from app.config import SYSTEM_TENANT_ID  # noqa: E402 — 단일 정의 재사용
from app.password import hash_password
from app.pii import PiiCrypto, get_pii_crypto
from app.routers.auth import _normalize_email
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import PiiVault, Tenant, User, UserRole

SYSTEM_TENANT_NAME = "LIVIQ 시스템"
_TEMP_PASSWORD_BYTES = 12  # secrets.token_urlsafe 엔트로피(임시 비밀번호는 첫 로그인 후 변경 강제)


@dataclass(frozen=True)
class BootstrapOutcome:
    """부트스트랩 결과. temp_password는 신규 생성·재발급 시에만 값(기존·무변경은 None)."""

    user_id: uuid.UUID
    created: bool
    temp_password: str | None


async def bootstrap_sys_admin(
    session: AsyncSession,
    crypto: PiiCrypto,
    email: str,
    *,
    reset_password: bool = False,
) -> BootstrapOutcome:
    """시스템 테넌트 upsert + SYS_ADMIN 계정 생성/조회. 멱등(존재 시 무변경, 재발급은 플래그).

    users·user_roles·pii_vault는 FORCE RLS 대상이라 app.tenant_id를 시스템 테넌트로 설정한
    뒤 쓴다. tenants는 RLS 예외라 전역 upsert 가능.
    """
    # ── 시스템 테넌트 upsert(RLS 예외) ─────────────────────────────────────
    if await session.scalar(select(Tenant.id).where(Tenant.id == SYSTEM_TENANT_ID)) is None:
        session.add(Tenant(id=SYSTEM_TENANT_ID, name=SYSTEM_TENANT_NAME, status="active"))
        await session.flush()

    # ── 시스템 테넌트 격리 컨텍스트로 전환(users·pii_vault·user_roles 쓰기) ──
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(SYSTEM_TENANT_ID))
    )
    email_norm = _normalize_email(email)
    login_id = crypto.hmac_hash(email_norm)
    now = datetime.datetime.now(datetime.UTC)

    existing = await session.scalar(
        select(User).where(User.login_id == login_id, User.deleted_at.is_(None))
    )
    if existing is not None:
        if not reset_password:
            return BootstrapOutcome(user_id=existing.id, created=False, temp_password=None)
        temp = secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)
        existing.password_hash = hash_password(temp)
        existing.must_change_password = True
        existing.email_verified_at = existing.email_verified_at or now
        await session.flush()
        return BootstrapOutcome(user_id=existing.id, created=False, temp_password=temp)

    # ── 신규 SYS_ADMIN 생성 ────────────────────────────────────────────────
    dek = await crypto.get_dek(session, SYSTEM_TENANT_ID)
    vault = PiiVault(
        tenant_id=SYSTEM_TENANT_ID,
        email_enc=crypto.encrypt(dek, email_norm),
        key_version=1,
    )
    session.add(vault)
    await session.flush()
    temp = secrets.token_urlsafe(_TEMP_PASSWORD_BYTES)
    user = User(
        tenant_id=SYSTEM_TENANT_ID,
        login_id=login_id,
        password_hash=hash_password(temp),
        status="active",  # 상태는 active, 접근 게이트는 must_change_password가 담당
        email_verified_at=now,
        must_change_password=True,
        pii_ref=vault.id,
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(tenant_id=SYSTEM_TENANT_ID, user_id=user.id, role="SYS_ADMIN"))
    await session.flush()
    return BootstrapOutcome(user_id=user.id, created=True, temp_password=temp)


def _print_outcome(email: str, outcome: BootstrapOutcome) -> None:
    """임시 비밀번호는 여기서만 stdout에 출력(로그 금지). 첫 로그인 후 변경 강제 안내."""
    if outcome.created:
        print(f"SYS_ADMIN 생성됨: {email}")
        print(f"임시 비밀번호: {outcome.temp_password}")
        print("첫 로그인 후 반드시 변경하세요 — 변경 전에는 다른 기능에 접근할 수 없습니다.")
    elif outcome.temp_password is not None:
        print(f"SYS_ADMIN 임시 비밀번호 재발급: {email}")
        print(f"임시 비밀번호: {outcome.temp_password}")
        print("첫 로그인 후 반드시 변경하세요 — 변경 전에는 다른 기능에 접근할 수 없습니다.")
    else:
        print(f"이미 존재하는 SYS_ADMIN: {email} (변경 없음).")
        print("임시 비밀번호 재발급이 필요하면 --reset-password 플래그로 재실행하세요.")


async def _run(email: str, *, reset_password: bool) -> None:
    engine = create_engine()
    factory = create_session_factory(engine)
    crypto = get_pii_crypto()
    try:
        async with factory() as session, session.begin():
            outcome = await bootstrap_sys_admin(
                session, crypto, email, reset_password=reset_password
            )
        _print_outcome(email, outcome)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="최초 SYS_ADMIN 부트스트랩(H7-2)")
    parser.add_argument("--email", required=True, help="SYS_ADMIN 이메일")
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="기존 계정의 임시 비밀번호를 재발급(첫 로그인 변경 강제 재설정)",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.email, reset_password=args.reset_password))


if __name__ == "__main__":
    main()
