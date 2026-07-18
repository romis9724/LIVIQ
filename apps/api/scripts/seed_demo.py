"""seed_demo.py — 데모/부트스트랩 시드 (수동 통합테스트·최초 관리소장 부트스트랩용).

역할 분리 계정으로 로그인·회원가입 여정을 사람이 직접 탈 수 있게 dev 단지에 계정과
명부(pre_registered)를 멱등 upsert 한다. 파괴적 삭제 없음 — 기존 dev 데이터(문서·관리비·
시설)는 불변, login_id/명부 해시 기준으로 재실행해도 중복이 생기지 않는다.

실행:
    # env 로드(DATABASE_URL·PII_MASTER_KEY 필요) 후
    uv run --no-sync python scripts/seed_demo.py

시드되는 활성 계정 (login_id = mock IdP가 반환하는 google sub):
    | 이름   | 역할     | login_id(sub)   | 상태   |
    |--------|----------|-----------------|--------|
    | 김소장 | MANAGER  | demo-manager    | active |
    | 박직원 | STAFF    | demo-staff      | active |
    | 이기사 | FACILITY | demo-facility   | active |
    | 최주민 | RESIDENT | demo-resident   | active |  (관리비가 있는 세대에 배정)

명부(pre_registered) 2명 — 신규 가입 여정 테스트용. 계정이 아직 없으므로 mock IdP에서
신규 sub(demo-signup-1·demo-signup-2)로 로그인 → 온보딩 폼에서 아래 인적사항을 **그대로**
입력해야 명부와 자동 대조(name_hash+birth_date_hash+household)되어 pending 승격된다:
    | 이름   | 생년월일    | 동   | 층 | 호  |
    |--------|-------------|------|----|-----|
    | 정가입 | 1992-03-15  | 101  | 3  | 301 |
    | 한신규 | 1988-11-02  | 101  | 4  | 402 |

단지 초대코드: HANGANG (온보딩 폼의 "단지 초대코드"에 입력). E2E 단지가 LIVIQ1을 쓰므로
전역 유니크 충돌을 피해 dev 단지는 HANGANG 을 사용한다.

mock IdP 계정 선택 화면(tests/e2e/mock-idp.mjs): 환경변수 MOCK_IDP_INTERACTIVE=1 로 기동하면
/authorize 가 즉시 302 대신 위 6개 sub(4 활성 + 2 신규가입) + 직접 입력이 있는 구글식 계정
선택 페이지를 렌더한다. 미설정 시 기존 즉시 로그인(E2E 무회귀).
"""

from __future__ import annotations

import asyncio
import datetime
import os
import uuid

from app.pii import PiiCrypto
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import Building, Fee, Household, PiiVault, Tenant, User, UserRole

# --- 상수 (mock-idp.mjs ACCOUNTS 와 일치시켜야 한다) ---------------------------------

DEV_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
INVITE_CODE = "HANGANG"  # E2E(LIVIQ1)와 전역 유니크 충돌 회피
# 입주민 웹 가입 폼의 동 옵션(DONG_OPTIONS)과 일치해야 세대 조회가 성공한다.
BUILDING_NAME = "101"

# 활성 계정: (이름, 역할, login_id/sub)
ACTIVE_ACCOUNTS = (
    ("김소장", "MANAGER", "demo-manager"),
    ("박직원", "STAFF", "demo-staff"),
    ("이기사", "FACILITY", "demo-facility"),
    ("최주민", "RESIDENT", "demo-resident"),
)

# 명부 사전등록: (이름, 생년월일, 층, 호) — 동은 BUILDING_NAME. 수동 가입 시 그대로 입력.
ROSTER_PEOPLE = (
    ("정가입", datetime.date(1992, 3, 15), 3, 301),
    ("한신규", datetime.date(1988, 11, 2), 4, 402),
)


async def _ensure_tenant_invite_code(session: AsyncSession) -> None:
    """dev 단지의 settings['invite_code']를 확인·설정(없을 때만 HANGANG, 기존값 보존)."""
    tenant = await session.get(Tenant, DEV_TENANT_ID)
    if tenant is None:
        raise SystemExit(f"dev 단지({DEV_TENANT_ID})가 없습니다 — 먼저 dev 시드를 실행하세요.")
    settings = dict(tenant.settings or {})
    if not settings.get("invite_code"):
        settings["invite_code"] = INVITE_CODE
        tenant.settings = settings


