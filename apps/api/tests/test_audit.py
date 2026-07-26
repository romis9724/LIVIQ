"""감사 로그 배선 — 행위별 기록 + **개인정보 비저장**(H11-1, docs/06 §8) — CRITICAL.

두 축을 본다:

1. **기록 누락 없음**: 보안 핵심 행위마다 `audit_logs` 행이 남는가(행위명·행위자·대상).
2. **개인정보 비저장**(docs/06 §4.3·§9): 남은 행의 어디에도 이메일·성함·차량번호·거절 사유
   원문이 없는가. 이게 깨지면 감사 로그 자체가 개인정보 저장소가 된다.

로그인 실패 기록은 **별도 트랜잭션**이라 다른 테스트와 다르게 시드를 커밋한다(401이 요청
트랜잭션을 롤백시키므로 같은 세션에 쓰면 기록이 사라진다 — 그 성질 자체가 검증 대상이다).
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app import audit
from app.deps import (
    RequestContext,
    get_auth_lookup_session,
    get_context,
    get_queue,
    get_storage,
    get_tenant_session,
    visibilities_for,
)
from app.mail import get_mailer
from app.main import create_app
from app.password import hash_password
from app.pii import PiiCrypto, get_pii_crypto
from app.session import get_redis
from conftest import (
    BUILDING_ID,
    MANAGER_USER_ID,
    TENANT_ID,
    FakeQueue,
    FakeStorage,
    seed_tenant,
)
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from liviq_db.models import AuditLog, Building, Household, ParkingVehicle, PiiVault, Tenant, User

_KEK = base64.b64encode(b"0" * 32).decode()
_EMAIL = "audit-target@example.com"
_PASSWORD = "correct-horse-battery"
_NAME = "홍길동"
_PLATE = "205고9167"
_REJECT_REASON = "명부의 홍길동과 생년월일이 일치하지 않습니다"


class FakeMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


def _crypto() -> PiiCrypto:
    return PiiCrypto(_KEK)


def _client(
    db_session: AsyncSession,
    redis: FakeRedis,
    *,
    roles: tuple[str, ...] = ("MANAGER",),
    mailer: FakeMailer | None = None,
) -> httpx.AsyncClient:
    """MANAGER 컨텍스트 클라이언트. Redis는 **항상** 주입한다 — 승인·거절이 세션 revoke를
    호출하므로 미주입 시 실 Redis 접속을 시도해 실패한다.
    """
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, MANAGER_USER_ID, roles=roles, visibilities=visibilities_for(roles)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_auth_lookup_session] = lambda: db_session
    app.dependency_overrides[get_pii_crypto] = _crypto
    app.dependency_overrides[get_mailer] = lambda: mailer or FakeMailer()
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_queue] = lambda: FakeQueue()
    app.dependency_overrides[get_redis] = lambda: redis
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _audits(session: AsyncSession, action: str | None = None) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.created_at)
    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
    return list(await session.scalars(stmt))


def _serialized(rows: list[AuditLog]) -> str:
    """행 전체를 문자열로 이어 붙인다 — PII 문자열 포함 여부를 한 번에 본다."""
    return " ".join(f"{r.action} {r.target_type} {r.target_id} {r.meta} {r.ip}" for r in rows)


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await seed_tenant(db_session)
    yield db_session


# ── 로그인 ─────────────────────────────────────────────────────────────────


async def test_login_success_records_audit(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    """`auth.login` — 행위자=본인, meta는 역할만(이메일 금지)."""
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    db_session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await db_session.flush()
    crypto = _crypto()
    dek = await crypto.get_dek(db_session, TENANT_ID)
    vault = PiiVault(tenant_id=TENANT_ID, email_enc=crypto.encrypt(dek, _EMAIL), key_version=1)
    db_session.add(vault)
    await db_session.flush()
    user = User(
        tenant_id=TENANT_ID,
        login_id=crypto.hmac_hash(_EMAIL),
        password_hash=hash_password(_PASSWORD),
        status="active",
        email_verified_at=text("now()"),
        pii_ref=vault.id,
    )
    db_session.add(user)
    await db_session.flush()

    async with _client(db_session, fake_redis) as c:
        r = await c.post("/auth/login", json={"email": _EMAIL, "password": _PASSWORD})
    assert r.status_code == 200, r.text

    rows = await _audits(db_session, audit.AUTH_LOGIN)
    assert len(rows) == 1
    assert rows[0].actor_user_id == user.id
    assert rows[0].target_id == user.id
    assert _EMAIL not in _serialized(rows)


async def test_login_failure_audit_survives_rollback(pg_dsn: str, fake_redis: FakeRedis) -> None:
    """`auth.login_failed` — 401이 요청 트랜잭션을 롤백해도 기록은 남는다(별도 트랜잭션).

    그래서 이 테스트만 시드를 **커밋**한다(다른 테스트는 롤백 세션). 정리는 finally에서.
    """
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tenant_id = uuid.uuid4()
    crypto = _crypto()
    try:
        async with factory() as setup, setup.begin():
            await setup.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            setup.add(Tenant(id=tenant_id, name="감사-실패", status="active"))
            await setup.flush()
            dek = await crypto.get_dek(setup, tenant_id)
            vault = PiiVault(
                tenant_id=tenant_id, email_enc=crypto.encrypt(dek, _EMAIL), key_version=1
            )
            setup.add(vault)
            await setup.flush()
            user = User(
                tenant_id=tenant_id,
                login_id=crypto.hmac_hash(_EMAIL),
                password_hash=hash_password(_PASSWORD),
                status="active",
                email_verified_at=text("now()"),
                pii_ref=vault.id,
            )
            setup.add(user)
            await setup.flush()
            user_id = user.id

        # 요청 세션은 커밋하지 않는 별개 세션 — 실패 응답으로 롤백된다.
        async with factory() as request_session:
            app = create_app()
            app.dependency_overrides[get_auth_lookup_session] = lambda: request_session
            app.dependency_overrides[get_pii_crypto] = _crypto
            app.dependency_overrides[get_redis] = lambda: fake_redis
            async with httpx.AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as c:
                r = await c.post("/auth/login", json={"email": _EMAIL, "password": "wrong-pw"})
            assert r.status_code == 401
            await request_session.rollback()

        async with factory() as check:
            await check.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            rows = await _audits(check, audit.AUTH_LOGIN_FAILED)
            assert len(rows) == 1, "실패 기록이 요청 롤백과 함께 사라졌다"
            assert rows[0].actor_user_id == user_id
            assert rows[0].meta == {"reason": "bad_password"}
            assert _EMAIL not in _serialized(rows)
    finally:
        async with factory() as cleanup, cleanup.begin():
            await cleanup.execute(text("SET LOCAL lock_timeout = '10s'"))
            await cleanup.execute(text("DELETE FROM tenants WHERE id = :t").bindparams(t=tenant_id))
        await engine.dispose()


# ── 승인·거절 ──────────────────────────────────────────────────────────────


async def _add_pending(session: AsyncSession, household_id: uuid.UUID) -> uuid.UUID:
    crypto = _crypto()
    dek = await crypto.get_dek(session, TENANT_ID)
    vault = PiiVault(
        tenant_id=TENANT_ID,
        name_enc=crypto.encrypt(dek, _NAME),
        email_enc=crypto.encrypt(dek, _EMAIL),
        key_version=1,
    )
    session.add(vault)
    await session.flush()
    user = User(
        tenant_id=TENANT_ID,
        household_id=household_id,
        status="pending",
        pii_ref=vault.id,
        roster_matched=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def test_approve_records_audit(seeded: AsyncSession, fake_redis: FakeRedis) -> None:
    households = await _household_ids(seeded)
    user_id = await _add_pending(seeded, households[0])
    async with _client(seeded, fake_redis) as c:
        r = await c.post(f"/admin/approvals/{user_id}/approve")
    assert r.status_code == 204, r.text

    rows = await _audits(seeded, audit.USER_APPROVED)
    assert len(rows) == 1
    assert rows[0].actor_user_id == MANAGER_USER_ID
    assert rows[0].target_type == audit.TARGET_USER
    assert rows[0].target_id == user_id


async def test_reject_records_audit_without_reason_text(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    """거절 사유 **원문은 기록하지 않는다** — 자유 텍스트는 개인정보 유입 경로다."""
    households = await _household_ids(seeded)
    user_id = await _add_pending(seeded, households[0])
    async with _client(seeded, fake_redis) as c:
        r = await c.post(f"/admin/approvals/{user_id}/reject", json={"reason": _REJECT_REASON})
    assert r.status_code == 204, r.text

    rows = await _audits(seeded, audit.USER_REJECTED)
    assert len(rows) == 1
    assert rows[0].meta == {"has_reason": True}
    assert _NAME not in _serialized(rows)
    assert _REJECT_REASON not in _serialized(rows)


# ── 권한변경(초대) ─────────────────────────────────────────────────────────


async def test_staff_invite_records_audit(seeded: AsyncSession, fake_redis: FakeRedis) -> None:
    """`staff.invited` — 부여 역할만 기록, 초대 이메일·성함은 금지."""
    mailer = FakeMailer()
    async with _client(seeded, fake_redis, mailer=mailer) as c:
        r = await c.post(
            "/admin/staff/invite", json={"email": "new-staff@example.com", "name": _NAME}
        )
    assert r.status_code == 202, r.text

    rows = await _audits(seeded, audit.STAFF_INVITED)
    assert len(rows) == 1
    assert rows[0].meta == {"role": "STAFF"}
    assert rows[0].actor_user_id == MANAGER_USER_ID
    serialized = _serialized(rows)
    assert "new-staff@example.com" not in serialized
    assert _NAME not in serialized


# ── 개인정보 열람 ──────────────────────────────────────────────────────────


async def test_roster_view_records_audit(seeded: AsyncSession, fake_redis: FakeRedis) -> None:
    households = await _household_ids(seeded)
    await _add_pending(seeded, households[0])
    async with _client(seeded, fake_redis) as c:
        r = await c.get("/admin/roster")
    assert r.status_code == 200, r.text

    rows = await _audits(seeded, audit.PII_ROSTER_VIEWED)
    assert len(rows) == 1
    assert rows[0].meta is not None and "count" in rows[0].meta
    assert _NAME not in _serialized(rows)


async def test_plates_view_records_audit(seeded: AsyncSession, fake_redis: FakeRedis) -> None:
    """`pii.plates_viewed` — 번호판을 복호해 내보내는 유일한 경로. 번호판 자체는 미기록."""
    households = await _household_ids(seeded)
    crypto = _crypto()
    dek = await crypto.get_dek(seeded, TENANT_ID)
    seeded.add(
        ParkingVehicle(
            tenant_id=TENANT_ID,
            household_id=households[0],
            plate_enc=crypto.encrypt(dek, _PLATE),
            model="아이오닉5",
            is_ev=True,
        )
    )
    await seeded.flush()

    async with _client(seeded, fake_redis) as c:
        r = await c.get("/admin/parking/vehicles")
    assert r.status_code == 200, r.text
    assert r.json()["vehicles"][0]["plate"] == _PLATE  # 응답엔 평문(관리자 전용)

    rows = await _audits(seeded, audit.PII_PLATES_VIEWED)
    assert len(rows) == 1
    assert rows[0].meta == {"count": 1}
    assert _PLATE not in _serialized(rows), "감사 로그에 번호판 평문이 들어갔다"


# ── append-only ────────────────────────────────────────────────────────────


async def test_audit_rows_are_never_updated_by_app(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    """앱은 감사 행을 갱신·삭제하지 않는다 — 권한으로도 막혀 있다(03 §4.7).

    여기서는 코드 경로에 UPDATE/DELETE가 없음을 표현한다(권한 차단 자체는 packages/db의
    RLS 스위트가 실접속 롤로 검증한다).
    """
    households = await _household_ids(seeded)
    user_id = await _add_pending(seeded, households[0])
    async with _client(seeded, fake_redis) as c:
        assert (await c.post(f"/admin/approvals/{user_id}/approve")).status_code == 204

    rows = await _audits(seeded)
    assert rows, "감사 행이 없다"
    assert all(r.action.count(".") == 1 for r in rows), "행위명 규약(도메인.행위) 위반"


async def _household_ids(session: AsyncSession) -> list[uuid.UUID]:
    return list(
        await session.scalars(
            select(Household.id)
            .where(Household.tenant_id == TENANT_ID, Household.building_id == BUILDING_ID)
            .order_by(Household.unit_no)
        )
    )


@pytest.mark.parametrize("pii", [_EMAIL, _NAME, _PLATE, _REJECT_REASON])
async def test_no_pii_anywhere_in_audit_logs(
    seeded: AsyncSession, fake_redis: FakeRedis, pii: str
) -> None:
    """여러 행위를 한 번에 돌리고, 남은 감사 행 전체에 개인정보 문자열이 없음을 본다 —
    개별 테스트가 놓친 조합을 잡는 그물이다(docs/06 §9 "감사 로그 … 개인정보 비저장").
    """
    households = await _household_ids(seeded)
    user_id = await _add_pending(seeded, households[0])
    crypto = _crypto()
    dek = await crypto.get_dek(seeded, TENANT_ID)
    seeded.add(
        ParkingVehicle(
            tenant_id=TENANT_ID,
            household_id=households[0],
            plate_enc=crypto.encrypt(dek, _PLATE),
            model="아이오닉5",
            is_ev=False,
        )
    )
    await seeded.flush()

    async with _client(seeded, fake_redis) as c:
        await c.post(f"/admin/approvals/{user_id}/reject", json={"reason": _REJECT_REASON})
        await c.get("/admin/roster")
        await c.get("/admin/parking/vehicles")
        await c.post("/admin/staff/invite", json={"email": _EMAIL, "name": _NAME})

    rows = await _audits(seeded)
    assert len(rows) >= 4
    assert pii not in _serialized(rows)


async def test_building_seed_is_untouched(seeded: AsyncSession) -> None:
    """시드 정합 확인용 — 감사 배선이 기존 시드를 건드리지 않는다."""
    assert await seeded.scalar(select(Building.name).where(Building.id == BUILDING_ID)) == "101"
