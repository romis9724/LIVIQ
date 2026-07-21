"""review_queue — AI 검수 큐 사후 검수(docs/01 §13, docs/04 §3).

신뢰도 낮은 assistant 답변(`review_status='needs_review'`)을 사람이 검토해 승인/반려한다(규칙 6).
**사후 검수** — 이미 전달된 답변을 회수하거나 재발송하지 않는다. 결정은 기록으로만 남고
골든셋 후보로 축적된다(docs/07 §5). 부수효과(알림·발송)를 트리거하지 않는다(규칙 8).

목록은 MANAGER·STAFF 읽기, 결정(decide)은 MANAGER만(docs/04 §3 매트릭스).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.schemas.review_queue import (
    DecideIn,
    ReviewCitationOut,
    ReviewItemOut,
    ReviewListOut,
    ReviewStatus,
)
from liviq_db.models import Citation, Conversation, Document, Message, Notification

router = APIRouter(prefix="/admin/review-queue", tags=["review-queue"])

_READ_ROLES = ("MANAGER",)  # 검수 큐 소장 전용(H7-2에서 STAFF 제거, docs/04 §4)

# 반려 정정 알림 문구 — 검수 메모(review_note) 원문은 넣지 않는다(PII·내부 정보 노출 방지,
# ADR-0012). 입주민은 인앱 함에서 확인하고 필요 시 관리사무소로 문의한다.
_REJECT_NOTICE_TITLE = "AI 답변이 검수 결과 정정되었습니다"
_REJECT_NOTICE_BODY = (
    "이전 AI 답변에 정정이 필요한 것으로 확인되었습니다. 자세한 내용은 관리사무소로 문의해 주세요."
)


@router.get("", response_model=ReviewListOut)
async def list_review_queue(
    ctx: Annotated[RequestContext, Depends(require_roles(*_READ_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    status: Annotated[ReviewStatus, Query()] = "needs_review",
    page: Annotated[int, Query(ge=1)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReviewListOut:
    """검수 대상 assistant 답변 목록. 신뢰도 낮은 순(nulls last)→오래된 순 정렬."""
    base = select(Message).where(
        Message.tenant_id == ctx.tenant_id,
        Message.role == "assistant",
        Message.review_status == status,
    )
    total = await session.scalar(select(func.count()).select_from(base.order_by(None).subquery()))
    messages = list(
        await session.scalars(
            base.order_by(Message.confidence.asc().nulls_last(), Message.created_at.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
    )

    questions = await _questions_for(session, ctx.tenant_id, messages)
    citations = await _citations_for(session, ctx.tenant_id, [m.id for m in messages])
    items = [_to_item(m, questions.get(m.id), citations.get(m.id, [])) for m in messages]
    return ReviewListOut(items=items, total=total or 0, page=page, limit=limit)


@router.post("/{message_id}/decide", response_model=ReviewItemOut)
async def decide_review(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    message_id: uuid.UUID,
    body: DecideIn,
) -> ReviewItemOut:
    """승인/반려 결정 기록(사후) — review_status·reviewed_by/at·note 갱신. 부수효과 없음."""
    message = await session.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.tenant_id == ctx.tenant_id,
            Message.role == "assistant",
        )
    )
    if message is None:
        raise HTTPException(status_code=404, detail="검수 대상을 찾을 수 없음")
    if message.review_status != "needs_review":
        raise HTTPException(status_code=409, detail="이미 처리된 검수 항목")

    message.review_status = "approved" if body.action == "approve" else "rejected"
    message.reviewed_by = ctx.user_id
    message.reviewed_at = datetime.datetime.now(datetime.UTC)
    message.review_note = body.note
    if body.action == "reject":
        # 사후 검수 루프 폐합 — 반려 시 대화 소유자에게 인앱 정정 알림(같은 트랜잭션).
        await _notify_conversation_owner(session, ctx.tenant_id, message.conversation_id)
    await session.flush()

    questions = await _questions_for(session, ctx.tenant_id, [message])
    citations = await _citations_for(session, ctx.tenant_id, [message.id])
    return _to_item(message, questions.get(message.id), citations.get(message.id, []))


async def _notify_conversation_owner(
    session: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """대화 소유 입주민에게 인앱 정정 알림 생성 — 자동 외부발송 아님(ADR-0012).

    link는 web-resident에 실존하는 AI 비서 화면(/assistant)으로 건다.
    """
    owner_id = await session.scalar(
        select(Conversation.user_id).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
        )
    )
    if owner_id is None:  # pragma: no cover — 메시지의 대화는 항상 존재(FK)
        return
    session.add(
        Notification(
            tenant_id=tenant_id,
            user_id=owner_id,
            type="system",
            title=_REJECT_NOTICE_TITLE,
            body=_REJECT_NOTICE_BODY,
            link="/assistant",
        )
    )


async def _questions_for(
    session: AsyncSession, tenant_id: uuid.UUID, messages: list[Message]
) -> dict[uuid.UUID, str | None]:
    """assistant 메시지별 직전 user 메시지 content(같은 대화·created_at 이전).

    ponytail: 페이지당 N번 조회(limit<=100). 병목이면 lateral join으로 승격.
    """
    result: dict[uuid.UUID, str | None] = {}
    for m in messages:
        result[m.id] = await session.scalar(
            select(Message.content)
            .where(
                Message.tenant_id == tenant_id,
                Message.conversation_id == m.conversation_id,
                Message.role == "user",
                Message.created_at <= m.created_at,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    return result


async def _citations_for(
    session: AsyncSession, tenant_id: uuid.UUID, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ReviewCitationOut]]:
    """메시지별 인용(문서명·인용문). document_id 없는 근거(fee_data 등)는 title=None."""
    if not message_ids:
        return {}
    rows = await session.execute(
        select(Citation.message_id, Document.title, Citation.quote)
        .outerjoin(
            Document,
            and_(
                Document.tenant_id == Citation.tenant_id,
                Document.id == Citation.document_id,
            ),
        )
        .where(
            Citation.tenant_id == tenant_id,
            Citation.message_id.in_(message_ids),
        )
        .order_by(Citation.created_at)
    )
    result: dict[uuid.UUID, list[ReviewCitationOut]] = {}
    for message_id, title, quote in rows.all():
        result.setdefault(message_id, []).append(
            ReviewCitationOut(document_title=title, quote=quote)
        )
    return result


def _to_item(
    message: Message, question: str | None, citations: list[ReviewCitationOut]
) -> ReviewItemOut:
    return ReviewItemOut(
        message_id=message.id,
        question=question,
        answer=message.content,
        confidence=float(message.confidence) if message.confidence is not None else None,
        status=message.status,
        citations=citations,
        created_at=message.created_at,
        review_status=cast(ReviewStatus, message.review_status),
        reviewed_at=message.reviewed_at,
        review_note=message.review_note,
    )
