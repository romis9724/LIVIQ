"""seed_demo.py — 데모 계정 시드 (수동 통합테스트·데모 시연용, H7-4).

역할 분리 계정으로 로그인·회원가입 여정을 사람이 직접 탈 수 있게 dev 단지에 계정과
명부(pre_registered)를 멱등 upsert 한다. 파괴적 삭제 없음 — 기존 dev 데이터(문서·관리비·
시설)는 불변, login_id(이메일 HMAC)/명부 해시 기준으로 재실행해도 중복이 생기지 않는다.

인증은 자체 이메일+비밀번호(ADR-0014) — login_id는 이메일 keyed HMAC, 평문은 pii_vault
암호화. 여기서는 검증·초대 절차 없이 email_verified_at·password_hash를 직접 심어 바로
로그인 가능한 활성 계정을 만든다(데모 편의 — 운영 경로는 signup/invite 라우터).

실행(seed 관행 — 루트 .env 로드):

    cd apps/api
    uv run --no-sync --env-file ../../.env python scripts/seed_demo.py

활성 계정 (비밀번호 공통: liviq-demo-1234!):
    | 이름   | 역할     | 이메일(로그인 ID)         |
    |--------|----------|---------------------------|
    | 김소장 | MANAGER  | demo-manager@example.com  |
    | 박직원 | STAFF    | demo-staff@example.com    |
    | 최주민 | RESIDENT | demo-resident@example.com |  (관리비가 있는 세대에 배정)

H7-2 역할 축소로 FACILITY 계정은 제거했다(RESIDENT·MANAGER·STAFF·SYS_ADMIN만 유효).

명부(pre_registered) 2명 — 신규 가입 여정 테스트용. 계정이 아직 없으므로 dev 단지 가입 링크로
계정을 만든 뒤 온보딩 폼에서 아래 인적사항을 **그대로** 입력하면 명부와 자동 대조
(name_hash+birth_date_hash+household)되어 pending 승격된다. 동·층·호는 실명부(401~405동,
seed_households_xlsx)의 실재 세대에 맞춘다:
    | 이름   | 생년월일    | 동   | 층 | 호  |
    |--------|-------------|------|----|-----|
    | 정가입 | 1992-03-15  | 401  | 3  | 301 |
    | 한신규 | 1988-11-02  | 401  | 4  | 402 |

dev 단지 가입 링크(입주민 웹):
    /signup?t=11111111-1111-1111-1111-111111111111
"""

from __future__ import annotations

import asyncio
import datetime
import uuid

from app.password import hash_password
from app.pii import PiiCrypto, get_pii_crypto
from app.routers.auth import _normalize_email
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import Building, Fee, Household, PiiVault, Tenant, User, UserRole

DEV_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEMO_PASSWORD = "liviq-demo-1234!"  # 활성 계정 공통 비밀번호(데모 편의 — 운영은 재설정 유도)
# 실명부(seed_households_xlsx의 401~405동) 중 하나 — 데모 명부·온보딩 대조가 실단지 세대와 정합.
BUILDING_NAME = "401"

# 활성 계정: (이름, 역할, 이메일). login_id = 이메일 keyed HMAC.
ACTIVE_ACCOUNTS = (
    ("김소장", "MANAGER", "demo-manager@example.com"),
    ("박직원", "STAFF", "demo-staff@example.com"),
    ("최주민", "RESIDENT", "demo-resident@example.com"),
)

# 구 mock IdP sub login_id(이메일 해시가 아닌 평문) — 소프트 정리 대상(H7-4). 참조 데이터 없음.
LEGACY_SUB_LOGIN_IDS = ("demo-manager", "demo-staff", "demo-facility", "demo-resident")

# 명부 사전등록: (이름, 생년월일, 층, 호) — 동은 BUILDING_NAME. 수동 가입 시 그대로 입력.
ROSTER_PEOPLE = (
    ("정가입", datetime.date(1992, 3, 15), 3, 301),
    ("한신규", datetime.date(1988, 11, 2), 4, 402),
)


