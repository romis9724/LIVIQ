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

공지 샘플 6건(공지사항샘플정리.xlsx) — 전체동 published 게시글로 멱등 upsert(제목 기준).
category는 NOTICE_CATEGORY 시드 코드(시설점검·회의결과·시스템장애·주민행사·방역소독)와 정합.
직접 INSERT라 H8-3 벡터화(ai-worker 인제스트)는 별도 — AI 검색 필요 시 재색인 트리거.
"""

from __future__ import annotations

import asyncio
import datetime
import uuid
from typing import NamedTuple

from app.password import hash_password
from app.pii import PiiCrypto, get_pii_crypto
from app.routers.auth import _normalize_email
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import (
    Building,
    Code,
    CodeGroup,
    Fee,
    Household,
    Notice,
    PiiVault,
    Tenant,
    User,
    UserRole,
)

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


class NoticeSeed(NamedTuple):
    """실단지 공지 샘플(공지사항샘플정리.xlsx) — 게시판 published 데모 데이터."""

    title: str
    category: str  # NOTICE_CATEGORY 코드 라벨(codes_seed와 일치)
    posted: datetime.date  # 발행일 → published_at(자정 UTC)
    event_start: datetime.date | None  # 표시용 행사/작업 기간
    event_end: datetime.date | None
    keywords: str  # 콤마 구분(H8-3 임베딩 텍스트 포함)
    body: str


# 전 공지 target_dong="전체동" → target_buildings=None. category는 DEFAULT_CODE_GROUPS 시드와 일치.
NOTICES: tuple[NoticeSeed, ...] = (
    NoticeSeed(
        title="7월 승강기 정기점검 안내",
        category="시설점검",
        posted=datetime.date(2026, 6, 24),
        event_start=datetime.date(2026, 7, 1),
        event_end=datetime.date(2026, 7, 2),
        keywords="승강기,엘리베이터,정기점검,운행중지,401동,402동,403동,404동,405동,휘트니스",
        body=(
            "승강기 제조 및 관리에 관한 법률 제31조에 따라 승강기 정기 안전점검을 실시합니다. "
            "점검 중 승강기 운행이 중지될 수 있습니다. 7월 1일은 401동부터 404동까지 "
            "09:30~15:30에 점검하며 각 호기당 약 30분이 소요됩니다. 7월 2일은 405동과 휘트니스 "
            "승강기를 09:30~12:00에 점검하며 각 호기당 약 30분이 소요됩니다. 점검업체는 "
            "코리아엘리베이터이며 문의전화는 044-862-8258입니다. 현장 상황에 따라 점검이 "
            "지연되거나 단축될 수 있습니다."
        ),
    ),
    NoticeSeed(
        title="[제21차] 2026년 6월 정기 입주자대표회의 결과 안내",
        category="회의결과",
        posted=datetime.date(2026, 6, 25),
        event_start=datetime.date(2026, 6, 23),
        event_end=datetime.date(2026, 6, 23),
        keywords="입주자대표회의,회의결과,전산계약,재활용업체,공용배관,로비폰,장기수선충당금,폐자전거,홈넷서버",
        body=(
            "2026년 6월 23일 18:30 입주자대표회의실에서 제21차 정기 입주자대표회의를 "
            "개최했습니다. 구성원 4명 중 4명이 참석했고 의결정족수는 3명입니다. 제1안 전산 공급 "
            "계약 만료 건은 최저 금액 122,360원을 제시한 아이창을 선정했습니다. 제2안 재활용업체 "
            "계약 만료 건은 최고 금액 2,704,800원을 제시한 대국환경을 선정했습니다. 제3안 단지 내 "
            "공용배관 청소업체 선정 건은 최저 금액 4,950,000원을 제시한 성혜종합건설설비를 "
            "선정했습니다. 제4안 401동 지상 1층 로비폰 교체를 위한 장기수선충당금 사용계획서 "
            "추인의 건은 의결했습니다. 제5안 단지 내 폐자전거 처리 일정과 집행 권한은 관리주체에 "
            "위임하기로 했습니다. 기타 논의사항으로 방재실 홈넷 서버 고장 수리, 직원 회식비 지원, "
            "경로당 지원금 재논의를 다뤘습니다."
        ),
    ),
    NoticeSeed(
        title="코콤 부분 기능 작동 불능 안내",
        category="시스템장애",
        posted=datetime.date(2026, 6, 25),
        event_start=datetime.date(2026, 6, 23),
        event_end=datetime.date(2026, 6, 23),
        keywords="코콤,월패드,홈넷,서버고장,승강기호출,에너지원격검침,스마트폰제어,기능장애,복구",
        body=(
            "단지 홈넷 하드웨어 서버 고장으로 코콤 월패드의 생활정보 기능이 정상 작동하지 "
            "않습니다. 현재 승강기 호출, 에너지 원격검침, 스마트폰 제어 등의 기능을 이용할 수 "
            "없습니다. 특히 승강기 호출 기능 장애로 불편을 드리고 있으며, 하드웨어를 발주한 "
            "상태입니다. 다음 주 중 수리하여 복구할 예정입니다."
        ),
    ),
    NoticeSeed(
        title="2026 한솔동 주민총회 및 주민자치프로그램 발표회 안내",
        category="주민행사",
        posted=datetime.date(2026, 6, 25),
        event_start=datetime.date(2026, 6, 23),
        event_end=datetime.date(2026, 6, 23),
        keywords="한솔동,주민총회,주민자치프로그램,발표회,사전투표,온라인투표,본투표,정음관",
        body=(
            "2026년 6월 27일 토요일 10:00~12:00 한솔동 정음관 3층 다목적체육관에서 주민총회 및 "
            "주민자치프로그램 발표회를 개최합니다. 대상은 한솔동 주민 누구나입니다. "
            "주민자치프로그램 발표회, 마을계획사업 설명과 주민자치회 활동 보고, "
            "2027년 마을계획사업 및 주민제안사업 투표결과 발표가 진행됩니다. "
            "사전투표는 6월 15일부터 19일까지 10:00~17:00이며, "
            "온라인투표는 6월 8일부터 19일까지 진행됩니다. 본투표는 6월 27일 10:00~11:00에 "
            "진행됩니다. 문의는 한솔동 행정복지센터 044-301-6115 또는 한솔동 주민자치회 "
            "044-868-2450입니다."
        ),
    ),
    NoticeSeed(
        title="단지 내 수목소독 실시 안내",
        category="방역소독",
        posted=datetime.date(2026, 6, 25),
        event_start=datetime.date(2026, 7, 2),
        event_end=datetime.date(2026, 7, 2),
        keywords="수목소독,병해충방제,저층세대,베란다창문,지상주차금지,반려동물산책,우천연기,금강위생",
        body=(
            "아파트 수목의 병해충 방제를 위해 2026년 7월 2일 목요일 09:00~12:00 단지 내 "
            "수목소독을 실시합니다. 1~5층 세대는 베란다 쪽 창문을 닫아주시고, 외부 물건은 실내로 "
            "이동해 주시기 바랍니다. 차량에 약품이 묻을 수 있으므로 지상 주차를 삼가고, 단지 내 "
            "반려동물 산책을 자제해 주십시오. 소독 후에는 수목을 만지지 마시기 바랍니다. 우천 시 "
            "연기될 수 있으며 사용약품은 스미치온, 허스식, 톱신엠입니다. 실시업체는 금강위생입니다."
        ),
    ),
    NoticeSeed(
        title="실내 소독 실시 안내",
        category="방역소독",
        posted=datetime.date(2026, 6, 25),
        event_start=datetime.date(2026, 7, 3),
        event_end=datetime.date(2026, 7, 4),
        keywords="실내소독,정기소독,추가소독,전체동,감염병예방,분무식,독먹이식,도포식,금강위생",
        body=(
            "감염병 예방 및 관리에 관한 법률 제51조에 따라 7월 실내소독을 실시합니다. 정기소독은 "
            "2026년 7월 3일 금요일 09:30~16:30 전체 동을 대상으로 진행하며, 추가소독은 7월 4일 "
            "토요일 09:00~13:00 전체 동을 대상으로 진행합니다. 소독방법은 분무식, 독먹이식, "
            "도포식이며 각 가정에서는 입회하여 충실한 소독이 되도록 협조해 주시기 바랍니다. "
            "실시업체는 금강위생입니다."
        ),
    ),
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


async def _notice_category_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    """NOTICE_CATEGORY 코드 라벨 → code_id 매핑(공지 category_code_id 해석용)."""
    rows = await session.execute(
        select(Code.code, Code.id)
        .join(CodeGroup, CodeGroup.id == Code.group_id)
        .where(Code.tenant_id == DEV_TENANT_ID, CodeGroup.group_key == "NOTICE_CATEGORY")
    )
    return {code: code_id for code, code_id in rows}


async def _manager_user_id(session: AsyncSession, crypto: PiiCrypto) -> uuid.UUID | None:
    """김소장(MANAGER) user id — 공지 published_by(작성자 표시)로 사용."""
    manager_email = next(email for _, role, email in ACTIVE_ACCOUNTS if role == "MANAGER")
    login_id = crypto.hmac_hash(_normalize_email(manager_email))
    return await session.scalar(
        select(User.id).where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id == login_id,
            User.deleted_at.is_(None),
        )
    )


async def _seed_notices(
    session: AsyncSession, category_ids: dict[str, uuid.UUID], published_by: uuid.UUID | None
) -> None:
    """실단지 공지 샘플 멱등 upsert(제목 기준) — 전체동 published 게시글."""
    for seed in NOTICES:
        exists = await session.scalar(
            select(Notice.id).where(Notice.tenant_id == DEV_TENANT_ID, Notice.title == seed.title)
        )
        if exists is not None:
            continue
        published_at = datetime.datetime.combine(
            seed.posted, datetime.time.min, tzinfo=datetime.UTC
        )
        session.add(
            Notice(
                tenant_id=DEV_TENANT_ID,
                title=seed.title,
                body=seed.body,
                status="published",
                category_code_id=category_ids.get(seed.category),
                event_start=seed.event_start,
                event_end=seed.event_end,
                target_buildings=None,  # 전체동
                keywords=seed.keywords,
                pinned=False,
                published_at=published_at,
                published_by=published_by,
                audience="ALL",
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

    seeded_titles = [n.title for n in NOTICES]
    notice_count = await session.scalar(
        select(func.count())
        .select_from(Notice)
        .where(Notice.tenant_id == DEV_TENANT_ID, Notice.title.in_(seeded_titles))
    )
    notice_count = notice_count or 0
    print(f"공지 샘플(published): {notice_count}건")

    # 멱등성: 재실행해도 아래 개수는 고정이어야 한다(중복 생성 없음).
    expected_active = len(ACTIVE_ACCOUNTS)
    assert active_count == expected_active, f"활성 계정 {active_count} != {expected_active}"
    assert roster_count >= len(ROSTER_PEOPLE), f"명부 {roster_count} < {len(ROSTER_PEOPLE)}"
    assert notice_count == len(NOTICES), f"공지 {notice_count} != {len(NOTICES)}"
    print("멱등성 검증 통과 (활성 계정·명부·공지 개수 고정).")


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

            category_ids = await _notice_category_ids(session)
            published_by = await _manager_user_id(session, crypto)
            await _seed_notices(session, category_ids, published_by)

            await _report(session, crypto)
            print(f"\n단지: {DEV_TENANT_ID}  ·  가입 링크: /signup?t={DEV_TENANT_ID}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
