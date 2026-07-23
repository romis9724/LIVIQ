"""H7-2 역할 인가 매트릭스 + 초대·수락·비활성화 + 임시 비밀번호 강제 변경 (CRITICAL 게이트).

실 PG + fakeredis. FACILITY·COUNCIL 제거·STAFF 축소로 소장 전용이 된 엔드포인트의 STAFF
거부, SYS_ADMIN의 단지 콘텐츠 비열람, 초대→수락→로그인 여정, 임시 비밀번호 게이트를 검증한다.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest_asyncio
from app import auth_tokens
from app.config import SYSTEM_TENANT_ID
from app.deps import (
    RequestContext,
    get_auth_lookup_session,
    get_context,
    get_queue,
    get_storage,
    get_tenant_session,
)
from app.mail import get_mailer
from app.main import create_app
from app.password import hash_password
from app.pii import PiiCrypto, get_pii_crypto
from app.session import SessionStore, get_redis
from conftest import MANAGER_USER_ID, TENANT_ID, FakeQueue, FakeStorage, seed_tenant
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import AuthToken, CodeGroup, PiiVault, User, UserRole

_KEK = base64.b64encode(b"0" * 32).decode()
STAFF_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
SYS_ADMIN_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


def _crypto() -> PiiCrypto:
    return PiiCrypto(_KEK)


class FakeMailer:
    """발송 캡처 — 초대 링크(토큰)를 테스트에서 꺼내 쓴다."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))

    def last_token(self) -> str:
        return self.sent[-1][2].split("token=")[1].strip()


def _make_app(
    db_session: AsyncSession,
    fake_redis: FakeRedis,
    mailer: FakeMailer,
    *,
    ctx: RequestContext | None = None,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_redis] = lambda: fake_redis
    app.dependency_overrides[get_auth_lookup_session] = lambda: db_session
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_pii_crypto] = _crypto
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_queue] = lambda: FakeQueue()
    if ctx is not None:  # 매트릭스 검사는 컨텍스트 주입, 세션 여정은 실 쿠키(ctx=None)
        app.dependency_overrides[get_context] = lambda: ctx
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
    )


def _ctx(roles: tuple[str, ...], *, user_id: uuid.UUID = MANAGER_USER_ID) -> RequestContext:
    return RequestContext(TENANT_ID, user_id, roles=roles)


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await seed_tenant(db_session)
    yield db_session


# ── 역할 인가 매트릭스 (CRITICAL) ────────────────────────────────────────────


async def test_staff_retains_inquiry_and_document_access(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("STAFF",), user_id=STAFF_ID)
    ) as c:
        assert (await c.get("/admin/inquiries")).status_code == 200
        assert (await c.get("/documents")).status_code == 200
        # 공지 작성·발행은 STAFF에 개방(H7-2 부분 개정, ADR-0015) — 역할 가드 통과 확인.
        assert (await c.get("/admin/notices")).status_code == 200
        created = await c.post(
            "/admin/notices", json={"title": "직원 공지", "body": "본문", "status": "draft"}
        )
        assert created.status_code == 201


async def test_staff_denied_manager_only_surfaces(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    """관리비·시설·승인·명부·직원초대는 소장 전용 — STAFF 전부 403(CRITICAL).

    공지 발행은 ADR-0015로 STAFF에 개방됐다(위 allowed 테스트) — 여기 목록에서 제외.
    """
    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("STAFF",), user_id=STAFF_ID)
    ) as c:
        assert (await c.get("/admin/fees")).status_code == 403
        assert (await c.get("/admin/facilities")).status_code == 403
        assert (await c.get("/admin/approvals")).status_code == 403
        assert (
            await c.post("/admin/staff/invite", json={"email": "x@example.com"})
        ).status_code == 403
        roster = await c.post("/admin/roster/upload", files={"file": ("r.xlsx", b"x")})
        assert roster.status_code == 403


