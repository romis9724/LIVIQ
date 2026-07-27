"""seed_inquiries_demo.py — 민원 데모 시드 (가상 입주민 10명 + 민원 30건, 시연용).

첫마을 4단지(dev tenant)에 로그인 가능한 가상 입주민 10명을 만들고, 그들이 접수한 민원
30건을 타임라인(created·assigned·status_changed·comment)까지 채워 넣는다. 30건 중 10건은
실존 시설에 정식 연결(FR-FAC-05 ①)되고, 8건은 담당자 재배정 이력을 갖는다.

계정 생성은 seed_demo._upsert_active_account를 그대로 재사용한다(PII 봉투 암호화·login_id
HMAC·Argon2id — 단일 출처). 이벤트 payload는 app/routers/inquiries.py와 동일한 스키마다.

멱등: 가상 입주민은 login_id 기준 upsert, 민원은 이 입주민들이 author인 기존 행을 지우고
재생성한다(inquiry_events는 FK ON DELETE CASCADE). 다른 사용자가 접수한 민원은 건드리지 않는다.

실행(DATABASE_URL은 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync --env-file .env python scripts/seed_inquiries_demo.py

가상 입주민 로그인: demo-r01@example.com ~ demo-r10@example.com (비밀번호는 seed_demo와 공통)
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import uuid
from pathlib import Path
from typing import NamedTuple

from app.pii import PiiCrypto, get_pii_crypto
from app.routers.auth import _normalize_email
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import (
    Building,
    Code,
    CodeGroup,
    Facility,
    Household,
    Inquiry,
    InquiryEvent,
    User,
    UserRole,
)

# scripts/·scripts/data는 패키지가 아니라 폴더 — 자신의 디렉터리를 sys.path에 넣어
# invocation 방식과 무관하게 임포트되게 한다(seed_facilities_kapt.py와 동일 관례).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.inquiries_demo import INQUIRIES, RESIDENT_NAMES, InquirySeed  # noqa: E402
from seed_demo import (  # noqa: E402
    DEMO_PASSWORD,
    DEV_TENANT_ID,
    _manager_user_id,
    _upsert_active_account,
)

RESIDENT_COUNT = 10
RESIDENT_EMAIL_FORMAT = "demo-r{n:02d}@example.com"
# 담당자 풀이 1명뿐인 DB에서도 재배정 데모가 성립하도록 보강하는 가상 직원.
FALLBACK_STAFF = ("박기사", "STAFF", "demo-staff2@example.com")
ASSIGNABLE_ROLES = ("MANAGER", "STAFF")
INQUIRY_CATEGORY_GROUP = "INQUIRY_CATEGORY"
VALID_STATUSES = frozenset({"received", "assigned", "in_progress", "done"})
VALID_PRIORITIES = frozenset({"urgent", "normal", "low"})

# 타임라인 간격(결정적) — 접수 후 배정, 배정 후 열람(처리중), 답변, 완료 순.
CREATED_HOUR_BASE = 9  # 접수 시각 = 09시 + (index % 9)
ASSIGN_DELAY_HOURS = 6
ACK_DELAY_HOURS = 8
REPLY_DELAY_HOURS = 6
COMPLETE_DELAY_HOURS = 2
REASSIGN_DELAY_DAYS = (1, 2, 3)  # index로 순환


class EventSeed(NamedTuple):
    """타임라인 이벤트 1건(시각 포함)."""

    type: str
    actor_user_id: uuid.UUID | None
    payload: dict[str, object] | None
    at: datetime.datetime


class Timeline(NamedTuple):
    """민원 1건의 확정 시각·담당자·이벤트 열."""

    created_at: datetime.datetime
    updated_at: datetime.datetime
    assignee_user_id: uuid.UUID | None
    events: tuple[EventSeed, ...]


def _validate_seeds() -> None:
    """데이터 상수 사전 검증 — 오타·규약 위반은 DB 접속 전에 중단."""
    for seed in INQUIRIES:
        if seed.status not in VALID_STATUSES:
            raise SystemExit(f"허용되지 않은 status: {seed.status} ({seed.title})")
        if seed.priority not in VALID_PRIORITIES:
            raise SystemExit(f"허용되지 않은 priority: {seed.priority} ({seed.title})")
        if seed.status == "done" and not seed.reply:
            raise SystemExit(f"done 민원에는 담당자 답변(reply)이 필요합니다: {seed.title}")
        if seed.reassign and seed.status == "received":
            raise SystemExit(f"미배정 민원은 재배정할 수 없습니다: {seed.title}")
    if len(RESIDENT_NAMES) != RESIDENT_COUNT:
        raise SystemExit(f"가상 입주민 이름 {len(RESIDENT_NAMES)}개 != {RESIDENT_COUNT}")


async def _pick_households(session: AsyncSession) -> list[uuid.UUID]:
    """동·층·호 정렬 후 균등 간격으로 10세대 추출 — 결정적, 전 동에 고르게 분산."""
    rows = (
        await session.execute(
            select(Household.id)
            .join(Building, Building.id == Household.building_id)
            .where(Household.tenant_id == DEV_TENANT_ID)
            .order_by(Building.name, Household.floor, Household.unit_no)
        )
    ).all()
    if len(rows) < RESIDENT_COUNT:
        raise SystemExit(f"세대가 {len(rows)}개뿐입니다 — 먼저 seed_households_xlsx를 실행하세요.")
    stride = len(rows) // RESIDENT_COUNT
    return [rows[i * stride][0] for i in range(RESIDENT_COUNT)]


async def _user_id_by_email(session: AsyncSession, crypto: PiiCrypto, email: str) -> uuid.UUID:
    """이메일(login_id HMAC)로 활성 사용자 id 조회 — 없으면 중단."""
    user_id = await session.scalar(
        select(User.id).where(
            User.tenant_id == DEV_TENANT_ID,
            User.login_id == crypto.hmac_hash(_normalize_email(email)),
            User.deleted_at.is_(None),
        )
    )
    if user_id is None:
        raise SystemExit(f"계정을 찾을 수 없습니다: {email}")
    return user_id


async def _ensure_residents(
    session: AsyncSession, crypto: PiiCrypto, dek: bytes, household_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """가상 입주민 10명 멱등 upsert — 실 세대에 연결된 활성 RESIDENT 계정."""
    user_ids: list[uuid.UUID] = []
    for index, name in enumerate(RESIDENT_NAMES):
        email = RESIDENT_EMAIL_FORMAT.format(n=index + 1)
        await _upsert_active_account(
            session, crypto, dek, name, "RESIDENT", email, household_ids[index]
        )
        await session.flush()
        user_ids.append(await _user_id_by_email(session, crypto, email))
    return user_ids


async def _assignee_pool(session: AsyncSession, crypto: PiiCrypto, dek: bytes) -> list[uuid.UUID]:
    """배정 가능한 활성 MANAGER·STAFF 목록(id 정렬). 2명 미만이면 가상 직원 1명 보강."""

    async def query() -> list[uuid.UUID]:
        rows = await session.scalars(
            select(User.id)
            .join(UserRole, UserRole.user_id == User.id)
            .where(
                User.tenant_id == DEV_TENANT_ID,
                User.status == "active",
                User.deleted_at.is_(None),
                UserRole.tenant_id == DEV_TENANT_ID,
                UserRole.role.in_(ASSIGNABLE_ROLES),
            )
            .distinct()
            .order_by(User.id)
        )
        return list(rows)

    pool = await query()
    if len(pool) >= 2:
        return pool
    name, role, email = FALLBACK_STAFF
    await _upsert_active_account(session, crypto, dek, name, role, email, None)
    await session.flush()
    pool = await query()
    if len(pool) < 2:
        raise SystemExit("배정 가능한 담당자를 2명 이상 확보하지 못했습니다.")
    return pool


async def _category_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    """INQUIRY_CATEGORY 라벨 → code_id 매핑 — 시드가 쓰는 라벨이 없으면 중단."""
    rows = await session.execute(
        select(Code.label, Code.id)
        .join(CodeGroup, CodeGroup.id == Code.group_id)
        .where(Code.tenant_id == DEV_TENANT_ID, CodeGroup.group_key == INQUIRY_CATEGORY_GROUP)
    )
    mapping = {label: code_id for label, code_id in rows}
    missing = sorted({seed.category for seed in INQUIRIES} - set(mapping))
    if missing:
        raise SystemExit(f"INQUIRY_CATEGORY 코드 없음: {', '.join(missing)}")
    return mapping


async def _facility_ids(session: AsyncSession) -> dict[str, uuid.UUID]:
    """시드가 연결할 시설명 → facility_id — 하나라도 없으면 중단(조용한 skip 금지)."""
    names = sorted({seed.facility for seed in INQUIRIES if seed.facility is not None})
    rows = await session.execute(
        select(Facility.name, Facility.id).where(
            Facility.tenant_id == DEV_TENANT_ID,
            Facility.name.in_(names),
            Facility.deleted_at.is_(None),
        )
    )
    mapping = {name: facility_id for name, facility_id in rows}
    missing = [name for name in names if name not in mapping]
    if missing:
        raise SystemExit(
            "시설을 찾을 수 없습니다(먼저 seed_facilities_kapt를 실행하세요): " + ", ".join(missing)
        )
    return mapping


def _build_timeline(
    seed: InquirySeed,
    index: int,
    *,
    now: datetime.datetime,
    author_user_id: uuid.UUID,
    manager_user_id: uuid.UUID,
    pool: list[uuid.UUID],
) -> Timeline:
    """days_ago 기준으로 이벤트 시각을 순차 증가시켜 타임라인을 구성한다."""
    day = (now - datetime.timedelta(days=seed.days_ago)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    created_at = day + datetime.timedelta(hours=CREATED_HOUR_BASE + index % 9)
    events = [EventSeed("created", author_user_id, None, created_at)]
    if seed.status == "received":
        return Timeline(created_at, created_at, None, tuple(events))

    assignee = pool[index % len(pool)]
    at = created_at + datetime.timedelta(hours=ASSIGN_DELAY_HOURS)
    events.append(EventSeed("assigned", manager_user_id, {"assignee_user_id": str(assignee)}, at))
    if seed.reassign:
        assignee = pool[(index + 1) % len(pool)]
        at += datetime.timedelta(days=REASSIGN_DELAY_DAYS[index % len(REASSIGN_DELAY_DAYS)])
        events.append(
            EventSeed("assigned", manager_user_id, {"assignee_user_id": str(assignee)}, at)
        )
    if seed.status == "assigned":
        return Timeline(created_at, at, assignee, tuple(events))

    at += datetime.timedelta(hours=ACK_DELAY_HOURS)
    events.append(
        EventSeed("status_changed", assignee, {"from": "assigned", "to": "in_progress"}, at)
    )
    if seed.status == "in_progress":
        return Timeline(created_at, at, assignee, tuple(events))

    at += datetime.timedelta(hours=REPLY_DELAY_HOURS)
    events.append(EventSeed("comment", assignee, {"kind": "reply", "body": seed.reply}, at))
    at += datetime.timedelta(hours=COMPLETE_DELAY_HOURS)
    events.append(EventSeed("status_changed", assignee, {"from": "in_progress", "to": "done"}, at))
    return Timeline(created_at, at, assignee, tuple(events))


async def _reset_demo_inquiries(session: AsyncSession, author_ids: list[uuid.UUID]) -> int:
    """가상 입주민이 접수한 기존 민원 삭제(events는 FK CASCADE) — 멱등 재생성 전제."""
    mine = (Inquiry.tenant_id == DEV_TENANT_ID, Inquiry.author_user_id.in_(author_ids))
    removed = await session.scalar(select(func.count()).select_from(Inquiry).where(*mine)) or 0
    await session.execute(delete(Inquiry).where(*mine))
    return removed


async def _create_inquiries(
    session: AsyncSession,
    *,
    now: datetime.datetime,
    resident_ids: list[uuid.UUID],
    household_ids: list[uuid.UUID],
    manager_user_id: uuid.UUID,
    pool: list[uuid.UUID],
    categories: dict[str, uuid.UUID],
    facilities: dict[str, uuid.UUID],
) -> int:
    """민원 30건 + 타임라인 생성 — 반환값은 기록한 이벤트 총수."""
    event_count = 0
    for index, seed in enumerate(INQUIRIES):
        author_index = index % RESIDENT_COUNT
        timeline = _build_timeline(
            seed,
            index,
            now=now,
            author_user_id=resident_ids[author_index],
            manager_user_id=manager_user_id,
            pool=pool,
        )
        inquiry = Inquiry(
            tenant_id=DEV_TENANT_ID,
            household_id=household_ids[author_index],
            author_user_id=resident_ids[author_index],
            category_code_id=categories[seed.category],
            title=seed.title,
            body=seed.body,
            priority=seed.priority,
            status=seed.status,
            assignee_user_id=timeline.assignee_user_id,
            facility_id=None if seed.facility is None else facilities[seed.facility],
            created_at=timeline.created_at,
            updated_at=timeline.updated_at,
        )
        session.add(inquiry)
        await session.flush()
        for event in timeline.events:
            session.add(
                InquiryEvent(
                    tenant_id=DEV_TENANT_ID,
                    inquiry_id=inquiry.id,
                    type=event.type,
                    actor_user_id=event.actor_user_id,
                    payload=event.payload,
                    created_at=event.at,
                )
            )
            event_count += 1
    await session.flush()
    return event_count


async def _report(session: AsyncSession, resident_ids: list[uuid.UUID], events: int) -> None:
    """시드 결과 리포트 + 멱등성 검증(재실행해도 30건 고정)."""
    where = (Inquiry.tenant_id == DEV_TENANT_ID, Inquiry.author_user_id.in_(resident_ids))
    total = await session.scalar(select(func.count()).select_from(Inquiry).where(*where)) or 0
    linked = (
        await session.scalar(
            select(func.count())
            .select_from(Inquiry)
            .where(*where, Inquiry.facility_id.is_not(None))
        )
        or 0
    )
    rows = (
        await session.execute(
            select(Inquiry.status, func.count()).where(*where).group_by(Inquiry.status)
        )
    ).all()
    reassigned = sum(1 for seed in INQUIRIES if seed.reassign)

    print(f"\n가상 입주민: {len(resident_ids)}명 (demo-r01~r10@example.com / {DEMO_PASSWORD})")
    print(f"민원: {total}건 (시설 정식 연결 {linked}건 · 재배정 {reassigned}건)")
    print("  상태 분포:")
    for status, count in sorted(rows):
        print(f"    {status:<12}{count}건")
    print(f"타임라인 이벤트: {events}건")

    assert len(resident_ids) == RESIDENT_COUNT, f"입주민 {len(resident_ids)}명"
    assert total == len(INQUIRIES), f"민원 {total} != {len(INQUIRIES)}"
    assert linked == sum(1 for s in INQUIRIES if s.facility), f"시설 연결 {linked}건"
    print("멱등성 검증 통과 (재실행해도 입주민·민원 개수 고정).")


async def _run() -> None:
    _validate_seeds()
    crypto = get_pii_crypto()
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(
                    t=str(DEV_TENANT_ID)
                )
            )
            dek = await crypto.get_dek(session, DEV_TENANT_ID)
            household_ids = await _pick_households(session)
            resident_ids = await _ensure_residents(session, crypto, dek, household_ids)
            pool = await _assignee_pool(session, crypto, dek)
            manager_user_id = await _manager_user_id(session, crypto) or pool[0]
            categories = await _category_ids(session)
            facilities = await _facility_ids(session)

            removed = await _reset_demo_inquiries(session, resident_ids)
            events = await _create_inquiries(
                session,
                now=datetime.datetime.now(datetime.UTC),
                resident_ids=resident_ids,
                household_ids=household_ids,
                manager_user_id=manager_user_id,
                pool=pool,
                categories=categories,
                facilities=facilities,
            )
            if removed:
                print(f"기존 데모 민원 {removed}건 삭제 후 재생성")
            await _report(session, resident_ids, events)
            print(f"\n단지: {DEV_TENANT_ID}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_run())
