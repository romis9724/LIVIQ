"""Redis 세션 스토어 + 역할 인가 가드 테스트 (ADR-0011, docs/06 §2).

SessionStore는 fakeredis로, 쿠키 인가 경로는 실 PG + fakeredis로 검증한다.
보안 게이트(교차 역할 거부·만료 401)는 CRITICAL 케이스.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app.deps import (
    get_queue,
    get_storage,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from app.session import SessionStore, get_redis
from conftest import TENANT_ID, USER_ID, FakeQueue, FakeStorage
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Tenant, User

_SESSION_KEY = "session:"


# ── SessionStore 단위 (fakeredis) ──────────────────────────────────────


async def test_create_get_roundtrip_preserves_roles(session_store: SessionStore) -> None:
    sid = await session_store.create(str(TENANT_ID), str(USER_ID), ["MANAGER", "STAFF"])

    data = await session_store.get(sid)

    assert data is not None
    assert data.tenant_id == str(TENANT_ID)
    assert data.user_id == str(USER_ID)
    assert data.roles == ("MANAGER", "STAFF")


async def test_revoke_removes_session(session_store: SessionStore) -> None:
    sid = await session_store.create(str(TENANT_ID), str(USER_ID), ["RESIDENT"])

    await session_store.revoke(sid)

    assert await session_store.get(sid) is None


async def test_revoke_all_for_user_removes_every_session(session_store: SessionStore) -> None:
    sid1 = await session_store.create(str(TENANT_ID), str(USER_ID), ["RESIDENT"])
    sid2 = await session_store.create(str(TENANT_ID), str(USER_ID), ["RESIDENT"])

    await session_store.revoke_all_for_user(str(TENANT_ID), str(USER_ID))

    assert await session_store.get(sid1) is None
    assert await session_store.get(sid2) is None


async def test_get_slides_idle_ttl(session_store: SessionStore, fake_redis: FakeRedis) -> None:
    sid = await session_store.create(str(TENANT_ID), str(USER_ID), ["RESIDENT"])
    key = f"{_SESSION_KEY}{sid}"
    await fake_redis.expire(key, 100)  # idle이 거의 소진된 상태를 모사

    await session_store.get(sid)  # 조회 시 슬라이딩 연장

    ttl = await fake_redis.ttl(key)
    assert ttl > 100  # 다시 idle(2h)로 연장됨


def test_visibilities_for_maps_roles() -> None:
    assert visibilities_for(["RESIDENT"]) == ("ALL", "RESIDENT")
    assert visibilities_for(["MANAGER"]) == ("ALL", "RESIDENT", "ADMIN")
    assert visibilities_for(["STAFF"]) == ("ALL", "RESIDENT", "ADMIN")
    # 합집합 + 정렬 고정
    assert visibilities_for(["RESIDENT", "MANAGER"]) == ("ALL", "RESIDENT", "ADMIN")
    # 미지정/빈 역할(H7-2에서 제거된 FACILITY 포함) → 입주민 기본값
    assert visibilities_for(["FACILITY"]) == ("ALL", "RESIDENT")
    assert visibilities_for([]) == ("ALL", "RESIDENT")


# ── 쿠키 인가 경로 (실 PG + fakeredis) ─────────────────────────────────


async def _seed_tenant_user(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await session.flush()


def _build_client(db_session: AsyncSession, fake_redis: FakeRedis) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_queue] = lambda: FakeQueue()
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> AsyncIterator[httpx.AsyncClient]:
    await _seed_tenant_user(db_session)
    async with _build_client(db_session, fake_redis) as c:
        yield c


async def test_manager_session_cookie_allows_documents_get(
    client: httpx.AsyncClient, session_store: SessionStore
) -> None:
    sid = await session_store.create(str(TENANT_ID), str(USER_ID), ["MANAGER"])
    client.cookies.set("liviq_session", sid)

    response = await client.get("/documents")

    assert response.status_code == 200
    assert response.json()["items"] == []


async def test_resident_session_denied_on_documents_upload(
    client: httpx.AsyncClient, session_store: SessionStore
) -> None:
    """교차 역할 거부 — RESIDENT는 문서 업로드 불가(CRITICAL, 규칙 4)."""
    sid = await session_store.create(str(TENANT_ID), str(USER_ID), ["RESIDENT"])
    client.cookies.set("liviq_session", sid)

    response = await client.post(
        "/documents",
        files={"file": ("규약.txt", "본문".encode(), "text/plain")},
        data={"title": "규약", "category_code_id": str(uuid.uuid4()), "visibility": "ALL"},
    )

    assert response.status_code == 403


async def test_invalid_session_cookie_rejected(client: httpx.AsyncClient) -> None:
    client.cookies.set("liviq_session", "does-not-exist")

    response = await client.get("/documents")

    assert response.status_code == 401


async def test_revoked_session_cookie_rejected(
    client: httpx.AsyncClient, session_store: SessionStore
) -> None:
    sid = await session_store.create(str(TENANT_ID), str(USER_ID), ["MANAGER"])
    await session_store.revoke(sid)
    client.cookies.set("liviq_session", sid)

    response = await client.get("/documents")

    assert response.status_code == 401


async def test_dev_headers_rejected_in_non_local_env(
    db_session: AsyncSession, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비-local 환경에선 쿠키 없는 dev 헤더는 통하지 않는다(401)."""
    from app.config import get_settings

    monkeypatch.setenv("API_ENV", "staging")
    get_settings.cache_clear()
    try:
        await _seed_tenant_user(db_session)
        async with _build_client(db_session, fake_redis) as c:
            response = await c.get(
                "/documents",
                headers={
                    "X-Dev-Tenant-Id": str(TENANT_ID),
                    "X-Dev-User-Id": str(USER_ID),
                },
            )
        assert response.status_code == 401
    finally:
        get_settings.cache_clear()
