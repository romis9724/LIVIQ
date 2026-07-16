"""Google OAuth PKCE 로그인·콜백·로그아웃·/me + 상태별 차단 (docs/06 §2, ADR-0011).

콜백은 실 PG(login_id 전역 조회) + fakeredis(세션·state)로 검증한다. state CSRF·
온보딩/pending 세션의 일반 API 차단은 CRITICAL 케이스(규칙 4, docs/06 §2).
"""

from __future__ import annotations

import base64
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from app.deps import get_auth_lookup_session, get_queue, get_storage, get_tenant_session
from app.main import create_app
from app.oauth import (
    GoogleOAuth,
    _decode_id_token,
    generate_pkce,
    get_oauth_provider,
)
from app.session import SessionStore, get_redis
from conftest import (
    GOOGLE_SUB,
    TENANT_ID,
    USER_ID,
    FakeOAuthProvider,
    FakeQueue,
    FakeStorage,
)
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Tenant, User, UserRole

# ── OAuth 어댑터 단위 (네트워크는 MockTransport) ────────────────────────


def test_generate_pkce_challenge_is_s256_of_verifier() -> None:
    import hashlib

    verifier, challenge = generate_pkce()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert challenge == expected
    assert "=" not in challenge  # base64url no-padding


def _make_id_token(claims: dict[str, str]) -> str:
    def seg(obj: dict[str, str]) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    return f"{seg({'alg': 'RS256'})}.{seg(claims)}.sig"


def test_decode_id_token_reads_sub_and_email() -> None:
    token = _make_id_token({"sub": "abc", "email": "user@example.com"})

    payload = _decode_id_token(token)

    assert payload["sub"] == "abc"
    assert payload["email"] == "user@example.com"


async def test_google_oauth_exchange_parses_identity() -> None:
    token = _make_id_token({"sub": "sub-xyz", "email": "u@ex.com"})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id_token": token, "access_token": "discarded"})

    provider = GoogleOAuth(
        "cid", "secret", "https://app/cb", transport=httpx.MockTransport(handler)
    )

    identity = await provider.exchange("code", "verifier")

    assert identity.sub == "sub-xyz"
    assert identity.email == "u@ex.com"


def test_google_oauth_authorize_url_carries_pkce() -> None:
    provider = GoogleOAuth("cid", "secret", "https://app/cb")

    url = provider.authorize_url("st8", "chal")

    q = parse_qs(urlparse(url).query)
    assert q["state"] == ["st8"]
    assert q["code_challenge"] == ["chal"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["client_id"] == ["cid"]


def test_get_oauth_provider_builds_google_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import get_settings

    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://app/cb")
    get_settings.cache_clear()
    try:
        assert isinstance(get_oauth_provider(), GoogleOAuth)
    finally:
        get_settings.cache_clear()


# ── 콜백·세션 경로 (실 PG + fakeredis) ─────────────────────────────────


async def _seed_user(session: AsyncSession, *, status: str, roles: list[str]) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status=status, login_id=GOOGLE_SUB))
    await session.flush()
    for role in roles:
        session.add(UserRole(tenant_id=TENANT_ID, user_id=USER_ID, role=role))
    await session.flush()


def _build_client(
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    provider: FakeOAuthProvider,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_auth_lookup_session] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_queue] = lambda: FakeQueue()
    app.dependency_overrides[get_oauth_provider] = lambda: provider
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


async def test_login_redirects_with_state_and_stores_verifier(
    db_session: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    async with _build_client(db_session, fake_redis, FakeOAuthProvider()) as c:
        response = await c.get("/auth/google/login")

    assert response.status_code == 302
    q = parse_qs(urlparse(response.headers["location"]).query)
    state = q["state"][0]
    assert "code_challenge" in q
    # state에 매핑된 code_verifier가 Redis에 보관됨(콜백까지)
    assert await session_store.pop_oauth_state(state) is not None


async def test_callback_active_user_issues_session_cookie(
    db_session: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    await _seed_user(db_session, status="active", roles=["RESIDENT", "COUNCIL"])
    await session_store.save_oauth_state("s1", "verifier1")

    async with _build_client(db_session, fake_redis, FakeOAuthProvider()) as c:
        callback = await c.get("/auth/google/callback", params={"code": "c", "state": "s1"})
        assert callback.status_code == 302
        me = await c.get("/me")

    assert me.status_code == 200
    body = me.json()
    assert body["kind"] == "user"
    assert body["status"] == "active"
    assert body["user_id"] == str(USER_ID)
    assert sorted(body["roles"]) == ["COUNCIL", "RESIDENT"]


async def test_callback_state_mismatch_rejected(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """저장되지 않은 state → 400(CSRF 방어, docs/06 §2)."""
    async with _build_client(db_session, fake_redis, FakeOAuthProvider()) as c:
        response = await c.get("/auth/google/callback", params={"code": "c", "state": "unknown"})

    assert response.status_code == 400


async def test_new_sub_gets_onboarding_session_blocked_from_documents(
    db_session: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    """users 행 없는 신규 sub → 온보딩 세션 → 일반 API(문서) 403(CRITICAL)."""
    await session_store.save_oauth_state("s2", "verifier2")
    provider = FakeOAuthProvider(sub="brand-new-sub")

    async with _build_client(db_session, fake_redis, provider) as c:
        callback = await c.get("/auth/google/callback", params={"code": "c", "state": "s2"})
        assert callback.status_code == 302
        assert callback.headers["location"] == "/onboarding"
        me = await c.get("/me")
        documents = await c.get("/documents")

    assert me.status_code == 200
    assert me.json()["kind"] == "onboarding"
    assert me.json()["tenant_id"] is None
    assert documents.status_code == 403


async def test_pending_user_me_ok_but_general_api_blocked(
    db_session: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    """pending 계정 → /me는 상태 노출(200), 일반 API는 403(docs/06 §2)."""
    await _seed_user(db_session, status="pending", roles=["RESIDENT"])
    await session_store.save_oauth_state("s3", "verifier3")

    async with _build_client(db_session, fake_redis, FakeOAuthProvider()) as c:
        await c.get("/auth/google/callback", params={"code": "c", "state": "s3"})
        me = await c.get("/me")
        general_api = await c.get("/documents")

    assert me.status_code == 200
    assert me.json()["status"] == "pending"
    assert general_api.status_code == 403


async def test_logout_revokes_session(
    db_session: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    await _seed_user(db_session, status="active", roles=["RESIDENT"])
    await session_store.save_oauth_state("s4", "verifier4")

    async with _build_client(db_session, fake_redis, FakeOAuthProvider()) as c:
        await c.get("/auth/google/callback", params={"code": "c", "state": "s4"})
        logout = await c.post("/auth/logout")
        me = await c.get("/me")

    assert logout.status_code == 204
    assert me.status_code == 401


async def test_login_returns_503_when_oauth_unconfigured(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """OAuth env 미설정 → /auth/google/login 503(부팅은 성공, 로그인만 비활성)."""
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    ) as c:
        response = await c.get("/auth/google/login")

    assert response.status_code == 503