async def test_sys_admin_denied_tenant_content(seeded: AsyncSession, fake_redis: FakeRedis) -> None:
    """SYS_ADMIN은 단지 콘텐츠 비열람 — 문서·민원·관리비·시설·승인 전부 403(CRITICAL 규칙 4)."""
    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("SYS_ADMIN",), user_id=SYS_ADMIN_ID)
    ) as c:
        assert (await c.get("/documents")).status_code == 403
        assert (await c.get("/admin/inquiries")).status_code == 403
        assert (await c.get("/admin/fees")).status_code == 403
        assert (await c.get("/admin/facilities")).status_code == 403
        assert (await c.get("/admin/approvals")).status_code == 403


async def test_manager_cannot_access_tenant_admin(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as c:
        assert (await c.get("/admin/tenants")).status_code == 403
        assert (await c.post("/admin/tenants", json={"name": "x"})).status_code == 403


# ── 단지 생성 + 소장 초대 (SYS_ADMIN) ────────────────────────────────────────


async def test_sys_admin_create_list_and_invite_manager(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    mailer = FakeMailer()
    email = "mgr@example.com"
    async with _make_app(
        db_session, fake_redis, mailer, ctx=_ctx(("SYS_ADMIN",), user_id=SYS_ADMIN_ID)
    ) as c:
        created = await c.post("/admin/tenants", json={"name": "새단지"})
        assert created.status_code == 201, created.text
        tid = created.json()["id"]

        # 단지 생성 시 기본 공통 코드 시드(H8-4, ADR-0017·0018) — 시스템 그룹 3종.
        await db_session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=tid)
        )
        seeded_groups = list(
            await db_session.scalars(
                select(CodeGroup.group_key).where(CodeGroup.tenant_id == uuid.UUID(tid))
            )
        )
        assert set(seeded_groups) == {"NOTICE_CATEGORY", "DOC_CATEGORY", "INQUIRY_CATEGORY"}

        listed = await c.get("/admin/tenants")
        assert listed.status_code == 200
        assert any(t["id"] == tid for t in listed.json()["items"])
        # 시스템 테넌트는 목록 제외·초대 불가(소장 초대 대상 아님).
        assert all(t["id"] != str(SYSTEM_TENANT_ID) for t in listed.json()["items"])
        sys_invite = await c.post(
            f"/admin/tenants/{SYSTEM_TENANT_ID}/invite-manager", json={"email": email}
        )
        assert sys_invite.status_code == 404

        invited = await c.post(f"/admin/tenants/{tid}/invite-manager", json={"email": email})
        assert invited.status_code == 202

    # 초대 계정: status='invited' + MANAGER 역할 + 메일 토큰.
    await db_session.execute(text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=tid))
    user = await db_session.scalar(select(User).where(User.login_id == _crypto().hmac_hash(email)))
    assert user is not None and user.status == "invited"
    assert user.password_hash is None  # 수락 전 비밀번호 미설정
    role = await db_session.scalar(select(UserRole.role).where(UserRole.user_id == user.id))
    assert role == "MANAGER"
    assert "token=" in mailer.sent[-1][2]


async def test_invite_manager_unknown_tenant_404(
    db_session: AsyncSession, fake_redis: FakeRedis
) -> None:
    async with _make_app(
        db_session, fake_redis, FakeMailer(), ctx=_ctx(("SYS_ADMIN",), user_id=SYS_ADMIN_ID)
    ) as c:
        resp = await c.post(
            "/admin/tenants/99999999-9999-9999-9999-999999999999/invite-manager",
            json={"email": "x@example.com"},
        )
    assert resp.status_code == 404


# ── 직원 초대 → 수락 → 로그인 여정 (MANAGER) ─────────────────────────────────