async def _ensure_building(session: AsyncSession) -> uuid.UUID:
    """웹 폼 동 옵션과 일치하는 building '101' 확보. 기존 '101동'이 있으면 개명(멱등)."""
    building_id = await session.scalar(
        select(Building.id).where(
            Building.tenant_id == DEV_TENANT_ID, Building.name == BUILDING_NAME
        )
    )
    if building_id is not None:
        return building_id
    legacy = await session.scalar(
        select(Building).where(Building.tenant_id == DEV_TENANT_ID, Building.name == "101동")
    )
    if legacy is not None:
        legacy.name = BUILDING_NAME  # 웹 가입 폼(dong="101")과 정합 — FK는 id 기준이라 안전
        return legacy.id
    building = Building(tenant_id=DEV_TENANT_ID, name=BUILDING_NAME, floors=15)
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


async def _upsert_active_account(
    session: AsyncSession,
    crypto: PiiCrypto,
    dek: bytes,
    name: str,
    role: str,
    sub: str,
    household_id: uuid.UUID | None,
) -> None:
    """활성 계정 멱등 upsert(login_id 기준) + 역할 부여."""
    user = await session.scalar(
        select(User).where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id == sub,
            User.deleted_at.is_(None),
        )
    )
    if user is None:
        vault = PiiVault(
            tenant_id=DEV_TENANT_ID,
            name_enc=crypto.encrypt(dek, name),
            name_hash=crypto.hmac_hash(name),
            key_version=1,
        )
        session.add(vault)
        await session.flush()
        user = User(
            tenant_id=DEV_TENANT_ID,
            household_id=household_id,
            login_id=sub,
            status="active",
            roster_matched=household_id is not None,
            pii_ref=vault.id,
        )
        session.add(user)
        await session.flush()
    else:
        user.status = "active"
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


async def _report(session: AsyncSession) -> None:
    """시드 결과 표 출력 + 멱등성 검증(재실행해도 개수 불변)."""
    rows = await session.execute(
        select(User.login_id, User.status, UserRole.role)
        .outerjoin(UserRole, UserRole.user_id == User.id)
        .where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id.in_([sub for _, _, sub in ACTIVE_ACCOUNTS]),
        )
        .order_by(User.login_id)
    )
    print("\n활성 계정:")
    print(f"  {'login_id':<16}{'상태':<8}역할")
    for login_id, status, role in rows:
        print(f"  {login_id:<16}{status:<8}{role}")

    roster = await session.scalars(
        select(User.id).where(User.tenant_id == DEV_TENANT_ID, User.status == "pre_registered")
    )
    roster_count = len(list(roster))
    active_count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id.in_([sub for _, _, sub in ACTIVE_ACCOUNTS]),
        )
    )
    print(f"\n명부(pre_registered): {roster_count}명")
    # 멱등성: 재실행해도 아래 개수는 고정이어야 한다(중복 생성 없음).
    expected_active = len(ACTIVE_ACCOUNTS)
    assert active_count == expected_active, f"활성 계정 {active_count} != {expected_active}"
    assert roster_count >= len(ROSTER_PEOPLE), f"명부 {roster_count} < {len(ROSTER_PEOPLE)}"
    print("멱등성 검증 통과 (활성 계정·명부 개수 고정).")


async def main() -> None:
    master_key = os.environ.get("PII_MASTER_KEY")
    if not master_key:
        raise SystemExit("PII_MASTER_KEY 환경변수가 필요합니다.")
    crypto = PiiCrypto(master_key)

    factory = create_session_factory(create_engine())
    async with factory() as session, session.begin():
        # 소유자(liviq) 접속은 RLS를 우회하지만, get_dek·격리 경로 계약에 맞춰 컨텍스트를 설정한다.
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(DEV_TENANT_ID))
        )
        await _ensure_tenant_invite_code(session)
        building_id = await _ensure_building(session)
        dek = await crypto.get_dek(session, DEV_TENANT_ID)

        fee_household = await _fee_household_id(session)
        for name, role, sub in ACTIVE_ACCOUNTS:
            household = fee_household if role == "RESIDENT" else None
            await _upsert_active_account(session, crypto, dek, name, role, sub, household)

        for name, birth, floor, unit_no in ROSTER_PEOPLE:
            await _upsert_roster_person(
                session, crypto, dek, building_id, name, birth, floor, unit_no
            )

        await _report(session)
        print(f"\n초대코드: {INVITE_CODE}  ·  단지: {DEV_TENANT_ID}")


if __name__ == "__main__":
    asyncio.run(main())
