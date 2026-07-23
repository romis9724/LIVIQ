"""notifications — 인앱 알림함 조회·읽음 처리 (docs/03 §4.4, ADR-0012).

인앱 함 적재만 — 외부 자동발송 아님. 알림 **생성**은 도메인 이벤트(민원 상태·검수 반려 등)
쪽 코드가 담당하고, 이 라우터는 본인 알림 조회·읽음만 제공한다.

소유권 불변식: 목록·읽음 모두 `user_id == ctx.user_id` 필터가 쿼리에 박힌다(규칙 4).
notifications RLS는 tenant 단위라 user 격리는 DB가 아닌 이 필터가 보장한다.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_context, get_tenant_session
from app.schemas.notifications import NotificationListOut, NotificationOut
from liviq_db.models import Notification

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListOut)
async def list_my_notifications(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> NotificationListOut:
    """본인 알림 최신순. 소유권 필터가 쿼리에 박힘 — 파라미터로 우회 불가(규칙 4)."""
    base = select(Notification).where(
        Notification.tenant_id == ctx.tenant_id,
        Notification.user_id == ctx.user_id,
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.scalars(
        base.order_by(Notification.created_at.desc()).offset((page - 1) * limit).limit(limit)
    )
    return NotificationListOut(
        items=[NotificationOut.model_validate(row, from_attributes=True) for row in rows],
        total=total or 0,
        page=page,
        limit=limit,
    )


@router.post("/{notification_id}/read", response_model=NotificationOut)
async def mark_read(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    notification_id: uuid.UUID,
) -> NotificationOut:
    """읽음 스탬프 — 본인 알림만. 이미 읽었으면 기존 시각 유지(멱등)."""
    notification = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == ctx.tenant_id,
            Notification.user_id == ctx.user_id,  # 타인 알림은 404(존재 여부 미노출)
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없음")
    if notification.read_at is None:
        notification.read_at = datetime.datetime.now(datetime.UTC)
        await session.flush()
    return NotificationOut.model_validate(notification, from_attributes=True)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    notification_id: uuid.UUID,
) -> None:
    """본인 알림 하드 삭제. 없거나 타인 것이면 404(존재 여부 미노출, 규칙 4)."""
    notification = await session.scalar(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.tenant_id == ctx.tenant_id,
            Notification.user_id == ctx.user_id,  # 타인 알림은 404
        )
    )
    if notification is None:
        raise HTTPException(status_code=404, detail="알림을 찾을 수 없음")
    await session.delete(notification)
    await session.flush()