async def test_staff_invite_accept_login_journey(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    mailer = FakeMailer()
    email = "newstaff@example.com"
    password = "brand-new-staff-pass"
    async with _make_app(seeded, fake_redis, mailer, ctx=_ctx(("MANAGER",))) as mgr:
        invited = await mgr.post(
            "/admin/staff/invite", json={"email": email, "name": "신입직원"}
        )
        assert invited.status_code == 202
    token = mailer.last_token()

    async with _make_app(seeded, fake_redis, mailer) as c:
        accept = await c.post("/auth/invite/accept", json={"token": token, "password": password})
        assert accept.status_code == 204
        login = await c.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        assert login.json()["status"] == "active"
        me = await c.get("/me")
        assert "STAFF" in me.json()["roles"]
        assert me.json()["must_change_password"] is False


async def test_staff_invite_duplicate_email_conflict(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    mailer = FakeMailer()
    async with _make_app(seeded, fake_redis, mailer, ctx=_ctx(("MANAGER",))) as mgr:
        first = await mgr.post(
            "/admin/staff/invite", json={"email": "dup@example.com", "name": "중복직원"}
        )
        assert first.status_code == 202
        second = await mgr.post(
            "/admin/staff/invite", json={"email": "DUP@example.com", "name": "중복직원"}
        )
    assert second.status_code == 409  # 정규화(소문자) 후 전역 중복


async def test_invite_accept_reused_token_rejected(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    mailer = FakeMailer()
    async with _make_app(seeded, fake_redis, mailer, ctx=_ctx(("MANAGER",))) as mgr:
        await mgr.post(
            "/admin/staff/invite", json={"email": "once@example.com", "name": "일회직원"}
        )
    token = mailer.last_token()
    async with _make_app(seeded, fake_redis, mailer) as c:
        first = await c.post(
            "/auth/invite/accept", json={"token": token, "password": "first-passphrase"}
        )
        second = await c.post(
            "/auth/invite/accept", json={"token": token, "password": "second-passphrase"}
        )
    assert first.status_code == 204
    assert second.status_code == 400  # 1회용 소진(status invited 아님 + used_at)


async def test_invite_accept_expired_token_rejected(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    mailer = FakeMailer()
    async with _make_app(seeded, fake_redis, mailer, ctx=_ctx(("MANAGER",))) as mgr:
        await mgr.post("/admin/staff/invite", json={"email": "exp@example.com", "name": "만료직원"})
    token = mailer.last_token()
    tok = await seeded.scalar(
        select(AuthToken).where(AuthToken.token_hash == auth_tokens._hash_token(token))
    )
    assert tok is not None
    tok.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    await seeded.flush()
    async with _make_app(seeded, fake_redis, mailer) as c:
        resp = await c.post(
            "/auth/invite/accept", json={"token": token, "password": "expired-passphrase"}
        )
    assert resp.status_code == 400


# ── 직원 비활성화 (MANAGER) ──────────────────────────────────────────────────


async def _seed_role_user(
    session: AsyncSession, user_id: uuid.UUID, role: str, status: str = "active"
) -> None:
    session.add(User(id=user_id, tenant_id=TENANT_ID, status=status))
    await session.flush()
    session.add(UserRole(tenant_id=TENANT_ID, user_id=user_id, role=role))
    await session.flush()


async def test_deactivate_staff_sets_inactive_and_revokes(
    seeded: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    staff_id = uuid.uuid4()
    await _seed_role_user(seeded, staff_id, "STAFF")
    sid = await session_store.create(str(TENANT_ID), str(staff_id), ["STAFF"], status="active")

    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as mgr:
        resp = await mgr.post(f"/admin/staff/{staff_id}/deactivate")

    assert resp.status_code == 204
    user = await seeded.scalar(select(User).where(User.id == staff_id))
    assert user is not None and user.status == "inactive"
    assert await session_store.get(sid) is None  # 세션 즉시 revoke


async def test_deactivate_self_and_manager_rejected(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    other_manager = uuid.uuid4()
    await _seed_role_user(seeded, other_manager, "MANAGER")
    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as mgr:
        # 자기 자신
        assert (await mgr.post(f"/admin/staff/{MANAGER_USER_ID}/deactivate")).status_code == 400
        # 다른 소장
        assert (await mgr.post(f"/admin/staff/{other_manager}/deactivate")).status_code == 400


async def test_list_staff_returns_managers_and_staff(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    staff_id = uuid.uuid4()
    await _seed_role_user(seeded, staff_id, "STAFF")
    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as mgr:
        resp = await mgr.get("/admin/staff")
    assert resp.status_code == 200
    ids = {item["user_id"] for item in resp.json()["items"]}
    assert str(MANAGER_USER_ID) in ids and str(staff_id) in ids


async def test_staff_can_list_staff(seeded: AsyncSession, fake_redis: FakeRedis) -> None:
    """직원 목록 조회는 STAFF에도 개방(배정 드롭다운용, ADR-0018) — 초대·비활성은 소장 유지."""
    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("STAFF",), user_id=STAFF_ID)
    ) as staff:
        resp = await staff.get("/admin/staff")
    assert resp.status_code == 200
    ids = {item["user_id"] for item in resp.json()["items"]}
    assert str(MANAGER_USER_ID) in ids


async def test_list_staff_includes_decrypted_email(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    """직원 목록에 이메일·이름 표시(ADR-0014 개정·ADR-0018) — PII 부재 행은 None으로 유지."""
    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as mgr:
        invite = await mgr.post(
            "/admin/staff/invite", json={"email": "new-staff@example.com", "name": "김초대"}
        )
        assert invite.status_code == 202
        resp = await mgr.get("/admin/staff")

    assert resp.status_code == 200
    by_email = {item["email"]: item for item in resp.json()["items"]}
    assert "new-staff@example.com" in by_email  # 초대 행은 복호 이메일
    assert by_email["new-staff@example.com"]["status"] == "invited"
    assert by_email["new-staff@example.com"]["name"] == "김초대"  # 초대 시 입력한 이름
    assert None in by_email  # vault 없는 시드 소장 행은 None(행 유지)


async def test_list_staff_includes_decrypted_name(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    """직원 목록에 성명 표시(ADR-0018) — name_enc 복호. PII 부재 행은 None."""
    crypto = _crypto()
    await seeded.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    dek = await crypto.get_dek(seeded, TENANT_ID)
    vault_id = uuid.uuid4()
    staff_id = uuid.uuid4()
    seeded.add(
        PiiVault(
            id=vault_id,
            tenant_id=TENANT_ID,
            email_enc=crypto.encrypt(dek, "named-staff@example.com"),
            name_enc=crypto.encrypt(dek, "홍길동"),
            key_version=1,
        )
    )
    seeded.add(
        User(id=staff_id, tenant_id=TENANT_ID, status="active", pii_ref=vault_id)
    )
    await seeded.flush()
    seeded.add(UserRole(tenant_id=TENANT_ID, user_id=staff_id, role="STAFF"))
    await seeded.flush()

    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as mgr:
        resp = await mgr.get("/admin/staff")

    assert resp.status_code == 200
    by_id = {item["user_id"]: item for item in resp.json()["items"]}
    assert by_id[str(staff_id)]["name"] == "홍길동"
    assert by_id[str(MANAGER_USER_ID)]["name"] is None  # vault 없는 시드 소장 행


# ── 임시 비밀번호 강제 변경 게이트 (부트스트랩 SYS_ADMIN) ─────────────────────


async def _seed_sys_admin(
    session: AsyncSession, crypto: PiiCrypto, email: str, password: str, *, must_change: bool
) -> uuid.UUID:
    dek = await crypto.get_dek(session, TENANT_ID)
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id, tenant_id=TENANT_ID, email_enc=crypto.encrypt(dek, email), key_version=1
        )
    )
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            tenant_id=TENANT_ID,
            login_id=crypto.hmac_hash(email),
            password_hash=hash_password(password),
            status="active",
            email_verified_at=datetime.now(UTC),
            must_change_password=must_change,
            pii_ref=vault_id,
        )
    )
    await session.flush()
    session.add(UserRole(tenant_id=TENANT_ID, user_id=user_id, role="SYS_ADMIN"))
    await session.flush()
    return user_id


async def test_must_change_password_gate_and_flow(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    email = "root@example.com"
    temp = "temp-boot-passphrase"
    new_password = "the-new-strong-passphrase"
    await _seed_sys_admin(seeded, _crypto(), email, temp, must_change=True)

    async with _make_app(seeded, fake_redis, FakeMailer()) as c:
        login = await c.post("/auth/login", json={"email": email, "password": temp})
        assert login.status_code == 200

        # 변경 전 — 다른 엔드포인트 차단.
        blocked = await c.get("/admin/tenants")
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "password_change_required"

        # /me는 허용 + 플래그 노출.
        me = await c.get("/me")
        assert me.json()["must_change_password"] is True

        # 현재 비밀번호 오류 → 401.
        wrong = await c.post(
            "/auth/password-change",
            json={"current_password": "totally-wrong", "new_password": new_password},
        )
        assert wrong.status_code == 401

        # 정상 변경 → 204(세션 재발급).
        changed = await c.post(
            "/auth/password-change",
            json={"current_password": temp, "new_password": new_password},
        )
        assert changed.status_code == 204

        # 변경 후 — SYS_ADMIN 정상 접근 + 플래그 해제.
        after = await c.get("/admin/tenants")
        assert after.status_code == 200
        me2 = await c.get("/me")
        assert me2.json()["must_change_password"] is False


async def test_active_user_without_flag_not_gated(
    seeded: AsyncSession, fake_redis: FakeRedis
) -> None:
    """must_change_password=False 계정은 게이트 없음(회귀 방지)."""
    email = "root2@example.com"
    password = "already-changed-passphrase"
    await _seed_sys_admin(seeded, _crypto(), email, password, must_change=False)
    async with _make_app(seeded, fake_redis, FakeMailer()) as c:
        assert (
            await c.post("/auth/login", json={"email": email, "password": password})
        ).status_code == 200
        assert (await c.get("/admin/tenants")).status_code == 200


# ── H7-6: 계정·단지 수명주기 (FR-ONB-08·12, CRITICAL) ────────────────────────


async def _seed_login_user(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
    password: str,
    role: str = "MANAGER",
) -> uuid.UUID:
    """검증 완료·비밀번호 설정된 로그인 가능 계정을 시드(PII vault 포함)."""
    crypto = _crypto()
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    dek = await crypto.get_dek(session, tenant_id)
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id, tenant_id=tenant_id, email_enc=crypto.encrypt(dek, email), key_version=1
        )
    )
    user_id = uuid.uuid4()
    session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            login_id=crypto.hmac_hash(email),
            password_hash=hash_password(password),
            status="active",
            email_verified_at=datetime.now(UTC),
            pii_ref=vault_id,
        )
    )
    await session.flush()
    session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role=role))
    await session.flush()
    return user_id


