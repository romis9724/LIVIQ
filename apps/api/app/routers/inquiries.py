"""inquiries — 접수(입주민)·조회·배정·상태·답변/피드백(관리자·입주민) + 타임라인 (docs/01 §13).

소유권 불변식(§13.3): 입주민 목록·상세는 `author_user_id` 필터가 쿼리에 박힌다(FR-RES-02 —
세대 공유 아님, 파라미터 우회 불가). 상태 전이·배정·답변은 사람 액션 엔드포인트만 수행(규칙 6·8),
변경마다 inquiry_events append + 알림 생성(§13.2). 분류는 공통 코드 그룹 INQUIRY_CATEGORY이며
AI 개입은 없다(ADR-0018).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.code_refs import validate_category_code
from app.deps import RequestContext, get_context, get_tenant_session, require_roles
from app.schemas.inquiries import (
    AssignIn,
    CommentIn,
    InquiryCategoryListOut,
    InquiryCategoryOut,
    InquiryCreateIn,
    InquiryEventListOut,
    InquiryEventOut,
    InquiryListOut,
    InquiryOut,
    InquiryStatus,
    PriorityIn,
    StatusChangeIn,
)
from liviq_db.models import Code, CodeGroup, Inquiry, InquiryEvent, Notification, User, UserRole

router = APIRouter(prefix="/inquiries", tags=["inquiries"])
admin_router = APIRouter(prefix="/admin/inquiries", tags=["inquiries"])

_ADMIN_ROLES = ("MANAGER", "STAFF")
_ASSIGNABLE_ROLES = ("MANAGER", "STAFF")  # H7-2에서 FACILITY 제거(docs/04 §4)
_INQUIRY_CATEGORY_GROUP = "INQUIRY_CATEGORY"
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


def _notify_assignee(session: AsyncSession, inquiry: Inquiry, title: str) -> None:
    """담당자에게 인앱 알림 생성 — 미배정이면 skip."""
    if inquiry.assignee_user_id is None:
        return
    session.add(
        Notification(
            tenant_id=inquiry.tenant_id,
            user_id=inquiry.assignee_user_id,
            type="inquiry_status",
            title=title,
            link=f"/admin/inquiries/{inquiry.id}",
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


async def _reply_count(session: AsyncSession, inquiry: Inquiry) -> int:
    """민원의 담당자 답변(comment·kind=reply) 이벤트 수 — 완료 게이트용(ADR-0018)."""
    return await session.scalar(
        select(func.count())
        .select_from(InquiryEvent)
        .where(
            InquiryEvent.tenant_id == inquiry.tenant_id,
            InquiryEvent.inquiry_id == inquiry.id,
            InquiryEvent.type == "comment",
            InquiryEvent.payload["kind"].astext == "reply",
        )
    ) or 0


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

    if body.category_code_id is not None:
        await validate_category_code(
            session, ctx.tenant_id, body.category_code_id, _INQUIRY_CATEGORY_GROUP
        )

    inquiry = Inquiry(
        tenant_id=ctx.tenant_id,
        household_id=household_id,
        author_user_id=ctx.user_id,
        category_code_id=body.category_code_id,
        title=body.title,
        body=body.body,
        status="received",
        priority=None,
    )
    session.add(inquiry)
    await session.flush()

    _add_event(session, inquiry, "created", actor_user_id=ctx.user_id)
    await session.flush()
    return _out(inquiry)


@router.get("/categories", response_model=InquiryCategoryListOut)
async def list_inquiry_categories(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> InquiryCategoryListOut:
    """접수 시 선택할 민원 분류(INQUIRY_CATEGORY active 코드, sort_order 순) — 입주민 이상 조회."""
    rows = (
        await session.execute(
            select(Code.id, Code.label)
            .join(
                CodeGroup,
                (Code.group_id == CodeGroup.id) & (Code.tenant_id == CodeGroup.tenant_id),
            )
            .where(
                Code.tenant_id == ctx.tenant_id,
                CodeGroup.group_key == _INQUIRY_CATEGORY_GROUP,
                Code.active.is_(True),
            )
            .order_by(Code.sort_order)
        )
    ).all()
    return InquiryCategoryListOut(
        items=[InquiryCategoryOut(id=cid, label=label) for cid, label in rows]
    )


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


@router.post("/{inquiry_id}/comments", response_model=InquiryOut)
async def add_inquiry_feedback(
    ctx: Annotated[RequestContext, Depends(require_roles("RESIDENT"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    inquiry_id: uuid.UUID,
    body: CommentIn,
) -> InquiryOut:
    """입주민 피드백 — 작성자 본인·처리중일 때만. 담당자에게 알림(ADR-0018)."""
    inquiry = await _get_inquiry(session, ctx.tenant_id, inquiry_id)
    if inquiry.author_user_id != ctx.user_id:  # 격리 — 존재 여부 노출 안 함
        raise HTTPException(status_code=404, detail="민원을 찾을 수 없음")
    if inquiry.status != "in_progress":
        raise HTTPException(status_code=422, detail="처리중인 민원에만 피드백을 남길 수 있음")

    _add_event(
        session,
        inquiry,
        "comment",
        actor_user_id=ctx.user_id,
        payload={"kind": "feedback", "body": body.body},
    )
    _notify_assignee(session, inquiry, "담당 민원에 입주민 피드백이 등록되었습니다")
    await session.flush()
    return _out(inquiry)


# ── 관리자 ────────────────────────────────────────────────────────────────


@admin_router.get("", response_model=InquiryListOut)
async def list_admin_inquiries(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    status: Annotated[InquiryStatus | None, Query()] = None,
    category_code_id: Annotated[uuid.UUID | None, Query()] = None,
) -> InquiryListOut:
    stmt = select(Inquiry).where(Inquiry.tenant_id == ctx.tenant_id, Inquiry.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(Inquiry.status == status)
    if category_code_id is not None:
        stmt = stmt.where(Inquiry.category_code_id == category_code_id)
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


@admin_router.post("/{inquiry_id}/comments", response_model=InquiryOut)
async def reply_inquiry(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    inquiry_id: uuid.UUID,
    body: CommentIn,
) -> InquiryOut:
    """담당자 답변 — 담당자 본인이거나 소장만. 작성자에게 알림(ADR-0018)."""
    inquiry = await _get_inquiry(session, ctx.tenant_id, inquiry_id)
    if inquiry.assignee_user_id != ctx.user_id and "MANAGER" not in ctx.roles:
        raise HTTPException(status_code=403, detail="담당자 또는 소장만 답변할 수 있음")

    _add_event(
        session,
        inquiry,
        "comment",
        actor_user_id=ctx.user_id,
        payload={"kind": "reply", "body": body.body},
    )
    _notify_author(session, inquiry, "민원에 답변이 등록되었습니다")
    await session.flush()
    return _out(inquiry)


@admin_router.post("/{inquiry_id}/priority", response_model=InquiryOut)
async def set_inquiry_priority(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    inquiry_id: uuid.UUID,
    body: PriorityIn,
) -> InquiryOut:
    """우선순위 수동 지정(담당자·소장). 타임라인 이벤트 없음(ADR-0018)."""
    inquiry = await _get_inquiry(session, ctx.tenant_id, inquiry_id)
    inquiry.priority = body.priority
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

    is_manager = "MANAGER" in ctx.roles
    is_assignee = ctx.user_id == inquiry.assignee_user_id
    if target < current and not is_manager:
        raise HTTPException(status_code=403, detail="상태 역행은 관리자만 가능")
    # 처리중 전환은 배정된 담당자만(+소장 override, ADR-0018).
    if body.status == "in_progress" and not (is_assignee or is_manager):
        raise HTTPException(status_code=403, detail="처리중 전환은 담당자만 가능")
    # 완료는 담당자만(+소장) AND 답변 1건 이상(답변 없는 완료 금지, ADR-0018).
    if body.status == "done":
        if not (is_assignee or is_manager):
            raise HTTPException(status_code=403, detail="완료 처리는 담당자만 가능")
        if await _reply_count(session, inquiry) < 1:
            raise HTTPException(status_code=422, detail="답변 입력 후 완료 가능")

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