async def _require_tenant(session: AsyncSession) -> None:
    """dev 단지 존재 확인 — 없으면 중단(먼저 dev 시드/마이그레이션을 실행하세요)."""
    if await session.get(Tenant, DEV_TENANT_ID) is None:
        raise SystemExit(f"dev 단지({DEV_TENANT_ID})가 없습니다 — 먼저 dev 시드를 실행하세요.")


async def _ensure_building(session: AsyncSession) -> uuid.UUID:
    """실명부 동 '401' 확보 — seed_households_xlsx가 이미 만들면 재사용, 없으면 생성(멱등)."""
    building_id = await session.scalar(
        select(Building.id).where(
            Building.tenant_id == DEV_TENANT_ID, Building.name == BUILDING_NAME
        )
    )
    if building_id is not None:
        return building_id
    building = Building(tenant_id=DEV_TENANT_ID, name=BUILDING_NAME, floors=25)
    session.add(building)
    await session.flush()
    return building.id


async def _ensure_household(
    session: AsyncSession, building_id: uuid.UUID, floor: int, unit_no: int
) -> uuid.UUID:
    """(building, floor, unit_no) 세대 확보 — 없으면 생성(멱등)."""
    household_id = await session.scalar(
        select(Household.id).where(
            Household.tenant_id == DEV_TENANT_ID,
            Household.building_id == building_id,
            Household.floor == floor,
            Household.unit_no == unit_no,
        )
    )
    if household_id is not None:
        return household_id
    household = Household(
        tenant_id=DEV_TENANT_ID,
        building_id=building_id,
        floor=floor,
        unit_no=unit_no,
        status="active",
    )
    session.add(household)
    await session.flush()
    return household.id


async def _fee_household_id(session: AsyncSession) -> uuid.UUID | None:
    """관리비가 있는 세대 하나(최주민 배정용) — 화면이 채워지도록."""
    return await session.scalar(
        select(Fee.household_id).where(Fee.tenant_id == DEV_TENANT_ID).limit(1)
    )


async def _soft_delete_legacy(session: AsyncSession, now: datetime.datetime) -> None:
    """구 mock IdP sub 계정 소프트 정리 — 새 이메일 계정은 login_id가 달라 upsert가 못 찾는다."""
    await session.execute(
        update(User)
        .where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id.in_(LEGACY_SUB_LOGIN_IDS),
            User.deleted_at.is_(None),
        )
        .values(deleted_at=now)
    )


