"""자체 이메일+비밀번호 인증 — 가입·로그인·검증·재설정 + 상태별 차단 (ADR-0014, docs/06 §2).

실 PG(login_id·token_hash 전역 조회, pii_vault 암호화) + fakeredis(세션·레이트리밋)로 검증한다.
평문 비밀번호 미저장·검증 전 로그인 차단·토큰 1회용은 CRITICAL 케이스(규칙 2·4).
"""

from __future__ import annotations

import base64
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta

import httpx
from app import auth_tokens
from app.deps import get_auth_lookup_session, get_queue, get_storage, get_tenant_session
from app.mail import get_mailer
from app.main import create_app
from app.pii import PiiCrypto, get_pii_crypto
from app.session import SessionStore, get_redis
from conftest import TENANT_ID, FakeQueue, FakeStorage
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import AuthToken, Building, Household, PiiVault, Tenant, User

_KEK = base64.b64encode(b"0" * 32).decode()
EMAIL = "resident@example.com"
PASSWORD = "correct-horse-battery"


class FakeMailer:
    """발송 캡처 — 링크(토큰)를 테스트에서 꺼내 쓴다."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    def last_token(self) -> str:
        return self.sent[-1][2].split("token=")[1].strip()


def _crypto() -> PiiCrypto:
    return PiiCrypto(_KEK)


async def _session_count(redis: FakeRedis, tenant_id: object, user_id: object) -> int:
    """user_sessions 셋 크기 — fakeredis 스텁의 sync/async 겸용 반환을 흡수."""
    result = redis.smembers(f"user_sessions:{tenant_id}:{user_id}")
    members = await result if isinstance(result, Awaitable) else result
    return len(members)


async def _seed_tenant(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()


def _build_client(
    db_session: AsyncSession, fake_redis: FakeRedis, mailer: FakeMailer
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_auth_lookup_session] = lambda: db_session
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_pii_crypto] = _crypto
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_queue] = lambda: FakeQueue()
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


async def _signup(c: httpx.AsyncClient, email: str = EMAIL, password: str = PASSWORD) -> str:
    """가입 → user_id 반환(검증 메일 발송됨)."""
    resp = await c.post(
        "/auth/signup", json={"tenant_id": str(TENANT_ID), "email": email, "password": password}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["user_id"]


# ── signup ────────────────────────────────────────────────────────────────


async def test_signup_creates_registered_user_and_mails_link(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        user_id = await _signup(c)

    user = await db_session.scalar(select(User).where(User.id == user_id))
    assert user is not None
    assert user.status == "registered"
    assert user.email_verified_at is None
    assert user.login_id == _crypto().hmac_hash(EMAIL)  # keyed HMAC, 평문 아님
    # 검증 메일 1통 + 링크에 토큰.
    assert len(mailer.sent) == 1
    assert "token=" in mailer.sent[0][2]


async def test_signup_stores_email_encrypted_never_plaintext(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """이메일은 pii_vault.email_enc 암호화만 — 평문·비밀번호가 DB 어디에도 없다(CRITICAL)."""
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        user_id = await _signup(c)

    user = await db_session.scalar(select(User).where(User.id == user_id))
    assert user is not None
    vault = await db_session.scalar(select(PiiVault).where(PiiVault.id == user.pii_ref))
    assert vault is not None and vault.email_enc is not None

    crypto = _crypto()
    dek = await crypto.get_dek(db_session, TENANT_ID)
    assert crypto.decrypt(dek, vault.email_enc) == EMAIL  # 복호하면 평문
    assert isinstance(vault.email_enc, bytes) and vault.email_enc != EMAIL.encode()
    # 비밀번호: Argon2id 해시만(평문 미포함).
    assert user.password_hash is not None
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash
    # login_id는 평문 이메일이 아님.
    assert user.login_id != EMAIL


async def test_signup_duplicate_email_conflict(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        dup = await c.post(
            "/auth/signup",
            json={"tenant_id": str(TENANT_ID), "email": EMAIL.upper(), "password": PASSWORD},
        )

    assert dup.status_code == 409  # 정규화(소문자) 후 전역 중복


async def test_signup_short_password_422(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    await _seed_tenant(db_session)
    async with _build_client(db_session, fake_redis, FakeMailer()) as c:
        resp = await c.post(
            "/auth/signup",
            json={"tenant_id": str(TENANT_ID), "email": EMAIL, "password": "short"},
        )
    assert resp.status_code == 422


async def test_signup_unknown_tenant_404(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    async with _build_client(db_session, fake_redis, FakeMailer()) as c:
        resp = await c.post(
            "/auth/signup",
            json={
                "tenant_id": "99999999-9999-9999-9999-999999999999",
                "email": EMAIL,
                "password": PASSWORD,
            },
        )
    assert resp.status_code == 404


# ── verify-email ───────────────────────────────────────────────────────────


async def test_verify_email_marks_verified_and_redirects(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        user_id = await _signup(c)
        resp = await c.get("/auth/verify-email", params={"token": mailer.last_token()})

    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/login?verified=1")
    user = await db_session.scalar(select(User).where(User.id == user_id))
    assert user is not None and user.email_verified_at is not None


async def test_verify_email_token_single_use(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """재사용 불가 — 두 번째 클릭은 오류 리다이렉트(CRITICAL, used_at 소진)."""
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        token = mailer.last_token()
        first = await c.get("/auth/verify-email", params={"token": token})
        second = await c.get("/auth/verify-email", params={"token": token})

    assert first.headers["location"].endswith("/login?verified=1")
    assert second.headers["location"].endswith("/login?verify_error=1")


async def test_verify_email_expired_rejected(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """만료 토큰은 검증 불가(CRITICAL)."""
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        token = mailer.last_token()
        # 토큰을 과거 만료로 조작.
        tok = await db_session.scalar(
            select(AuthToken).where(AuthToken.token_hash == auth_tokens._hash_token(token))
        )
        assert tok is not None
        tok.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db_session.flush()
        resp = await c.get("/auth/verify-email", params={"token": token})

    assert resp.headers["location"].endswith("/login?verify_error=1")


async def test_verify_email_bad_token_redirects_error(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    await _seed_tenant(db_session)
    async with _build_client(db_session, fake_redis, FakeMailer()) as c:
        resp = await c.get("/auth/verify-email", params={"token": "nonexistent"})
    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/login?verify_error=1")


# ── login ───────────────────────────────────────────────────────────────────


async def test_login_success_after_verify(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        await c.get("/auth/verify-email", params={"token": mailer.last_token()})
        login = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        me = await c.get("/me")

    assert login.status_code == 200
    assert login.json()["status"] == "registered"  # 온보딩 필요 신호
    assert me.status_code == 200

    assert me.json()["status"] == "registered"
    assert me.json()["email"] == EMAIL  # 세션 저장분 표시(ADR-0014 개정, H7-5)


async def test_tenant_directory_public_excludes_system(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """가입 단지 선택 목록 — 인증 없이 조회, 시스템 테넌트 제외(H7-5)."""
    from app.config import SYSTEM_TENANT_ID

    await _seed_tenant(db_session)
    db_session.add(Tenant(id=SYSTEM_TENANT_ID, name="LIVIQ 시스템", status="active"))
    await db_session.flush()

    async with _build_client(db_session, fake_redis, FakeMailer()) as c:
        resp = await c.get("/auth/tenants")

    assert resp.status_code == 200
    names = [t["name"] for t in resp.json()["items"]]
    assert names == ["단지A"]  # 시스템 테넌트 미노출


async def test_login_unverified_forbidden(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    """검증 전 로그인 차단 — 403 email_not_verified(CRITICAL)."""
    await _seed_tenant(db_session)
    async with _build_client(db_session, fake_redis, FakeMailer()) as c:
        await _signup(c)
        login = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert login.status_code == 403
    assert login.json()["detail"] == "email_not_verified"


async def test_login_wrong_and_unknown_return_same_401(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        await c.get("/auth/verify-email", params={"token": mailer.last_token()})
        wrong = await c.post("/auth/login", json={"email": EMAIL, "password": "totally-wrong"})
        unknown = await c.post(
            "/auth/login", json={"email": "nobody@example.com", "password": PASSWORD}
        )

    assert wrong.status_code == 401
    assert unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]  # 존재 노출 금지


async def test_login_rate_limited_after_5(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    async with _build_client(db_session, fake_redis, FakeMailer()) as c:
        for _ in range(5):
            r = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
            assert r.status_code == 401
        sixth = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert sixth.status_code == 429


async def test_login_deleted_account_401(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        user_id = await _signup(c)
        await c.get("/auth/verify-email", params={"token": mailer.last_token()})
        user = await db_session.scalar(select(User).where(User.id == user_id))
        assert user is not None
        user.deleted_at = datetime.now(UTC)
        await db_session.flush()
        login = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert login.status_code == 401


# ── password reset ───────────────────────────────────────────────────────────


async def test_password_reset_always_202(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    """존재 여부 무관 202(존재 노출 금지)."""
    await _seed_tenant(db_session)
    async with _build_client(db_session, fake_redis, FakeMailer()) as c:
        missing = await c.post("/auth/password-reset", json={"email": "nobody@example.com"})
    assert missing.status_code == 202


async def test_password_reset_confirm_rotates_password_and_revokes(
    db_session: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()
    new_password = "brand-new-passphrase"

    async with _build_client(db_session, fake_redis, mailer) as c:
        user_id = await _signup(c)
        await c.get("/auth/verify-email", params={"token": mailer.last_token()})
        # 로그인 세션 1개 확보(재설정 후 revoke 확인용).
        await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        assert await _session_count(fake_redis, TENANT_ID, user_id) == 1

        reset = await c.post("/auth/password-reset", json={"email": EMAIL})
        assert reset.status_code == 202
        confirm = await c.post(
            "/auth/password-reset/confirm",
            json={"token": mailer.last_token(), "new_password": new_password},
        )
        assert confirm.status_code == 204
        # 재설정 직후 — 기존 세션 전부 revoke됨(탈취 대비).
        assert await _session_count(fake_redis, TENANT_ID, user_id) == 0

        old = await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        new = await c.post("/auth/login", json={"email": EMAIL, "password": new_password})

    assert old.status_code == 401  # 구 비밀번호 실패
    assert new.status_code == 200  # 신 비밀번호 성공


async def test_password_reset_confirm_token_single_use(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        await c.get("/auth/verify-email", params={"token": mailer.last_token()})
        await c.post("/auth/password-reset", json={"email": EMAIL})
        token = mailer.last_token()
        first = await c.post(
            "/auth/password-reset/confirm",
            json={"token": token, "new_password": "first-passphrase"},
        )
        second = await c.post(
            "/auth/password-reset/confirm",
            json={"token": token, "new_password": "second-passphrase"},
        )

    assert first.status_code == 204
    assert second.status_code == 400  # 1회용 소진


# ── logout ────────────────────────────────────────────────────────────────────


async def test_logout_revokes_session(db_session: AsyncSession, fake_redis: FakeRedis) -> None:
    await _seed_tenant(db_session)
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        await c.get("/auth/verify-email", params={"token": mailer.last_token()})
        await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
        logout = await c.post("/auth/logout")
        me = await c.get("/me")

    assert logout.status_code == 204
    assert me.status_code == 401


async def test_me_exposes_own_name_and_unit(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    """본인 세션은 실명·'{동}동 {호}호'를 /me로 받는다(H8-8, 본인 소유 vault만)."""
    await _seed_tenant(db_session)
    crypto = _crypto()
    mailer = FakeMailer()

    async with _build_client(db_session, fake_redis, mailer) as c:
        await _signup(c)
        await c.get("/auth/verify-email", params={"token": mailer.last_token()})
        await c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

        # 온보딩 대체 — 세대 배정 + 실명 암호화(본인 vault)
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
        )
        user = await db_session.scalar(select(User).where(User.tenant_id == TENANT_ID))
        assert user is not None and user.pii_ref is not None
        building = Building(tenant_id=TENANT_ID, name="401", floors=25)
        db_session.add(building)
        await db_session.flush()
        household = Household(
            tenant_id=TENANT_ID,
            building_id=building.id,
            floor=2,
            unit_no=201,
            status="active",
        )
        db_session.add(household)
        await db_session.flush()
        user.household_id = household.id
        vault = await db_session.scalar(select(PiiVault).where(PiiVault.id == user.pii_ref))
        assert vault is not None
        dek = await crypto.get_dek(db_session, TENANT_ID)
        vault.name_enc = crypto.encrypt(dek, "최주민")
        await db_session.flush()

        me = await c.get("/me")

    assert me.status_code == 200
    body = me.json()
    assert body["display_name"] == "최주민"
    assert body["unit_label"] == "401동 201호"
