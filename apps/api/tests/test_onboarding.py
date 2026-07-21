"""onboarding 제출 통합 테스트 — 실 PG + fakeredis.

가입(status='registered') 세션 전제 → 동의·연령·명부 대조 → pending 전이·세션 갱신.
명부 매칭 시 가입자 행을 유지하고 사전등록 행을 soft delete한다(행 이동 금지, ADR-0014).
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest_asyncio
from app.deps import get_onboarding_session
from app.main import create_app
from app.pii import PiiCrypto, get_pii_crypto
from app.session import SessionStore, get_redis
from conftest import TENANT_ID, seed_tenant
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Consent, Notification, PiiVault, User

EMAIL = "onboarder@example.com"


def _body(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "consents": [{"purpose": "privacy_required", "granted": True}],
        "name": "김입주",
        "birth_date": "1990-05-05",
        "building_name": "101",
        "floor": 3,
        "unit_no": 301,
    }
    base.update(over)
    return base


async def _seed_registered_user(session: AsyncSession, crypto: PiiCrypto) -> uuid.UUID:
    """가입 완료(status='registered') 사용자 — email_enc만 있는 vault를 참조."""
    dek = await crypto.get_dek(session, TENANT_ID)
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id, tenant_id=TENANT_ID, email_enc=crypto.encrypt(dek, EMAIL), key_version=1
        )
    )
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            tenant_id=TENANT_ID,
            login_id=crypto.hmac_hash(EMAIL),
            password_hash="$argon2id$v=19$m=65536,t=3,p=4$dummy",
            status="registered",
            pii_ref=vault_id,
        )
    )
    await session.flush()
    return user_id


async def _seed_pre_registered(
    session: AsyncSession, crypto: PiiCrypto, household_id: uuid.UUID, name: str, birth_iso: str
) -> uuid.UUID:
    dek = await crypto.get_dek(session, TENANT_ID)
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id,
            tenant_id=TENANT_ID,
            name_enc=crypto.encrypt(dek, name),
            birth_date_enc=crypto.encrypt(dek, birth_iso),
            name_hash=crypto.hmac_hash(name),
            birth_date_hash=crypto.hmac_hash(birth_iso),
            key_version=1,
        )
    )
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            tenant_id=TENANT_ID,
            household_id=household_id,
            login_id=None,
            status="pre_registered",
            roster_matched=False,
            pii_ref=vault_id,
        )
    )
    await session.flush()
    return user_id


@pytest_asyncio.fixture
async def setup(
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    session_store: SessionStore,
    pii_crypto: PiiCrypto,
) -> tuple[httpx.AsyncClient, uuid.UUID]:
    await seed_tenant(db_session)
    user_id = await _seed_registered_user(db_session, pii_crypto)
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_onboarding_session] = lambda: db_session
    app.dependency_overrides[get_pii_crypto] = lambda: pii_crypto
    sid = await session_store.create(str(TENANT_ID), str(user_id), [], status="registered")
    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    client.cookies.set("liviq_session", sid)
    return client, user_id


async def test_onboarding_no_roster_match_creates_pending(
    setup: tuple[httpx.AsyncClient, uuid.UUID], db_session: AsyncSession
) -> None:
    client, user_id = setup
    async with client as c:
        response = await c.post("/onboarding/profile", json=_body())
        me = await c.get("/me")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["roster_matched"] is False
    assert body["user_id"] == str(user_id)  # 가입자 행 유지

    user = await db_session.scalar(select(User).where(User.id == user_id))
    assert user is not None
    assert user.status == "pending"
    assert user.household_id is not None
    assert user.roster_matched is False

    # 성함·생년월일이 가입 시 만든 vault에 채워짐(행 신설 아님).
    vault = await db_session.scalar(select(PiiVault).where(PiiVault.id == user.pii_ref))
    assert vault is not None
    assert vault.name_hash is not None and vault.email_enc is not None

    consents = await db_session.scalar(select(func.count()).select_from(Consent))
    assert consents == 1
    notif = await db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.type == "approval")
    )
    assert notif == 1
    # 세션 갱신 — pending.
    assert me.status_code == 200
    assert me.json()["status"] == "pending"


async def test_onboarding_roster_match_soft_deletes_pre_registered(
    setup: tuple[httpx.AsyncClient, uuid.UUID],
    db_session: AsyncSession,
    pii_crypto: PiiCrypto,
) -> None:
    from liviq_db.models import Building, Household

    client, user_id = setup
    household_id = await db_session.scalar(
        select(Household.id)
        .join(Building, Building.id == Household.building_id)
        .where(Household.floor == 3, Household.unit_no == 301)
    )
    assert household_id is not None
    pre_id = await _seed_pre_registered(
        db_session, pii_crypto, household_id, "김입주", "1990-05-05"
    )

    async with client as c:
        response = await c.post("/onboarding/profile", json=_body())

    assert response.status_code == 200
    body = response.json()
    assert body["roster_matched"] is True
    assert body["user_id"] == str(user_id)  # 가입자 행 유지(사전등록 행으로 이동 아님)

    user = await db_session.scalar(select(User).where(User.id == user_id))
    assert user is not None
    assert user.status == "pending"
    assert user.roster_matched is True

    # 사전등록 행은 soft delete.
    pre = await db_session.scalar(select(User).where(User.id == pre_id))
    assert pre is not None
    assert pre.deleted_at is not None


async def test_resubmit_after_pending_conflict(
    setup: tuple[httpx.AsyncClient, uuid.UUID],
) -> None:
    """제출 후 세션은 pending — 재제출은 409(registered 아님)."""
    client, _ = setup
    async with client as c:
        first = await c.post("/onboarding/profile", json=_body())
        second = await c.post("/onboarding/profile", json=_body())

    assert first.status_code == 200
    assert second.status_code == 409


async def test_under_14_rejected(setup: tuple[httpx.AsyncClient, uuid.UUID]) -> None:
    client, _ = setup
    async with client as c:
        response = await c.post("/onboarding/profile", json=_body(birth_date="2020-01-01"))
    assert response.status_code == 422


async def test_unknown_household_rejected(setup: tuple[httpx.AsyncClient, uuid.UUID]) -> None:
    client, _ = setup
    async with client as c:
        response = await c.post("/onboarding/profile", json=_body(floor=9, unit_no=999))
    assert response.status_code == 422


async def test_missing_required_consent_rejected(
    setup: tuple[httpx.AsyncClient, uuid.UUID],
) -> None:
    client, _ = setup
    async with client as c:
        response = await c.post(
            "/onboarding/profile",
            json=_body(consents=[{"purpose": "privacy_required", "granted": False}]),
        )
    assert response.status_code == 422
