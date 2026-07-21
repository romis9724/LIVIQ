"""가입 승인/거절 통합 테스트 — 실 PG + fakeredis. 상태 전환·역할 부여·세션 revoke·인가."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app.deps import RequestContext, get_context, get_tenant_session
from app.main import create_app
from app.pii import PiiCrypto
from app.routers.approvals import mask_name
from app.session import SessionStore, get_redis
from conftest import MANAGER_USER_ID, TENANT_ID, seed_tenant
from fakeredis.aioredis import FakeRedis
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Notification, PiiVault, User, UserRole


@pytest.mark.parametrize(
    ("name", "expected"),
    [("홍", "*"), ("길동", "길*"), ("홍길동", "홍*동"), ("남궁민수", "남*수")],
)
def test_mask_name(name: str, expected: str) -> None:
    assert mask_name(name) == expected


async def _seed_applicant(
    session: AsyncSession,
    crypto: PiiCrypto,
    household_id: uuid.UUID,
    name: str = "김입주",
    status: str = "pending",
    login_id: str = "applicant-sub",
) -> uuid.UUID:
    dek = await crypto.get_dek(session, TENANT_ID)
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id,
            tenant_id=TENANT_ID,
            name_enc=crypto.encrypt(dek, name),
            name_hash=crypto.hmac_hash(name),
            key_version=1,
        )
    )
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            tenant_id=TENANT_ID,
            household_id=household_id,
            login_id=login_id,
            status=status,
            roster_matched=False,
            pii_ref=vault_id,
        )
    )
    await session.flush()
    return user_id


def _build_app(
    db_session: AsyncSession, fake_redis: FakeRedis, *, roles: tuple[str, ...] = ("MANAGER",)
) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, MANAGER_USER_ID, roles=roles
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: fake_redis
    return app


@pytest_asyncio.fixture
async def seeded(
    db_session: AsyncSession,
) -> AsyncIterator[dict[tuple[int, int], uuid.UUID]]:
    households = await seed_tenant(db_session)
    yield households


async def test_approve_activates_grants_role_notifies_and_revokes(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    session_store: SessionStore,
    pii_crypto: PiiCrypto,
) -> None:
    applicant_id = await _seed_applicant(db_session, pii_crypto, seeded[(3, 301)])
    old_sid = await session_store.create(str(TENANT_ID), str(applicant_id), [], status="pending")

    app = _build_app(db_session, fake_redis)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/admin/approvals/{applicant_id}/approve")
        # 구세션으로 /me → revoke 되어 401
        me = await c.get("/me", cookies={"liviq_session": old_sid})

    assert response.status_code == 204
    user = await db_session.scalar(select(User).where(User.id == applicant_id))
    assert user is not None and user.status == "active"
    assert user.approved_by == MANAGER_USER_ID and user.approved_at is not None
    role = await db_session.scalar(
        select(UserRole.role).where(UserRole.user_id == applicant_id, UserRole.role == "RESIDENT")
    )
    assert role == "RESIDENT"
    notif = await db_session.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == applicant_id, Notification.type == "approval")
    )
    assert notif == 1
    assert await session_store.get(old_sid) is None  # revoke_all
    assert me.status_code == 401


async def test_reject_sets_reason_and_revokes(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    session_store: SessionStore,
    pii_crypto: PiiCrypto,
) -> None:
    applicant_id = await _seed_applicant(db_session, pii_crypto, seeded[(3, 301)])
    old_sid = await session_store.create(str(TENANT_ID), str(applicant_id), [], status="pending")

    app = _build_app(db_session, fake_redis)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(
            f"/admin/approvals/{applicant_id}/reject", json={"reason": "명부 불일치"}
        )

    assert response.status_code == 204
    user = await db_session.scalar(select(User).where(User.id == applicant_id))
    assert user is not None and user.status == "rejected"
    assert user.rejected_reason == "명부 불일치"
    assert await session_store.get(old_sid) is None


async def test_reject_without_reason_rejected(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    pii_crypto: PiiCrypto,
) -> None:
    applicant_id = await _seed_applicant(db_session, pii_crypto, seeded[(3, 301)])
    app = _build_app(db_session, fake_redis)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        empty = await c.post(f"/admin/approvals/{applicant_id}/reject", json={"reason": ""})
        missing = await c.post(f"/admin/approvals/{applicant_id}/reject", json={})
    assert empty.status_code == 422
    assert missing.status_code == 422


async def test_approve_non_pending_conflict(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    pii_crypto: PiiCrypto,
) -> None:
    applicant_id = await _seed_applicant(db_session, pii_crypto, seeded[(3, 301)], status="active")
    app = _build_app(db_session, fake_redis)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/admin/approvals/{applicant_id}/approve")
    assert response.status_code == 409


async def test_list_masks_names(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    pii_crypto: PiiCrypto,
) -> None:
    await _seed_applicant(db_session, pii_crypto, seeded[(3, 301)], name="홍길동")
    app = _build_app(db_session, fake_redis)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/admin/approvals")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["name_masked"] == "홍*동"
    assert items[0]["building_name"] == "101"
    # 원문 이름이 응답 어디에도 없음
    assert "홍길동" not in response.text


async def test_cross_tenant_approve_not_found(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    pii_crypto: PiiCrypto,
) -> None:
    """다른 단지 사용자 승인 시도 → RLS로 미조회 → 404(CRITICAL 격리)."""
    other_tenant = uuid.UUID("99999999-9999-9999-9999-999999999999")
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(other_tenant))
    )
    from liviq_db.models import Tenant

    db_session.add(Tenant(id=other_tenant, name="단지B", status="active"))
    await db_session.flush()
    other_user = uuid.uuid4()
    db_session.add(
        User(id=other_user, tenant_id=other_tenant, status="pending", roster_matched=False)
    )
    await db_session.flush()
    # 컨텍스트 복귀(우리 단지)
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )

    app = _build_app(db_session, fake_redis)
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/admin/approvals/{other_user}/approve")
    assert response.status_code == 404


async def test_staff_cannot_approve(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    pii_crypto: PiiCrypto,
) -> None:
    """STAFF 세션으로 승인 시도 → 403(규칙 4, 서버 인가)."""
    applicant_id = await _seed_applicant(db_session, pii_crypto, seeded[(3, 301)])
    app = _build_app(db_session, fake_redis, roles=("STAFF",))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post(f"/admin/approvals/{applicant_id}/approve")
    assert response.status_code == 403


# ── 불일치 사유 (H7-9) ───────────────────────────────────────────────────────


async def _seed_roster_row(
    session: AsyncSession,
    crypto: PiiCrypto,
    household_id: uuid.UUID,
    name: str,
    *,
    consumed: bool = False,
) -> None:
    """명부 출신 행(pre_registered·login_id 없음). consumed=True면 소진(가입 완료)."""
    import datetime as dt

    dek = await crypto.get_dek(session, TENANT_ID)
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id,
            tenant_id=TENANT_ID,
            name_enc=crypto.encrypt(dek, name),
            name_hash=crypto.hmac_hash(name),
            key_version=1,
        )
    )
    session.add(
        User(
            tenant_id=TENANT_ID,
            household_id=household_id,
            login_id=None,
            status="pre_registered",
            pii_ref=vault_id,
            deleted_at=dt.datetime.now(dt.UTC) if consumed else None,
        )
    )
    await session.flush()


async def _mismatch_of(app: FastAPI, applicant_id: uuid.UUID) -> str | None:
    import httpx
    from httpx import ASGITransport

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/admin/approvals")
    assert resp.status_code == 200
    item = next(i for i in resp.json()["items"] if i["user_id"] == str(applicant_id))
    assert item["roster_matched"] is False
    return item["mismatch_reason"]


async def test_mismatch_reasons(
    seeded: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    pii_crypto: PiiCrypto,
) -> None:
    """불일치 사유 3분류(H7-9) — 세대 명부 없음 / 인적 불일치 / 전원 소진."""
    app = _build_app(db_session, fake_redis)
    h_none, h_mismatch, h_consumed = seeded[(3, 301)], seeded[(3, 302)], seeded[(5, 501)]

    # ① 해당 세대에 명부 행 자체가 없음.
    a1 = await _seed_applicant(db_session, pii_crypto, h_none, name="김하나", login_id="a1")
    assert await _mismatch_of(app, a1) == "no_household_roster"

    # ② 세대 명부는 있으나 성함·생년 불일치(미소진 행 존재).
    await _seed_roster_row(db_session, pii_crypto, h_mismatch, "박명부")
    a2 = await _seed_applicant(db_session, pii_crypto, h_mismatch, name="김둘", login_id="a2")
    assert await _mismatch_of(app, a2) == "person_mismatch"

    # ③ 세대 명부 전원이 이미 가입(전부 소진).
    await _seed_roster_row(db_session, pii_crypto, h_consumed, "이명부", consumed=True)
    a3 = await _seed_applicant(db_session, pii_crypto, h_consumed, name="김셋", login_id="a3")
    assert await _mismatch_of(app, a3) == "all_consumed"
