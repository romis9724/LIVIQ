"""staff — 직원 초대·목록·비활성화 (MANAGER 전용, H7-2, ADR-0014).

소장(MANAGER)이 자기 단지에 직원(STAFF)을 초대·관리한다. 초대는 대상 단지에 초대 계정
(status='invited')을 만들고 링크를 메일로 보낸다. 비활성화는 대상이 자기 단지 STAFF일 때만
가능하며 세션을 즉시 revoke한다(재로그인 차단, ADR-0011). 자기 자신·소장은 대상 불가.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_auth_lookup_session, get_tenant_session, require_roles
from app.invites import create_invite
from app.mail import Mailer, get_mailer
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.admin import InviteIn, StaffItem, StaffListOut
from app.session import SessionStore, get_session_store
from liviq_db.models import PiiVault, User, UserRole

router = APIRouter(prefix="/admin/staff", tags=["staff"])

_MANAGER = require_roles("MANAGER")
_STAFF_LIST_ROLES = ("MANAGER", "STAFF")


@router.post("/invite", status_code=202)
async def invite_staff(
    body: InviteIn,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> Response:
    """자기 단지에 직원(STAFF) 초대 — 계정 생성 + 초대 토큰 + 메일. 중복 이메일 409."""
    await create_invite(
        session=session,
        crypto=crypto,
        mailer=mailer,
        tenant_id=ctx.tenant_id,
        email=body.email,
        role="STAFF",
    )
    return Response(status_code=202)


@router.get("", response_model=StaffListOut)
async def list_staff(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
) -> StaffListOut:
    """직원 목록 — STAFF·MANAGER 역할 사용자(생성 순), 이메일 포함(ADR-0014 개정, H7-5).

    이메일은 pii_vault 복호로 채운다 — MANAGER 인가 뒤에서만 반환. 복호 실패는 None(행 유지).
    """
    rows = (
        await session.execute(
            select(User.id, User.status, User.created_at, UserRole.role, PiiVault.email_enc)
            .join(
                UserRole,
                and_(UserRole.user_id == User.id, UserRole.tenant_id == User.tenant_id),
            )
            .outerjoin(
                PiiVault,
                and_(PiiVault.id == User.pii_ref, PiiVault.tenant_id == User.tenant_id),
            )
            .where(
                User.tenant_id == ctx.tenant_id,
                User.deleted_at.is_(None),
                UserRole.role.in_(_STAFF_LIST_ROLES),
            )
            .order_by(User.created_at)
        )
    ).all()

    dek = await crypto.get_dek(session, ctx.tenant_id) if rows else b""

    def decrypt_email(blob: bytes | None) -> str | None:
        if blob is None:
            return None
        try:
            return crypto.decrypt(dek, blob)
        except Exception:  # noqa: BLE001 — 키 교체 등 복호 실패는 행 유지가 우선
            return None

    # 사용자별 역할 집계(등장 순 유지) — 조인이 역할 수만큼 행을 낸다.
    by_user: dict[uuid.UUID, StaffItem] = {}
    for user_id, status, created_at, role, email_enc in rows:
        item = by_user.get(user_id)
        if item is None:
            by_user[user_id] = StaffItem(
                user_id=user_id,
                roles=[role],
                status=status,
                invited_at=created_at,
                email=decrypt_email(email_enc),
            )
        elif role not in item.roles:
            item.roles.append(role)
    return StaffListOut(items=list(by_user.values()))


@router.post("/{user_id}/deactivate", status_code=204)
async def deactivate_staff(
    user_id: uuid.UUID,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> Response:
    """자기 단지 STAFF만 비활성화 + 세션 즉시 revoke. 자기 자신·소장 대상은 400."""
    if user_id == ctx.user_id:
        raise HTTPException(status_code=400, detail="자기 자신은 비활성화할 수 없습니다")
    user = await session.scalar(
        select(User).where(
            User.tenant_id == ctx.tenant_id, User.id == user_id, User.deleted_at.is_(None)
        )
    )
    if user is None:  # 없음·타 단지(RLS 미조회) → 격리 위해 존재 노출 안 함
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    roles = set(
        await session.scalars(
            select(UserRole.role).where(
                UserRole.tenant_id == ctx.tenant_id, UserRole.user_id == user_id
            )
        )
    )
    if "MANAGER" in roles:
        raise HTTPException(status_code=400, detail="소장은 비활성화할 수 없습니다")
    if "STAFF" not in roles:
        raise HTTPException(status_code=400, detail="직원이 아닙니다")

    user.status = "inactive"
    await session.flush()
    # 재로그인 시 inactive가 반영되도록 기존 세션 폐기(ADR-0011).
    await session_store.revoke_all_for_user(str(ctx.tenant_id), str(user_id))
    return Response(status_code=204)