async def test_delete_staff_soft_deletes_and_scrubs_pii(
    seeded: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    """삭제 = 소프트 삭제 + PII 비식별 + 세션 revoke(CRITICAL — 평문·해시 잔존 0)."""
    email = "target-staff@example.com"
    target_id = await _seed_login_user(seeded, TENANT_ID, email, "target-staff-pass", role="STAFF")
    sid = await session_store.create(str(TENANT_ID), str(target_id), ["STAFF"], status="active")

    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as mgr:
        resp = await mgr.delete(f"/admin/staff/{target_id}")
        assert resp.status_code == 204
        listed = await mgr.get("/admin/staff")

    user = await seeded.scalar(select(User).where(User.id == target_id))
    assert user is not None
    assert user.deleted_at is not None and user.status == "withdrawn"
    assert user.login_id is None and user.password_hash is None  # 식별자·자격 말소
    vault = await seeded.scalar(select(PiiVault).where(PiiVault.id == user.pii_ref))
    assert vault is not None and vault.email_enc is None  # 암호문도 말소(비식별)
    assert await session_store.get(sid) is None  # 세션 즉시 revoke
    assert all(item["user_id"] != str(target_id) for item in listed.json()["items"])


async def test_delete_other_manager_allowed_self_rejected(
    seeded: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    """소장은 타 소장 삭제 가능(운영자 결정), 자기 자신은 400(CRITICAL)."""
    other = await _seed_login_user(
        seeded, TENANT_ID, "other-mgr@example.com", "other-mgr-pass", role="MANAGER"
    )
    async with _make_app(seeded, fake_redis, FakeMailer(), ctx=_ctx(("MANAGER",))) as mgr:
        assert (await mgr.delete(f"/admin/staff/{MANAGER_USER_ID}")).status_code == 400  # 자신
        assert (await mgr.delete(f"/admin/staff/{other}")).status_code == 204

    user = await seeded.scalar(select(User).where(User.id == other))
    assert user is not None and user.deleted_at is not None


async def test_invite_manager_capacity_one(
    seeded: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    """단지당 소장 1명 — 존재 시 409, SYS_ADMIN이 제거하면 재초대 가능(교체 흐름)."""
    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("SYS_ADMIN",), user_id=SYS_ADMIN_ID)
    ) as c:
        # seed_tenant이 MANAGER를 이미 심었다 → 초대 차단.
        blocked = await c.post(
            f"/admin/tenants/{TENANT_ID}/invite-manager", json={"email": "new@example.com"}
        )
        assert blocked.status_code == 409

        # 목록에 현재 소장 표시.
        listed = await c.get("/admin/tenants")
        row = next(t for t in listed.json()["items"] if t["id"] == str(TENANT_ID))
        assert row["manager"] is not None and row["manager"]["status"] == "active"

        # 소장 제거(소프트 삭제) → 재초대 202.
        assert (await c.delete(f"/admin/tenants/{TENANT_ID}/manager")).status_code == 204
        retry = await c.post(
            f"/admin/tenants/{TENANT_ID}/invite-manager", json={"email": "new@example.com"}
        )
        assert retry.status_code == 202

    manager = await seeded.scalar(select(User).where(User.id == MANAGER_USER_ID))
    assert manager is not None and manager.deleted_at is not None  # 구 소장 비식별 삭제


async def test_delete_tenant_only_when_empty(seeded: AsyncSession, fake_redis: FakeRedis) -> None:
    """빈 단지만 완전 삭제 — 계정 있는 단지는 409(CRITICAL — 데이터 통삭제 방지)."""
    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("SYS_ADMIN",), user_id=SYS_ADMIN_ID)
    ) as c:
        # seed 단지엔 MANAGER 계정 존재 → 409.
        assert (await c.delete(f"/admin/tenants/{TENANT_ID}")).status_code == 409

        # 빈 단지는 204 + 목록에서 사라짐.
        created = await c.post("/admin/tenants", json={"name": "빈단지"})
        empty_id = created.json()["id"]
        assert (await c.delete(f"/admin/tenants/{empty_id}")).status_code == 204
        listed = await c.get("/admin/tenants")
        assert all(t["id"] != empty_id for t in listed.json()["items"])


