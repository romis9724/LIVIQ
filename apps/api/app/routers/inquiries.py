"""inquiries — 접수(입주민)·조회·배정·상태(관리자) + 키워드 분류·타임라인 (docs/01 §13).

소유권 불변식(§13.3): 입주민 목록·상세는 `author_user_id` 필터가 쿼리에 박힌다(FR-RES-02 —
세대 공유 아님, 파라미터 우회 불가). 상태 전이·배정은 사람 액션 엔드포인트만 수행(규칙 6·8),
변경마다 inquiry_events append + 작성자 알림 생성(§13.2).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_context, get_tenant_session, require_roles
from app.inquiry_classify import classify_inquiry
from app.schemas.inquiries import (
    AssignIn,
    InquiryCreateIn,
    InquiryEventListOut,
    InquiryEventOut,
    InquiryListOut,
    InquiryOut,
    InquiryStatus,
    StatusChangeIn,
)
from liviq_db.models import Inquiry, InquiryCategory, InquiryEvent, Notification, User, UserRole

router = APIRouter(prefix="/inquiries", tags=["inquiries"])
admin_router = APIRouter(prefix="/admin/inquiries", tags=["inquiries"])

_ADMIN_ROLES = ("MANAGER", "STAFF")
_ASSIGNABLE_ROLES = ("MANAGER", "STAFF")  # H7-2에서 FACILITY 제거(docs/04 §4)
# 상태 머신 전진 순서 — 역행(index 감소)은 MANAGER만(§13.2).
STATUS_ORDER = ("received", "assigned", "in_progress", "done")


def _out(inquiry: Inquiry) -> InquiryOut:
    return InquiryOut.model_validate(inquiry, from_attributes=True)


def _add_event(
    session: AsyncSession,
    inquiry: Inquiry,
    event_type: str,
    *,
    actor_user_id: uuid.UUID | None,
    payload: dict[str, object] | None = None,
) -> None:
    session.add(
        InquiryEvent(
            tenant_id=inquiry.tenant_id,
            inquiry_id=inquiry.id,
            type=event_type,
            actor_user_id=actor_user_id,
            payload=payload,
        )
    )


def _notify_author(session: AsyncSession, inquiry: Inquiry, title: str) -> None:
    """작성자에게 인앱 알림 생성 — 자동 외부발송 아님(ADR-0012)."""
    session.add(
        Notification(
            tenant_id=inquiry.tenant_id,
            user_id=inquiry.author_user_id,
            type="inquiry_status",
            title=title,
            link=f"/inquiries/{inquiry.id}",
        )
    )


async def _get_inquiry(
    session: AsyncSession, tenant_id: uuid.UUID, inquiry_id: uuid.UUID
) -> Inquiry:
    """tenant 소유의 미삭제 민원 — 없으면 404(격리 위해 존재 여부 노출 안 함)."""
    inquiry = await session.scalar(
        select(Inquiry).where(
            Inquiry.id == inquiry_id,
            Inquiry.tenant_id == tenant_id,
            Inquiry.deleted_at.is_(None),
        )
    )
    if inquiry is None:
        raise HTTPException(status_code=404, detail="민원을 찾을 수 없음")
    return inquiry


def _is_admin(ctx: RequestContext) -> bool:
    return not frozenset(_ADMIN_ROLES).isdisjoint(ctx.roles)


# ── 입주민 ────────────────────────────────────────────────────────────────


@router.post("", response_model=InquiryOut, status_code=201)
async def create_inquiry(
    ctx: Annotated[RequestContext, Depends(require_roles("RESIDENT"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    body: InquiryCreateIn,
) -> InquiryOut:
    household_id = await session.scalar(
        select(User.household_id).where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id)
    )
    if household_id is None:
        raise HTTPException(status_code=422, detail="세대 미배정 — 접수 불가")

    categories = [
        (cid, name)
        for cid, name in (
            await session.execute(
                select(InquiryCategory.id, InquiryCategory.name).where(
                    InquiryCategory.tenant_id == ctx.tenant_id
                )
            )
        ).all()
    ]
    classification = classify_inquiry(body.title, body.body, categories)

    inquiry = Inquiry(
        tenant_id=ctx.tenant_id,
        household_id=household_id,
        author_user_id=ctx.user_id,
        category_id=body.category_id,
        title=body.title,
        body=body.body,
        status="received",
        ai_priority=classification.priority,
        ai_suggested_category_id=classification.suggested_category_id,
    )
    session.add(inquiry)
    await session.flush()

    _add_event(session, inquiry, "created", actor_user_id=ctx.user_id)
    _add_event(
        session,
        inquiry,
        "ai_classified",
        actor_user_id=None,
        payload={
            "priority": classification.priority,
            "suggested_category_id": (
                str(classification.suggested_category_id)
                if classification.suggested_category_id
                else None
            ),
        },
    )
    await session.flush()
    return _out(inquiry)


@router.get("", response_model=InquiryListOut)
async def list_my_inquiries(
    ctx: Annotated[RequestContext, Depends(require_roles("RESIDENT"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> InquiryListOut:
    # 소유권 필터가 쿼리에 박힘 — 파라미터로 우회 불가(§13.3, FR-RES-02).
    rows = await session.scalars(
        select(Inquiry)
        .where(
            Inquiry.tenant_id == ctx.tenant_id,
            Inquiry.author_user_id == ctx.user_id,
            Inquiry.deleted_at.is_(None),
        )
        .order_by(Inquiry.created_at.desc())
    )
    return InquiryListOut(items=[_out(row) for row in rows])


@router.get("/{inquiry_id}", response_model=InquiryOut)
async def get_inquiry(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    inquiry_id: uuid.UUID,
) -> InquiryOut:
    inquiry = await _get_inquiry(session, ctx.tenant_id, inquiry_id)
    if inquiry.author_user_id != ctx.user_id and not _is_admin(ctx):
        raise HTTPException(status_code=404, detail="민원을 찾을 수 없음")
    return _out(inquiry)


@router.get("/{inquiry_id}/events", response_model=InquiryEventListOut)
async def list_inquiry_events(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    inquiry_id: uuid.UUID,
) -> InquiryEventListOut:
    inquiry = await _get_inquiry(session, ctx.tenant_id, inquiry_id)
    if inquiry.author_user_id != ctx.user_id and not _is_admin(ctx):
        raise HTTPException(status_code=404, detail="민원을 찾을 수 없음")
    rows = await session.scalars(
        select(InquiryEvent)
        .where(
            InquiryEvent.tenant_id == ctx.tenant_id,
            InquiryEvent.inquiry_id == inquiry_id,
        )
        .order_by(InquiryEvent.created_at)
    )
    return InquiryEventListOut(
        items=[InquiryEventOut.model_validate(row, from_attributes=True) for row in rows]
    )


# ── 관리자 ────────────────────────────────────────────────────────────────


@admin_router.get("", response_model=InquiryListOut)
async def list_admin_inquiries(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    status: Annotated[InquiryStatus | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query()] = None,
) -> InquiryListOut:
    stmt = select(Inquiry).where(Inquiry.tenant_id == ctx.tenant_id, Inquiry.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(Inquiry.status == status)
    if category_id is not None:
        stmt = stmt.where(Inquiry.category_id == category_id)
    rows = await session.scalars(stmt.order_by(Inquiry.created_at.desc()))
    return InquiryListOut(items=[_out(row) for row in rows])


@admin_router.post("/{inquiry_id}/assign", response_model=InquiryOut)
async def assign_inquiry(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    inquiry_id: uuid.UUID,
    body: AssignIn,
) -> InquiryOut:
    inquiry = await _get_inquiry(session, ctx.tenant_id, inquiry_id)

    # 배정 대상은 같은 단지의 처리 역할 보유자만(§13.2).
    assignable = await session.scalar(
        select(UserRole.id).where(
            UserRole.tenant_id == ctx.tenant_id,
            UserRole.user_id == body.assignee_user_id,
            UserRole.role.in_(_ASSIGNABLE_ROLES),
        )
    )
    if assignable is None:
        raise HTTPException(status_code=422, detail="배정 불가 — 처리 역할이 아닌 사용자")

    inquiry.assignee_user_id = body.assignee_user_id
    if inquiry.status == "received":
        inquiry.status = "assigned"
    _add_event(
        session,
        inquiry,
        "assigned",
        actor_user_id=ctx.user_id,
        payload={"assignee_user_id": str(body.assignee_user_id)},
    )
    _notify_author(session, inquiry, "민원 담당자가 배정되었습니다")
    await session.flush()
    return _out(inquiry)


@admin_router.post("/{inquiry_id}/status", response_model=InquiryOut)
async def change_inquiry_status(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    inquiry_id: uuid.UUID,
    body: StatusChangeIn,
) -> InquiryOut:
    inquiry = await _get_inquiry(session, ctx.tenant_id, inquiry_id)
    current = STATUS_ORDER.index(inquiry.status)
    target = STATUS_ORDER.index(body.status)
    if target == current:
        raise HTTPException(status_code=422, detail=f"이미 {body.status} 상태")
    if target < current and "MANAGER" not in ctx.roles:
        raise HTTPException(status_code=403, detail="상태 역행은 관리자만 가능")

    previous = inquiry.status
    inquiry.status = body.status
    _add_event(
        session,
        inquiry,
        "status_changed",
        actor_user_id=ctx.user_id,
        payload={"from": previous, "to": body.status},
    )
    _notify_author(session, inquiry, f"민원 상태가 '{body.status}'(으)로 변경되었습니다")
    await session.flush()
    return _out(inquiry)
