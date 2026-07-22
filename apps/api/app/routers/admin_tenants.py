"""admin_tenants — 단지 생성·목록·수명주기 + 소장 초대/제거 (SYS_ADMIN 전용, H7-2·H7-6).

SYS_ADMIN은 시스템 테넌트 소속으로 단지·소장 수명주기만 관리한다 — 어떤 단지 콘텐츠에도
접근하지 않는다(규칙 4·비열람 원칙, 콘텐츠 라우터의 require_roles에 SYS_ADMIN 미포함).
H7-6(FR-ONB-08·12): 단지당 소장 1명(초대 409), 소장 제거(소프트 삭제+PII 비식별),
빈 단지만 완전 삭제, 운영 단지는 비활성화/재활성화(소속 로그인 차단·세션 revoke).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts import soft_delete_user
from app.codes_seed import seed_default_codes
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
    TenantManagerItem,
    TenantOut,
)
from app.session import SessionStore, get_session_store
from liviq_db.models import Document, Inquiry, Notice, PiiVault, Tenant, User, UserRole

router = APIRouter(prefix="/admin/tenants", tags=["admin-tenants"])

_SYS_ADMIN = require_roles("SYS_ADMIN")


async def _require_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    """시스템 테넌트·부재는 동일 404 — 존재 노출 없이 차단."""
    tenant = (
        None
        if tenant_id == SYSTEM_TENANT_ID
        else await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="단지를 찾을 수 없습니다")
    return tenant


async def _managers_of(session: AsyncSession, tenant_id: uuid.UUID) -> list[User]:
    """단지의 비삭제 MANAGER 사용자(생성 순). auth_lookup 세션 전제(전역 SELECT)."""
    return list(
        await session.scalars(
            select(User)
            .join(UserRole, and_(UserRole.user_id == User.id, UserRole.tenant_id == User.tenant_id))
            .where(
                User.tenant_id == tenant_id,
                User.deleted_at.is_(None),
                UserRole.role == "MANAGER",
            )
            .order_by(User.created_at)
        )
    )


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
    # 기본 공통 코드 시드(규칙 8 — 액션은 코드). 이후 tenant 컨텍스트는 새 단지로 전환됨.
    await seed_default_codes(session, tenant.id)
    return TenantOut(id=tenant.id, name=tenant.name)


@router.get("", response_model=TenantListOut)
async def list_tenants(
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
) -> TenantListOut:
    """단지 목록(생성 순) — 상태·현재 소장(이메일·상태) 포함(H7-6). 시스템 테넌트 제외.

    소장 이메일은 단지별 tenant 컨텍스트 전환 후 pii_vault 복호 — SYS_ADMIN에게
    노출되는 건 자신이 초대한 소장 이메일뿐(단지 콘텐츠 비열람 원칙 유지).
    """
    tenants = list(
        await session.scalars(
            select(Tenant).where(Tenant.id != SYSTEM_TENANT_ID).order_by(Tenant.created_at)
        )
    )

    items: list[TenantItem] = []
    for tenant in tenants:
        managers = await _managers_of(session, tenant.id)
        manager_item: TenantManagerItem | None = None
        if managers:
            head = managers[0]
            email: str | None = None
            if head.pii_ref is not None:
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)").bindparams(
                        t=str(tenant.id)
                    )
                )
                enc = await session.scalar(
                    select(PiiVault.email_enc).where(
                        PiiVault.id == head.pii_ref, PiiVault.tenant_id == tenant.id
                    )
                )
                if enc is not None:
                    try:
                        dek = await crypto.get_dek(session, tenant.id)
                        email = crypto.decrypt(dek, enc)
                    except Exception:  # noqa: BLE001 — 복호 실패는 미기록 표시
                        email = None
            manager_item = TenantManagerItem(user_id=head.id, email=email, status=head.status)
        items.append(
            TenantItem(
                id=tenant.id,
                name=tenant.name,
                created_at=tenant.created_at,
                status=tenant.status,
                manager=manager_item,
            )
        )
    return TenantListOut(items=items)


@router.post("/{tenant_id}/invite-manager", status_code=202)
async def invite_manager(
    tenant_id: uuid.UUID,
    body: InviteIn,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> Response:
    """소장(MANAGER) 초대 — 단지당 1명(H7-6). 이미 있으면(활성·초대중) 409."""
    tenant = await _require_tenant(session, tenant_id)
    if tenant.status != "active":
        raise HTTPException(status_code=409, detail="비활성화된 단지에는 초대할 수 없습니다")
    if await _managers_of(session, tenant_id):
        raise HTTPException(
            status_code=409,
            detail="이미 소장이 있습니다. 교체하려면 기존 소장을 먼저 제거하세요.",
        )
    await create_invite(
        session=session,
        crypto=crypto,
        mailer=mailer,
        tenant_id=tenant_id,
        email=body.email,
        role="MANAGER",
    )
    return Response(status_code=202)


@router.delete("/{tenant_id}/manager", status_code=204)
async def remove_manager(
    tenant_id: uuid.UUID,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> Response:
    """현재 소장 삭제(소프트 삭제+PII 비식별) — 소장 교체·오초대 해소의 escape hatch(H7-6)."""
    await _require_tenant(session, tenant_id)
    managers = await _managers_of(session, tenant_id)
    if not managers:
        raise HTTPException(status_code=404, detail="소장이 없습니다")
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    for manager in managers:  # 정원 1이 정상 — 과거 데이터의 복수 소장도 함께 정리
        await soft_delete_user(session, session_store, manager)
    return Response(status_code=204)


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(
    tenant_id: uuid.UUID,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
) -> Response:
    """빈 단지만 완전 삭제(H7-6) — 비삭제 계정 또는 콘텐츠가 있으면 409.

    잘못 생성한 단지 정리 용도. 운영 중 단지의 파기는 보존기간 정책과 함께 Phase 2.
    """
    tenant = await _require_tenant(session, tenant_id)

    user_count = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
    )
    if user_count and user_count > 0:
        raise HTTPException(status_code=409, detail="계정이 있는 단지는 삭제할 수 없습니다")

    # 콘텐츠 존재 검사 — 대표 테이블(문서·민원·공지). RLS 우회 없이 tenant 컨텍스트로 조회.
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    for model in (Document, Inquiry, Notice):
        row_count = await session.scalar(
            select(func.count()).select_from(model).where(model.tenant_id == tenant_id)
        )
        if row_count and row_count > 0:
            raise HTTPException(status_code=409, detail="데이터가 있는 단지는 삭제할 수 없습니다")

    await session.delete(tenant)  # 종속 행은 FK ON DELETE CASCADE
    await session.flush()
    return Response(status_code=204)


@router.post("/{tenant_id}/deactivate", status_code=204)
async def deactivate_tenant(
    tenant_id: uuid.UUID,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> Response:
    """단지 비활성화 — 소속 계정 로그인 403 + 가입 단지 목록 제외 + 전 세션 revoke(H7-6)."""
    tenant = await _require_tenant(session, tenant_id)
    tenant.status = "inactive"
    await session.flush()
    user_ids = await session.scalars(
        select(User.id).where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
    )
    for user_id in user_ids:
        await session_store.revoke_all_for_user(str(tenant_id), str(user_id))
    return Response(status_code=204)


@router.post("/{tenant_id}/activate", status_code=204)
async def activate_tenant(
    tenant_id: uuid.UUID,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_auth_lookup_session)],
) -> Response:
    """단지 재활성화 — 로그인·가입 목록 복귀(H7-6)."""
    tenant = await _require_tenant(session, tenant_id)
    tenant.status = "active"
    await session.flush()
    return Response(status_code=204)
