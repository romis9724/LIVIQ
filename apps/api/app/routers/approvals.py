"""approvals — 가입 승인/거절 + 대기 목록 (docs/01 §13, docs/06 §2).

MANAGER 전용. 상태 전환(active/rejected) 시 대상 세션을 즉시 revoke(재로그인 시 반영,
ADR-0011)하고 인앱 알림을 생성한다. 이름은 복호화 후 마스킹만 노출(원문 금지, docs/06 §6).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.approvals import ApprovalListOut, ApprovalOut, RejectIn
from app.session import SessionStore, get_session_store
from liviq_db.models import Building, Household, Notification, PiiVault, User, UserRole

router = APIRouter(prefix="/admin/approvals", tags=["approvals"])

_MANAGER = require_roles("MANAGER")


def mask_name(name: str) -> str:
    """입주민 이름 마스킹 — 2자: 첫 자+*, 3자+: 첫 자+*+끝 자 (docs/06 §6)."""
    if len(name) <= 1:
        return "*"
    if len(name) == 2:
        return f"{name[0]}*"
    return f"{name[0]}*{name[-1]}"


@router.get("", response_model=ApprovalListOut)
async def list_approvals(
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    status: str = "pending",
) -> ApprovalListOut:
    rows = (
        await session.execute(
            select(
                User.id,
                User.household_id,
                User.roster_matched,
                User.created_at,
                PiiVault.name_enc,
                Building.name,
                Household.floor,
                Household.unit_no,
            )
            .outerjoin(PiiVault, PiiVault.id == User.pii_ref)
            .outerjoin(Household, Household.id == User.household_id)
            .outerjoin(Building, Building.id == Household.building_id)
            .where(
                User.tenant_id == ctx.tenant_id,
                User.status == status,
                User.deleted_at.is_(None),
            )
            .order_by(User.created_at)
        )
    ).all()

    dek = await crypto.get_dek(session, ctx.tenant_id)
    items = [
        ApprovalOut(
            user_id=user_id,
            name_masked=mask_name(crypto.decrypt(dek, name_enc)) if name_enc else "*",
            roster_matched=roster_matched,
            mismatch_reason=(
                None
                if roster_matched
                else await _mismatch_reason(session, ctx.tenant_id, household_id)
            ),
            building_name=building_name,
            floor=floor,
            unit_no=unit_no,
            requested_at=created_at,
        )
        for (
            user_id,
            household_id,
            roster_matched,
            created_at,
            name_enc,
            building_name,
            floor,
            unit_no,
        ) in rows
    ]
    return ApprovalListOut(items=items)


async def _mismatch_reason(
    session: AsyncSession, tenant_id: uuid.UUID, household_id: uuid.UUID | None
) -> str:
    """명부 불일치 사유(H7-9) — 소장이 후속 확인(전화 등)을 판단할 근거.

    명부 행 = 명부 출신 사용자(login_id 없음·pre_registered). 소진(soft delete)은 가입 완료.
    """
    if household_id is None:
        return "no_household_roster"
    rows = (
        await session.execute(
            select(User.deleted_at).where(
                User.tenant_id == tenant_id,
                User.household_id == household_id,
                User.status == "pre_registered",
                User.login_id.is_(None),
            )
        )
    ).all()
    if not rows:
        return "no_household_roster"
    if all(deleted_at is not None for (deleted_at,) in rows):
        return "all_consumed"
    return "person_mismatch"


@router.post("/{user_id}/approve", status_code=204)
async def approve(
    user_id: uuid.UUID,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    user = await _get_pending(session, ctx.tenant_id, user_id)
    user.status = "active"
    user.approved_by = ctx.user_id
    user.approved_at = datetime.datetime.now(datetime.UTC)
    await _grant_resident(session, ctx.tenant_id, user_id)
    session.add(
        Notification(
            tenant_id=ctx.tenant_id,
            user_id=user_id,
            type="approval",
            title="가입이 승인되었습니다",
        )
    )
    await session.flush()
    # 재로그인 시 active·역할이 세션에 반영되도록 기존 세션 폐기(docs/06 §2, ADR-0011).
    await session_store.revoke_all_for_user(str(ctx.tenant_id), str(user_id))


@router.post("/{user_id}/reject", status_code=204)
async def reject(
    user_id: uuid.UUID,
    body: RejectIn,
    ctx: Annotated[RequestContext, Depends(_MANAGER)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
) -> None:
    user = await _get_pending(session, ctx.tenant_id, user_id)
    user.status = "rejected"
    user.rejected_reason = body.reason
    session.add(
        Notification(
            tenant_id=ctx.tenant_id,
            user_id=user_id,
            type="approval",
            title="가입이 거절되었습니다",
            body=body.reason,
        )
    )
    await session.flush()
    await session_store.revoke_all_for_user(str(ctx.tenant_id), str(user_id))


async def _get_pending(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    """대상 사용자 조회 — 교차 tenant는 RLS로 자동 미조회(404). pending 아니면 409."""
    user = await session.scalar(
        select(User).where(
            User.tenant_id == tenant_id, User.id == user_id, User.deleted_at.is_(None)
        )
    )
    if user is None:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다")
    if user.status != "pending":
        raise HTTPException(status_code=409, detail=f"대기 중이 아닙니다: {user.status}")
    return user


async def _grant_resident(session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    existing = await session.scalar(
        select(UserRole.id).where(
            UserRole.tenant_id == tenant_id,
            UserRole.user_id == user_id,
            UserRole.role == "RESIDENT",
        )
    )
    if existing is None:
        session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role="RESIDENT"))
