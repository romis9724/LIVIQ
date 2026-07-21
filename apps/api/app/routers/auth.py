"""auth — 자체 이메일+비밀번호 가입·로그인·검증·재설정·로그아웃·/me (ADR-0014, docs/06 §2).

이메일은 PII다 — 평문 컬럼 금지(pii_vault.email_enc 암호화 + login_id는 keyed HMAC 해시).
검증 전 로그인 불가(가입 메일 필수). 토큰은 1회용(auth_tokens, 원문은 URL로만). 세션은
ADR-0011 그대로(Redis 서버 세션 + httpOnly 쿠키, 상태 전환 시 즉시 revoke).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_tokens
from app.config import get_settings
from app.deps import (
    clear_session_cookie,
    get_auth_lookup_session,
    get_session_raw,
    set_session_cookie,
)
from app.mail import Mailer, get_mailer
from app.password import dummy_verify, hash_password, verify_password
from app.pii import PiiCrypto, get_pii_crypto
from app.rate_limit import check_rate_limit
from app.schemas.auth import (
    LoginIn,
    LoginOut,
    MeOut,
    PasswordResetConfirmIn,
    PasswordResetIn,
    SignupIn,
    SignupOut,
)
from app.session import SessionData, SessionStore, get_redis, get_session_store
from liviq_db.models import PiiVault, Tenant, User, UserRole

logger = logging.getLogger("app.auth")
router = APIRouter(tags=["auth"])

# 무차별 대입 방어(ADR-0014) — 이메일 해시별 분당 상한. 로그인·재설정 각각.
LOGIN_RATE_PER_MIN = 5
RESET_RATE_PER_MIN = 3
# 계정 존재 여부를 노출하지 않도록 로그인 실패 메시지는 단일화(규칙 4·docs/06 §2).
_INVALID_CREDENTIALS = "이메일 또는 비밀번호가 올바르지 않습니다"


def _email_hash(crypto: PiiCrypto, email: str) -> str:
    """이메일 정규화(소문자·NFC·공백제거) 후 keyed HMAC — login_id 조회 키(§6)."""
    return crypto.hmac_hash(_normalize_email(email))


def _normalize_email(email: str) -> str:
    """저장·해시에 쓰는 정규형(소문자). hmac_hash가 NFC·strip을 마저 수행한다."""
    return email.strip().lower()


@router.post("/auth/signup", status_code=201, response_model=SignupOut)
async def signup(
    body: SignupIn,
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> SignupOut:
    """단지별 가입 링크(tenant_id) + 이메일 + 비밀번호. 검증 메일 발송 후 201.

    발송 실패는 예외 전파 → 트랜잭션 롤백 + 500(계정이 검증 불가 상태로 남지 않게).
    """
    settings = get_settings()
    email_norm = _normalize_email(body.email)
    email_hash = crypto.hmac_hash(email_norm)

    # 단지 존재 검증 — tenants는 RLS 예외라 auth_lookup 세션에서 전역 조회 가능.
    if await session.scalar(select(Tenant.id).where(Tenant.id == body.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="단지를 찾을 수 없습니다")

    # 이메일 전역 중복 — users의 auth_lookup permissive SELECT(파일럿 단일 단지 유니크).
    if (
        await session.scalar(
            select(User.id).where(User.login_id == email_hash, User.deleted_at.is_(None))
        )
        is not None
    ):
        raise HTTPException(status_code=409, detail="이미 가입된 이메일입니다")

    # tenant 컨텍스트 전환 후 정상 격리 경로로 계정·PII 생성(§5).
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(body.tenant_id))
    )
    dek = await crypto.get_dek(session, body.tenant_id)
    vault = PiiVault(
        tenant_id=body.tenant_id,
        email_enc=crypto.encrypt(dek, email_norm),
        key_version=1,
    )
    session.add(vault)
    await session.flush()
    user = User(
        tenant_id=body.tenant_id,
        login_id=email_hash,
        password_hash=hash_password(body.password),
        status="registered",  # 가입 완료·프로필 미제출(온보딩 필요 신호)
        pii_ref=vault.id,
    )
    session.add(user)
    await session.flush()

    raw = await auth_tokens.issue(
        session, body.tenant_id, user.id, "verify_email", auth_tokens.VERIFY_TTL
    )
    link = f"{settings.api_base_url}/auth/verify-email?token={raw}"
    await run_in_threadpool(
        mailer.send,
        email_norm,
        "[LIVIQ] 이메일 인증",
        f"아래 링크로 이메일을 인증해 주세요(24시간 유효):\n{link}",
    )
    return SignupOut(user_id=user.id)


@router.post("/auth/login", response_model=LoginOut)
async def login(
    body: LoginIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> LoginOut:
    """이메일+비밀번호 → 세션 확립. 검증 전(email_verified_at NULL) 계정은 403."""
    email_hash = _email_hash(crypto, body.email)
    await check_rate_limit(
        redis, user_id=email_hash, tenant_id="", user_limit=LOGIN_RATE_PER_MIN, tenant_limit=0
    )

    user = await session.scalar(
        select(User).where(User.login_id == email_hash, User.deleted_at.is_(None))
    )
    # 계정 부재·비밀번호 미설정 → 동일 401(존재 노출 금지). 부재 시 dummy로 타이밍 균등화.
    if user is None or user.password_hash is None:
        dummy_verify()
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)
    if user.email_verified_at is None:
        raise HTTPException(status_code=403, detail="email_not_verified")

    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(user.tenant_id))
    )
    roles = list(
        await session.scalars(
            select(UserRole.role).where(
                UserRole.tenant_id == user.tenant_id, UserRole.user_id == user.id
            )
        )
    )
    sid = await session_store.create(str(user.tenant_id), str(user.id), roles, status=user.status)
    set_session_cookie(response, sid)
    return LoginOut(status=user.status)


@router.get("/auth/verify-email")
async def verify_email(
    token: str,
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
) -> RedirectResponse:
    """검증 링크 클릭 → email_verified_at 기록·토큰 소진. 실패 시 로그인 화면으로 안내."""
    web_base = get_settings().web_base_url
    token_obj = await auth_tokens.consume(session, token, "verify_email")
    if token_obj is None:  # 없음·만료·이미 사용
        return RedirectResponse(f"{web_base}/login?verify_error=1", status_code=302)

    # 토큰의 tenant_id로 컨텍스트 전환 후 정상 격리 경로에서 소진·검증 기록.
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(token_obj.tenant_id))
    )
    user = await session.scalar(select(User).where(User.id == token_obj.user_id))
    now = datetime.now(UTC)
    if user is not None and user.email_verified_at is None:
        user.email_verified_at = now
    token_obj.used_at = now
    await session.flush()
    return RedirectResponse(f"{web_base}/login?verified=1", status_code=302)


@router.post("/auth/password-reset", status_code=202)
async def password_reset(
    body: PasswordResetIn,
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> Response:
    """재설정 링크 요청. 계정 존재·검증 여부와 무관하게 항상 202(존재 노출 금지)."""
    settings = get_settings()
    email_hash = _email_hash(crypto, body.email)
    await check_rate_limit(
        redis, user_id=email_hash, tenant_id="", user_limit=RESET_RATE_PER_MIN, tenant_limit=0
    )
    user = await session.scalar(
        select(User).where(User.login_id == email_hash, User.deleted_at.is_(None))
    )
    if user is not None and user.email_verified_at is not None:
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(user.tenant_id))
        )
        raw = await auth_tokens.issue(
            session, user.tenant_id, user.id, "reset_password", auth_tokens.RESET_TTL
        )
        link = f"{settings.web_base_url}/reset-password?token={raw}"
        try:
            await run_in_threadpool(
                mailer.send,
                _normalize_email(body.email),
                "[LIVIQ] 비밀번호 재설정",
                f"아래 링크에서 비밀번호를 재설정하세요(1시간 유효):\n{link}",
            )
        except Exception:  # noqa: BLE001 — 발송 실패도 202로 은폐(토큰은 미사용 만료)
            logger.warning("password-reset 메일 발송 실패", exc_info=True)
    return Response(status_code=202)


@router.post("/auth/password-reset/confirm", status_code=204)
async def password_reset_confirm(
    body: PasswordResetConfirmIn,
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> Response:
    """토큰 + 새 비밀번호 → 교체 + 해당 사용자 전 세션 revoke(탈취 대비)."""
    token_obj = await auth_tokens.consume(session, body.token, "reset_password")
    if token_obj is None:
        raise HTTPException(status_code=400, detail="토큰이 유효하지 않습니다")

    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(token_obj.tenant_id))
    )
    user = await session.scalar(select(User).where(User.id == token_obj.user_id))
    if user is None:  # pragma: no cover — 토큰은 있는데 사용자 소멸(FK CASCADE로 드묾)
        raise HTTPException(status_code=400, detail="토큰이 유효하지 않습니다")
    user.password_hash = hash_password(body.new_password)
    token_obj.used_at = datetime.now(UTC)
    await session.flush()
    await session_store.revoke_all_for_user(str(token_obj.tenant_id), str(token_obj.user_id))
    return Response(status_code=204)


@router.post("/auth/logout", status_code=204)
async def logout(
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    liviq_session: Annotated[str | None, Cookie()] = None,
) -> Response:
    """멱등 — 쿠키 유무와 무관하게 204. 쿠키 있으면 세션 revoke + 쿠키 제거."""
    if liviq_session:
        await session_store.revoke(liviq_session)
    response = Response(status_code=204)
    clear_session_cookie(response)
    return response


@router.get("/me", response_model=MeOut)
async def me(session: Annotated[SessionData, Depends(get_session_raw)]) -> MeOut:
    """계정 상태 무관 — registered·pending 등 모든 상태의 화면 분기 단일 출처."""
    return MeOut(
        status=session.status,
        tenant_id=uuid.UUID(session.tenant_id),
        user_id=uuid.UUID(session.user_id),
        roles=list(session.roles),
    )
