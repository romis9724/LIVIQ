"""admin_tenants — 단지 생성·목록 + 소장 초대 (SYS_ADMIN 전용, H7-2, ADR-0014).

SYS_ADMIN은 시스템 테넌트 소속으로 단지 생성·소장 초대만 수행한다 — 어떤 단지 콘텐츠에도
접근하지 않는다(규칙 4·비열람 원칙, 콘텐츠 라우터의 require_roles에 SYS_ADMIN 미포함).
소장 초대는 대상 단지에 초대 계정(status='invited', role MANAGER)을 만들고 링크를 메일로 보낸다.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import SYSTEM_TENANT_ID
from app.deps import RequestContext, get_auth_lookup_session, get_tenant_session, require_roles
from app.invites import create_invite
from app.mail import Mailer, get_mailer
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.admin import (
    InviteIn,
    TenantCreateIn,
    TenantItem,
    TenantListOut,
    TenantOut,
)
from liviq_db.models import Tenant

router = APIRouter(prefix="/admin/tenants", tags=["admin-tenants"])

_SYS_ADMIN = require_roles("SYS_ADMIN")


@router.post("", status_code=201, response_model=TenantOut)
async def create_tenant(
    body: TenantCreateIn,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> TenantOut:
    """단지 생성. tenants는 RLS 예외라 SYS_ADMIN(시스템 테넌트 컨텍스트)이 전역 INSERT 가능."""
    tenant = Tenant(name=body.name, status="active")
    session.add(tenant)
    await session.flush()
    return TenantOut(id=tenant.id, name=tenant.name)


@router.get("", response_model=TenantListOut)
async def list_tenants(
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> TenantListOut:
    """단지 목록(생성 순). 시스템 테넌트는 제외 — 소장 초대 대상이 아니다."""
    rows = (
        await session.execute(
            select(Tenant.id, Tenant.name, Tenant.created_at)
            .where(Tenant.id != SYSTEM_TENANT_ID)
            .order_by(Tenant.created_at)
        )
    ).all()
    return TenantListOut(
        items=[
            TenantItem(id=tid, name=name, created_at=created_at) for tid, name, created_at in rows
        ]
    )


@router.post("/{tenant_id}/invite-manager", status_code=202)
async def invite_manager(
    tenant_id: uuid.UUID,
    body: InviteIn,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> Response:
    """대상 단지에 소장(MANAGER) 초대 — 계정 생성 + 초대 토큰 + 메일. 중복 이메일 409."""
    if tenant_id == SYSTEM_TENANT_ID or (
        await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None
    ):
        raise HTTPException(status_code=404, detail="단지를 찾을 수 없습니다")
    await create_invite(
        session=session,
        crypto=crypto,
        mailer=mailer,
        tenant_id=tenant_id,
        email=body.email,
        role="MANAGER",
    )
    return Response(status_code=202)
