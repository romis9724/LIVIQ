"""backfill_staff_names.py — 이름 없는 관리 계정(MANAGER·STAFF)에 임의 한글 이름 부여 (ADR-0018).

직원 초대에 이름 입력이 생기기 전(H8-9 이전) 만들어진 관리 계정은 pii_vault.name_enc가
비어 목록에서 이메일로만 보인다. 이 스크립트는 name_enc가 NULL(또는 복호 시 빈값)인
MANAGER·STAFF 계정에 임의 한글 이름을 채워 목록 식별을 회복한다.

- 멱등: 이미 이름이 있으면 skip. 복호 실패(키 불일치·변조)도 skip해 기존 암호문을 덮어쓰지 않음.
- 단지별 DEK로 encrypt(RLS 계약상 app.tenant_id를 단지마다 설정). vault가 없는 계정은
  vault를 새로 만들어 user.pii_ref에 연결한다.
- 이름은 단지 내에서 충돌하지 않도록 성씨 순환 + 역할 접미 + 순번으로 생성한다.

실행(DATABASE_URL은 env로 주입):

    cd apps/api
    uv run --no-sync --env-file ../../.env python scripts/backfill_staff_names.py
"""

from __future__ import annotations

import asyncio
import uuid

from app.pii import PiiCrypto, get_pii_crypto
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import PiiVault, Tenant, User, UserRole

MANAGED_ROLES = ("MANAGER", "STAFF")
_SURNAMES = ("김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신")


def _generated_name(role: str, index: int) -> str:
    """단지 내 충돌 없는 임의 이름 — 성씨 순환 + 역할 접미 + 순번(1부터)."""
    surname = _SURNAMES[index % len(_SURNAMES)]
    suffix = "관리" if role == "MANAGER" else "직원"
    return f"{surname}{suffix}{index + 1}"


def _has_name(crypto: PiiCrypto, dek: bytes, blob: bytes | None) -> bool:
    """name_enc에 실제 이름이 있는지 — NULL·빈값은 False, 복호 실패는 덮어쓰기 방지로 True."""
    if blob is None:
        return False
    try:
        return bool(crypto.decrypt(dek, blob).strip())
    except Exception:  # noqa: BLE001 — 복호 실패 = 다른 키/변조 → 보존(skip)
        return True


async def _backfill_tenant(session: AsyncSession, crypto: PiiCrypto, tenant_id: uuid.UUID) -> int:
    """한 단지의 이름 없는 MANAGER·STAFF에 이름 부여. 채운 계정 수 반환."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    rows = (
        await session.execute(
            select(User.id, User.pii_ref, UserRole.role, PiiVault.name_enc)
            .join(
                UserRole,
                and_(UserRole.user_id == User.id, UserRole.tenant_id == User.tenant_id),
            )
            .outerjoin(
                PiiVault,
                and_(PiiVault.id == User.pii_ref, PiiVault.tenant_id == User.tenant_id),
            )
            .where(
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
                UserRole.role.in_(MANAGED_ROLES),
            )
            .order_by(User.created_at)
        )
    ).all()

    # 다중 역할이면 한 user가 여러 행으로 나온다 — 첫 등장(생성 순)만 유지.
    seen: set[uuid.UUID] = set()
    unique_rows: list[tuple[uuid.UUID, uuid.UUID | None, str, bytes | None]] = []
    for user_id, pii_ref, role, name_enc in rows:
        if user_id in seen:
            continue
        seen.add(user_id)
        unique_rows.append((user_id, pii_ref, role, name_enc))

    if not unique_rows:
        return 0

    dek = await crypto.get_dek(session, tenant_id)
    filled = 0
    for index, (user_id, pii_ref, role, name_enc) in enumerate(unique_rows):
        if _has_name(crypto, dek, name_enc):
            continue
        name = _generated_name(role, index)
        vault = None
        if pii_ref is not None:
            vault = await session.scalar(select(PiiVault).where(PiiVault.id == pii_ref))
        if vault is None:  # vault 없는 계정 → 신설 후 연결
            vault = PiiVault(tenant_id=tenant_id, key_version=1)
            session.add(vault)
            await session.flush()
            user = await session.scalar(select(User).where(User.id == user_id))
            if user is not None:
                user.pii_ref = vault.id
        vault.name_enc = crypto.encrypt(dek, name)
        filled += 1
    return filled


async def main() -> None:
    crypto = get_pii_crypto()
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            tenant_ids = list(await session.scalars(select(Tenant.id)))
            total = 0
            for tenant_id in tenant_ids:
                filled = await _backfill_tenant(session, crypto, tenant_id)
                if filled:
                    print(f"단지 {tenant_id}: {filled}명 이름 채움")
                total += filled
            print(f"\n총 {total}명에 임의 이름 부여 완료(단지 {len(tenant_ids)}곳 점검).")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
