"""onboarding 제출 통합 테스트 — 실 PG + fakeredis. 명부 대조·동의·연령·세션 승격."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest_asyncio
from app.deps import get_onboarding_session
from app.main import create_app
from app.pii import PiiCrypto
from app.session import SessionStore, get_redis
from conftest import INVITE_CODE, TENANT_ID, seed_tenant
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Consent, Notification, PiiVault, User

NEW_SUB = "google-sub-onboarding-777"


def _body(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "invite_code": INVITE_CODE,
        "consents": [{"purpose": "privacy_required", "granted": True}],
        "name": "김입주",
        "birth_date": "1990-05-05",
        "building_name": "101",
        "floor": 3,
        "unit_no": 301,
    }
    base.update(over)
    return base


@pytest_asyncio.fixture
async def onboarding_client(
    db_session: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> httpx.AsyncClient:
    await seed_tenant(db_session)
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_onboarding_session] = lambda: db_session
    sid = await session_store.create_onboarding(NEW_SUB)
    client = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    client.cookies.set("liviq_session", sid)
    return client


async def _seed_pre_registered(
    session: AsyncSession,
    crypto: PiiCrypto,
    household_id: uuid.UUID,
    name: str,
    birth_iso: str,
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


async def test_onboarding_no_roster_match_creates_pending(
    onboarding_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    async with onboarding_client as c:
        response = await c.post("/onboarding/profile", json=_body())
        me = await c.get("/me")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["roster_matched"] is False

    user = await db_session.scalar(select(User).where(User.id == uuid.UUID(body["user_id"])))
    assert user is not None
    assert user.status == "pending"
    assert user.login_id == NEW_SUB
    assert user.roster_matched is False

    consents = await db_session.scalar(select(func.count()).select_from(Consent))
    assert consents == 1
    # MANAGER에게 승인 대기 알림 생성
    notif = await db_session.scalar(
        select(func.count()).select_from(Notification).where(Notification.type == "approval")
    )
    assert notif == 1
    # 세션 승격 — kind=user, status=pending
    assert me.status_code == 200
    assert me.json()["kind"] == "user"
    assert me.json()["status"] == "pending"


async def test_onboarding_roster_match_reuses_pre_registered_row(
    onboarding_client: httpx.AsyncClient,
    db_session: AsyncSession,
    pii_crypto: PiiCrypto,
) -> None:
    # 세대 id를 직접 조회(households는 onboarding_client fixture의 seed_tenant가 생성함).
    from liviq_db.models import Building, Household

    household_id = await db_session.scalar(
        select(Household.id)
        .join(Building, Building.id == Household.building_id)
        .where(Household.floor == 3, Household.unit_no == 301)
    )
    assert household_id is not None
    pre_id = await _seed_pre_registered(
        db_session, pii_crypto, household_id, "김입주", "1990-05-05"
    )

    async with onboarding_client as c:
        response = await c.post("/onboarding/profile", json=_body())

    assert response.status_code == 200
    body = response.json()
    assert body["roster_matched"] is True
    assert body["user_id"] == str(pre_id)  # 사전등록 행 재사용

    user = await db_session.scalar(select(User).where(User.id == pre_id))
    assert user is not None
    assert user.status == "pending"
    assert user.login_id == NEW_SUB
    assert user.roster_matched is True


async def test_under_14_rejected(onboarding_client: httpx.AsyncClient) -> None:
    async with onboarding_client as c:
        response = await c.post("/onboarding/profile", json=_body(birth_date="2020-01-01"))
    assert response.status_code == 422


async def test_invalid_invite_code_not_found(onboarding_client: httpx.AsyncClient) -> None:
    async with onboarding_client as c:
        response = await c.post("/onboarding/profile", json=_body(invite_code="WRONG"))
    assert response.status_code == 404


async def test_unknown_household_rejected(onboarding_client: httpx.AsyncClient) -> None:
    async with onboarding_client as c:
        response = await c.post("/onboarding/profile", json=_body(floor=9, unit_no=999))
    assert response.status_code == 422


async def test_missing_required_consent_rejected(onboarding_client: httpx.AsyncClient) -> None:
    async with onboarding_client as c:
        response = await c.post(
            "/onboarding/profile",
            json=_body(consents=[{"purpose": "privacy_required", "granted": False}]),
        )
    assert response.status_code == 422


async def test_invite_code_case_insensitive(onboarding_client: httpx.AsyncClient) -> None:
    async with onboarding_client as c:
        response = await c.post("/onboarding/profile", json=_body(invite_code="apt-1234"))
    assert response.status_code == 200
