"""notices — 발행 공지 조회(전 사용자) + AI 초안 생성·검수 발행(관리자) (docs/01 §13).

초안은 근거 강제 AI 생성(근거 0이면 422 — 지어내기 금지, 규칙 1). 발행은 사람 확정만
수행하며(규칙 6·8), published 시 단지 전 active 사용자에게 인앱 알림(type=notice)을
생성한다(외부 자동발송 아님, ADR-0012). scheduled_at이 있으면 저장만(스케줄 실행기 백로그).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient, LlmError
from ai_core.masking import MaskingFailedError
from ai_core.notice_draft import NoEvidenceError, draft_notice
from ai_core.rag.retrieval import PgVectorRetriever
from app.deps import RequestContext, get_context, get_llm, get_tenant_session, require_roles
from app.schemas.notices import (
    DraftDetailOut,
    DraftOut,
    DraftRequestIn,
    NoticeCitationOut,
    NoticeListOut,
    NoticeOut,
    PublishIn,
)
from liviq_db.models import Notice, NoticeDraft, Notification, User

router = APIRouter(prefix="/notices", tags=["notices"])
admin_router = APIRouter(prefix="/admin/notices", tags=["notices"])

_ADMIN_ROLES = ("MANAGER", "STAFF")


def _notice_out(notice: Notice) -> NoticeOut:
    return NoticeOut.model_validate(notice, from_attributes=True)


# ── 조회(전 인증 사용자) ────────────────────────────────────────────────────


@router.get("", response_model=NoticeListOut)
async def list_notices(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> NoticeListOut:
    rows = await session.scalars(
        select(Notice)
        .where(
            Notice.tenant_id == ctx.tenant_id,
            Notice.status == "published",
            Notice.deleted_at.is_(None),
        )
        .order_by(Notice.published_at.desc())
    )
    return NoticeListOut(items=[_notice_out(row) for row in rows])


@router.get("/{notice_id}", response_model=NoticeOut)
async def get_notice(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    notice_id: uuid.UUID,
) -> NoticeOut:
    notice = await session.scalar(
        select(Notice).where(
            Notice.id == notice_id,
            Notice.tenant_id == ctx.tenant_id,
            Notice.status == "published",
            Notice.deleted_at.is_(None),
        )
    )
    if notice is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없음")
    return _notice_out(notice)


# ── 초안 생성·조회(관리자) ──────────────────────────────────────────────────


@admin_router.post("/drafts", response_model=DraftOut, status_code=201)
async def create_draft(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    llm: Annotated[LlmClient, Depends(get_llm)],
    body: DraftRequestIn,
) -> DraftOut:
    try:
        result = await draft_notice(
            body.keywords,
            llm=llm,
            retriever=PgVectorRetriever(session),
            tenant_id=ctx.tenant_id,
            visibilities=list(ctx.visibilities),
        )
    except NoEvidenceError as exc:
        raise HTTPException(
            status_code=422, detail="근거 문서 없음 — 문서 업로드 후 재시도"
        ) from exc
    except MaskingFailedError as exc:  # fail-closed(규칙 2) — 초안 생성 중단
        raise HTTPException(
            status_code=422, detail="개인정보 마스킹 실패 — 초안 생성 중단"
        ) from exc
    except LlmError as exc:
        raise HTTPException(status_code=503, detail="AI 생성 일시 불가") from exc

    draft = NoticeDraft(
        tenant_id=ctx.tenant_id,
        prompt_keywords={"keywords": body.keywords, "title": result.title},
        ai_body=result.body,
        review_status="pending",
    )
    session.add(draft)
    await session.flush()
    return DraftOut(
        draft_id=draft.id,
        title=result.title,
        body=result.body,
        citations=[
            NoticeCitationOut(
                document_id=c.document_id,
                document_title=c.document_title,
                chunk_id=c.chunk_id,
                quote=c.quote,
            )
            for c in result.citations
        ],
        confidence=result.confidence,
    )


@admin_router.get("/drafts/{draft_id}", response_model=DraftDetailOut)
async def get_draft(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    draft_id: uuid.UUID,
) -> DraftDetailOut:
    draft = await _get_draft(session, ctx.tenant_id, draft_id)
    keywords = draft.prompt_keywords or {}
    return DraftDetailOut(
        draft_id=draft.id,
        title=str(keywords.get("title", "")),
        body=draft.ai_body or "",
        keywords=list(keywords.get("keywords", [])),
        review_status=draft.review_status,
        notice_id=draft.notice_id,
        created_at=draft.created_at,
    )


# ── 발행(MANAGER만, 사람 확정) ──────────────────────────────────────────────


@admin_router.post("", response_model=NoticeOut, status_code=201)
async def publish_notice(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    body: PublishIn,
) -> NoticeOut:
    draft = await _get_draft(session, ctx.tenant_id, body.draft_id)
    if draft.review_status != "pending":
        raise HTTPException(status_code=409, detail="이미 검수된 초안")

    scheduled = body.scheduled_at is not None
    now = datetime.datetime.now(datetime.UTC)
    notice = Notice(
        tenant_id=ctx.tenant_id,
        title=body.title,
        body=body.body,
        audience=body.audience,
        # scheduled_at이 있으면 예약 상태로 저장만(스케줄 실행기 백로그) — 즉시 발행 아님.
        status="draft" if scheduled else "published",
        scheduled_at=body.scheduled_at,
        published_at=None if scheduled else now,
        published_by=None if scheduled else ctx.user_id,
    )
    session.add(notice)
    await session.flush()

    draft.notice_id = notice.id
    draft.review_status = "approved"
    draft.reviewed_by = ctx.user_id

    if not scheduled:
        await _notify_active_users(session, ctx.tenant_id, notice)
    await session.flush()
    return _notice_out(notice)


async def _get_draft(
    session: AsyncSession, tenant_id: uuid.UUID, draft_id: uuid.UUID
) -> NoticeDraft:
    draft = await session.scalar(
        select(NoticeDraft).where(NoticeDraft.id == draft_id, NoticeDraft.tenant_id == tenant_id)
    )
    if draft is None:
        raise HTTPException(status_code=404, detail="초안을 찾을 수 없음")
    return draft


async def _notify_active_users(session: AsyncSession, tenant_id: uuid.UUID, notice: Notice) -> None:
    """단지 전 active 사용자에게 인앱 알림 생성(외부 자동발송 아님, ADR-0012)."""
    user_ids = await session.scalars(
        select(User.id).where(User.tenant_id == tenant_id, User.status == "active")
    )
    for user_id in user_ids:
        session.add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="notice",
                title=notice.title,
                link=f"/notices/{notice.id}",
            )
        )