async def test_tenant_deactivate_blocks_login_and_directory(
    seeded: AsyncSession, fake_redis: FakeRedis, session_store: SessionStore
) -> None:
    """단지 비활성화 → 소속 로그인 403 tenant_inactive + 가입 목록 제외 + 세션 revoke,
    재활성화 → 로그인 복귀(CRITICAL)."""
    email = "tenant-user@example.com"
    password = "tenant-user-pass!"
    user_id = await _seed_login_user(seeded, TENANT_ID, email, password)
    sid = await session_store.create(str(TENANT_ID), str(user_id), ["MANAGER"], status="active")

    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("SYS_ADMIN",), user_id=SYS_ADMIN_ID)
    ) as admin:
        assert (await admin.post(f"/admin/tenants/{TENANT_ID}/deactivate")).status_code == 204

    assert await session_store.get(sid) is None  # 비활성화 즉시 세션 revoke

    async with _make_app(seeded, fake_redis, FakeMailer()) as c:
        login = await c.post("/auth/login", json={"email": email, "password": password})
        assert login.status_code == 403
        assert login.json()["detail"] == "tenant_inactive"
        directory = await c.get("/auth/tenants")
        assert all(t["id"] != str(TENANT_ID) for t in directory.json()["items"])
        signup = await c.post(
            "/auth/signup",
            json={"tenant_id": str(TENANT_ID), "email": "x@example.com", "password": "p" * 12},
        )
        assert signup.status_code == 404  # 비활성 단지 직접 가입도 차단

    async with _make_app(
        seeded, fake_redis, FakeMailer(), ctx=_ctx(("SYS_ADMIN",), user_id=SYS_ADMIN_ID)
    ) as admin:
        assert (await admin.post(f"/admin/tenants/{TENANT_ID}/activate")).status_code == 204

    async with _make_app(seeded, fake_redis, FakeMailer()) as c:
        assert (
            await c.post("/auth/login", json={"email": email, "password": password})
        ).status_code == 200