async def _upsert_active_account(
    session: AsyncSession,
    crypto: PiiCrypto,
    dek: bytes,
    name: str,
    role: str,
    email: str,
    household_id: uuid.UUID | None,
) -> None:
    """활성 계정 멱등 upsert(login_id=이메일 HMAC 기준) + 역할 부여. 검증·비번을 직접 심는다."""
    login_id = crypto.hmac_hash(_normalize_email(email))
    now = datetime.datetime.now(datetime.UTC)
    user = await session.scalar(
        select(User).where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id == login_id,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        vault = PiiVault(
            tenant_id=DEV_TENANT_ID,
            email_enc=crypto.encrypt(dek, _normalize_email(email)),
            name_enc=crypto.encrypt(dek, name),
            name_hash=crypto.hmac_hash(name),
            key_version=1,
        )
        session.add(vault)
        await session.flush()
        user = User(
            tenant_id=DEV_TENANT_ID,
            household_id=household_id,
            login_id=login_id,
            password_hash=hash_password(DEMO_PASSWORD),
            status="active",
            roster_matched=household_id is not None,
            email_verified_at=now,
            pii_ref=vault.id,
        )
        session.add(user)
        await session.flush()
    else:
        # 재실행 — 문서화된 비밀번호·검증·활성 상태를 보장(중복 행 생성 없음).
        user.status = "active"
        user.password_hash = hash_password(DEMO_PASSWORD)
        user.email_verified_at = user.email_verified_at or now
        if household_id is not None:
            user.household_id = household_id

    exists = await session.scalar(
        select(UserRole.id).where(
            UserRole.tenant_id == DEV_TENANT_ID,
            UserRole.user_id == user.id,
            UserRole.role == role,
        )
    )
    if exists is None:
        session.add(UserRole(tenant_id=DEV_TENANT_ID, user_id=user.id, role=role))


async def _upsert_roster_person(
    session: AsyncSession,
    crypto: PiiCrypto,
    dek: bytes,
    building_id: uuid.UUID,
    name: str,
    birth: datetime.date,
    floor: int,
    unit_no: int,
) -> None:
    """명부 사전등록 멱등 upsert — roster.py 와 동일한 해시·암호화 경로."""
    household_id = await _ensure_household(session, building_id, floor, unit_no)
    name_hash = crypto.hmac_hash(name)
    birth_hash = crypto.hmac_hash(birth.isoformat())
    existing = await session.scalar(
        select(User.id)
        .join(PiiVault, PiiVault.id == User.pii_ref)
        .where(
            User.tenant_id == DEV_TENANT_ID,
            User.status == "pre_registered",
            User.household_id == household_id,
            PiiVault.name_hash == name_hash,
            PiiVault.birth_date_hash == birth_hash,
        )
    )
    if existing is not None:
        return
    vault = PiiVault(
        tenant_id=DEV_TENANT_ID,
        name_enc=crypto.encrypt(dek, name),
        birth_date_enc=crypto.encrypt(dek, birth.isoformat()),
        name_hash=name_hash,
        birth_date_hash=birth_hash,
        key_version=1,
    )
    session.add(vault)
    await session.flush()
    session.add(
        User(
            tenant_id=DEV_TENANT_ID,
            household_id=household_id,
            login_id=None,
            status="pre_registered",
            roster_matched=False,
            pii_ref=vault.id,
        )
    )


async def _report(session: AsyncSession, crypto: PiiCrypto) -> None:
    """시드 결과 표 출력 + 멱등성 검증(재실행해도 개수 불변)."""
    by_login: dict[str, tuple[str, str]] = {
        crypto.hmac_hash(_normalize_email(email)): (email, role)
        for name, role, email in ACTIVE_ACCOUNTS
    }
    rows = await session.execute(
        select(User.login_id, User.status)
        .where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id.in_(list(by_login)),
            User.deleted_at.is_(None),
        )
        .order_by(User.login_id)
    )
    print("\n활성 계정 (비밀번호: liviq-demo-1234!):")
    print(f"  {'이메일':<28}{'역할':<10}상태")
    active_count = 0
    for login_id, status in rows:
        email, role = by_login[login_id]
        print(f"  {email:<28}{role:<10}{status}")
        active_count += 1

    roster = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == DEV_TENANT_ID, User.status == "pre_registered")
    )
    roster_count = roster or 0
    print(f"\n명부(pre_registered): {roster_count}명")

    # 멱등성: 재실행해도 아래 개수는 고정이어야 한다(중복 생성 없음).
    expected_active = len(ACTIVE_ACCOUNTS)
    assert active_count == expected_active, f"활성 계정 {active_count} != {expected_active}"
    assert roster_count >= len(ROSTER_PEOPLE), f"명부 {roster_count} < {len(ROSTER_PEOPLE)}"
    print("멱등성 검증 통과 (활성 계정·명부 개수 고정).")


async def main() -> None:
    crypto = get_pii_crypto()
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            # 소유자(liviq) 접속은 RLS를 우회하지만 get_dek 계약에 맞춰 컨텍스트를 설정한다.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(
                    t=str(DEV_TENANT_ID)
                )
            )
            await _require_tenant(session)
            building_id = await _ensure_building(session)
            dek = await crypto.get_dek(session, DEV_TENANT_ID)

            await _soft_delete_legacy(session, datetime.datetime.now(datetime.UTC))
            fee_household = await _fee_household_id(session)
            for name, role, email in ACTIVE_ACCOUNTS:
                household = fee_household if role == "RESIDENT" else None
                await _upsert_active_account(session, crypto, dek, name, role, email, household)

            for name, birth, floor, unit_no in ROSTER_PEOPLE:
                await _upsert_roster_person(
                    session, crypto, dek, building_id, name, birth, floor, unit_no
                )

            await _report(session, crypto)
            print(f"\n단지: {DEV_TENANT_ID}  ·  가입 링크: /signup?t={DEV_TENANT_ID}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
