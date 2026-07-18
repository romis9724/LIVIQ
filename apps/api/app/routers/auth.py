"""auth — Google OAuth PKCE 로그인·콜백·로그아웃·/me (docs/01 §13, ADR-0011).

콜백은 api가 PKCE·state(CSRF)를 검증하고 sub로 신원만 확인 → Redis 세션 확립,
구글 토큰은 저장하지 않는다. 계정 상태별 분기(신규→온보딩, 그 외→홈, /me가 화면 분기).
"""

from __future__ import annotations

import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.deps import (
    clear_session_cookie,
    get_auth_lookup_session,
    get_session_raw,
    set_session_cookie,
)
from app.oauth import OAuthProvider, generate_pkce, get_oauth_provider
from app.schemas.auth import MeOut
from app.session import SessionData, SessionStore, get_session_store
from liviq_db.models import User, UserRole

router = APIRouter(tags=["auth"])

# 콜백 후 리다이렉트 목적지 — 프론트가 /me로 최종 화면을 분기한다.
_ONBOARDING_PATH = "/onboarding"
_HOME_PATH = "/"


@router.get("/auth/google/login")
async def google_login(
    provider: Annotated[OAuthProvider, Depends(get_oauth_provider)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    verifier, challenge = generate_pkce()
    await session_store.save_oauth_state(state, verifier)
    return RedirectResponse(provider.authorize_url(state, challenge), status_code=302)


@router.get("/auth/google/callback")
async def google_callback(
    code: str,
    state: str,
    provider: Annotated[OAuthProvider, Depends(get_oauth_provider)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
) -> RedirectResponse:
    verifier = await session_store.pop_oauth_state(state)
    if verifier is None:  # state 미상·재사용 → CSRF 방어
        raise HTTPException(status_code=400, detail="state 검증 실패")
    identity = await provider.exchange(code, verifier)

    # 콜백 후 웹 앱으로 되돌릴 베이스 URL(빈 문자열=상대 경로 — api 동일 출처·테스트).
    web_base = get_settings().web_base_url

    # auth_lookup 플래그가 켜진 세션 — users의 login_id 전역 조회만 허용(docs/03 §5).
    user = await session.scalar(
        select(User).where(User.login_id == identity.sub, User.deleted_at.is_(None))
    )
    if user is None:
        sid = await session_store.create_onboarding(identity.sub)
        redirect = RedirectResponse(f"{web_base}{_ONBOARDING_PATH}", status_code=302)
    else:
        # 신원 확정 → 그 tenant_id로 정상 격리 경로 전환 후 역할 조회(§5).
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
        sid = await session_store.create(
            str(user.tenant_id), str(user.id), roles, status=user.status
        )
        redirect = RedirectResponse(f"{web_base}{_HOME_PATH}", status_code=302)
    set_session_cookie(redirect, sid)
    return redirect


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
    """계정 상태 무관 — 온보딩·pending 등 모든 상태에서 화면 분기의 단일 출처."""
    if session.kind == "onboarding":
        return MeOut(kind="onboarding", status="onboarding", tenant_id=None, user_id=None, roles=[])
    return MeOut(
        kind="user",
        status=session.status,
        tenant_id=uuid.UUID(session.tenant_id),
        user_id=uuid.UUID(session.user_id),
        roles=list(session.roles),
    )
