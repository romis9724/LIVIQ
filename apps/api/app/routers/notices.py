"""notices — 공지 게시판(작성·수정·삭제·고정·예약·첨부) + 발행 조회 (docs/01 §13, ADR-0015).

AI 초안 폐기(H8-1). 작성·발행은 MANAGER·STAFF. published 전이 시 단지 전 active 사용자에게
인앱 알림(type=notice)을 생성한다(외부 자동발송 아님, ADR-0012). 예약 발행(scheduled)은
ai-worker cron이 scheduled_at 도달 시 published로 전이하며 같은 알림 헬퍼 로직을 재사용한다.
첨부는 MinIO 저장·API 경유 다운로드(presigned 미사용) — tenant·published 이중 검증(§4.4).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import (
    RequestContext,
    Storage,
    get_context,
    get_storage,
    get_tenant_session,
    require_roles,
)
from app.schemas.notices import (
    AttachmentOut,
    NoticeCreateIn,
    NoticeListOut,
    NoticeOut,
    NoticeUpdateIn,
)
from liviq_db.models import Notice, NoticeAttachment, Notification, User

router = APIRouter(prefix="/notices", tags=["notices"])
admin_router = APIRouter(prefix="/admin/notices", tags=["notices"])

_ADMIN_ROLES = ("MANAGER", "STAFF")

ALLOWED_ATTACHMENT_SUFFIXES = {".pdf", ".hwp", ".hwpx", ".docx", ".xlsx", ".jpg", ".jpeg", ".png"}
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 파일당 20MB
MAX_ATTACHMENTS_PER_NOTICE = 5


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _attachment_out(row: NoticeAttachment) -> AttachmentOut:
    return AttachmentOut.model_validate(row, from_attributes=True)


def _notice_out(notice: Notice, attachments: Sequence[NoticeAttachment] = ()) -> NoticeOut:
    out = NoticeOut.model_validate(notice, from_attributes=True)
    return out.model_copy(update={"attachments": [_attachment_out(a) for a in attachments]})


async def _load_attachments(
    session: AsyncSession, tenant_id: uuid.UUID, notice_id: uuid.UUID
) -> list[NoticeAttachment]:
    rows = await session.scalars(
        select(NoticeAttachment)
        .where(
            NoticeAttachment.tenant_id == tenant_id,
            NoticeAttachment.notice_id == notice_id,
        )
        .order_by(NoticeAttachment.created_at.asc())
    )
    return list(rows)


async def _get_owned_notice(
    session: AsyncSession, tenant_id: uuid.UUID, notice_id: uuid.UUID
) -> Notice:
    """관리자 스코프 — tenant 소유의 미삭제 공지(전 상태). 없으면 404(격리 유지)."""
    notice = await session.scalar(
        select(Notice).where(
            Notice.id == notice_id,
            Notice.tenant_id == tenant_id,
            Notice.deleted_at.is_(None),
        )
    )
    if notice is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없음")
    return notice


async def _get_published_notice(
    session: AsyncSession, tenant_id: uuid.UUID, notice_id: uuid.UUID
) -> Notice:
    """입주민 스코프 — published + 미삭제 + tenant. 미발행·타 단지는 404(첨부 인가 게이트)."""
    notice = await session.scalar(
        select(Notice).where(
            Notice.id == notice_id,
            Notice.tenant_id == tenant_id,
            Notice.status == "published",
            Notice.deleted_at.is_(None),
        )
    )
    if notice is None:
        raise HTTPException(status_code=404, detail="공지를 찾을 수 없음")
    return notice


async def _notify_notice_published(
    session: AsyncSession, tenant_id: uuid.UUID, notice: Notice
) -> None:
    """단지 전 active 사용자에게 인앱 알림 생성(외부 자동발송 아님, ADR-0012).

    즉시 발행(POST)·발행 전이(PATCH) 두 경로가 공유한다. 예약 도달 발행은 ai-worker가
    같은 로직을 최소 중복으로 수행(패키지 경계, ADR-0015).
    """
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
        .order_by(Notice.pinned.desc(), Notice.published_at.desc())
    )
    return NoticeListOut(items=[_notice_out(row) for row in rows])


@router.get("/{notice_id}", response_model=NoticeOut)
async def get_notice(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    notice_id: uuid.UUID,
) -> NoticeOut:
    notice = await _get_published_notice(session, ctx.tenant_id, notice_id)
    attachments = await _load_attachments(session, ctx.tenant_id, notice.id)
    return _notice_out(notice, attachments)


@router.get("/{notice_id}/attachments/{attachment_id}")
async def download_attachment(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    notice_id: uuid.UUID,
    attachment_id: uuid.UUID,
) -> Response:
    # 첨부 인가 게이트(§4.4 CRITICAL): tenant + 공지 published + 소유 notice 일치.
    await _get_published_notice(session, ctx.tenant_id, notice_id)
    attachment = await session.scalar(
        select(NoticeAttachment).where(
            NoticeAttachment.id == attachment_id,
            NoticeAttachment.notice_id == notice_id,
            NoticeAttachment.tenant_id == ctx.tenant_id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="첨부를 찾을 수 없음")
    data = await storage.get(attachment.storage_key)
    # 한글 파일명은 RFC 5987(filename*)로 인코딩 — ASCII 헤더 제약 우회.
    disposition = f"attachment; filename*=UTF-8''{quote(attachment.filename)}"
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": disposition},
    )


# ── 관리(MANAGER·STAFF) ─────────────────────────────────────────────────────


@admin_router.get("", response_model=NoticeListOut)
async def list_admin_notices(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> NoticeListOut:
    rows = await session.scalars(
        select(Notice)
        .where(Notice.tenant_id == ctx.tenant_id, Notice.deleted_at.is_(None))
        .order_by(Notice.pinned.desc(), Notice.created_at.desc())
    )
    return NoticeListOut(items=[_notice_out(row) for row in rows])


@admin_router.post("", response_model=NoticeOut, status_code=201)
async def create_notice(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    body: NoticeCreateIn,
) -> NoticeOut:
    is_published = body.status == "published"
    now = _now()
    notice = Notice(
        tenant_id=ctx.tenant_id,
        title=body.title,
        body=body.body,
        audience=body.audience,
        status=body.status,
        pinned=body.pinned,
        scheduled_at=body.scheduled_at,
        published_at=now if is_published else None,
        published_by=ctx.user_id if is_published else None,
    )
    session.add(notice)
    await session.flush()
    if is_published:
        await _notify_notice_published(session, ctx.tenant_id, notice)
        await session.flush()
    return _notice_out(notice)


@admin_router.get("/{notice_id}", response_model=NoticeOut)
async def get_admin_notice(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    notice_id: uuid.UUID,
) -> NoticeOut:
    notice = await _get_owned_notice(session, ctx.tenant_id, notice_id)
    attachments = await _load_attachments(session, ctx.tenant_id, notice.id)
    return _notice_out(notice, attachments)


@admin_router.patch("/{notice_id}", response_model=NoticeOut)
async def update_notice(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    notice_id: uuid.UUID,
    body: NoticeUpdateIn,
) -> NoticeOut:
    notice = await _get_owned_notice(session, ctx.tenant_id, notice_id)
    fields = body.model_fields_set
    new_status = body.status

    # published→draft/scheduled 역행 거부(발행 취소 불가).
    if notice.status == "published" and new_status is not None and new_status != "published":
        raise HTTPException(status_code=409, detail="발행된 공지는 초안·예약으로 되돌릴 수 없음")

    if "title" in fields and body.title is not None:
        notice.title = body.title
    if "body" in fields and body.body is not None:
        notice.body = body.body
    if "audience" in fields and body.audience is not None:
        notice.audience = body.audience
    if "pinned" in fields and body.pinned is not None:
        notice.pinned = body.pinned

    became_published = False
    if new_status is not None:
        if new_status == "published" and notice.status != "published":
            notice.published_at = _now()
            notice.published_by = ctx.user_id
            notice.scheduled_at = None
            became_published = True
        elif new_status == "scheduled":
            notice.scheduled_at = body.scheduled_at  # validator가 미래·존재 보장
        elif new_status == "draft":
            notice.scheduled_at = None
        notice.status = new_status

    await session.flush()
    if became_published:
        await _notify_notice_published(session, ctx.tenant_id, notice)
        await session.flush()
    attachments = await _load_attachments(session, ctx.tenant_id, notice.id)
    return _notice_out(notice, attachments)


@admin_router.delete("/{notice_id}", status_code=204)
async def delete_notice(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    notice_id: uuid.UUID,
) -> Response:
    notice = await _get_owned_notice(session, ctx.tenant_id, notice_id)
    notice.deleted_at = _now()
    await session.flush()
    return Response(status_code=204)


# ── 첨부(MANAGER·STAFF) ─────────────────────────────────────────────────────


@admin_router.post("/{notice_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    notice_id: uuid.UUID,
    file: Annotated[UploadFile, File()],
) -> AttachmentOut:
    notice = await _get_owned_notice(session, ctx.tenant_id, notice_id)

    filename = file.filename or ""
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix not in ALLOWED_ATTACHMENT_SUFFIXES:  # fail-closed(화이트리스트)
        raise HTTPException(status_code=422, detail=f"허용되지 않는 형식: {suffix or '없음'}")

    count = await session.scalar(
        select(func.count())
        .select_from(NoticeAttachment)
        .where(
            NoticeAttachment.tenant_id == ctx.tenant_id,
            NoticeAttachment.notice_id == notice.id,
        )
    )
    if (count or 0) >= MAX_ATTACHMENTS_PER_NOTICE:
        raise HTTPException(
            status_code=422, detail=f"공지당 첨부는 최대 {MAX_ATTACHMENTS_PER_NOTICE}개"
        )

    data = await file.read()
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status_code=413, detail="파일이 20MB를 초과")
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일")

    attachment_id = uuid.uuid4()
    storage_key = f"{ctx.tenant_id}/notices/{notice.id}/{attachment_id}"
    await storage.put(storage_key, data)
    attachment = NoticeAttachment(
        id=attachment_id,
        tenant_id=ctx.tenant_id,
        notice_id=notice.id,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data),
        storage_key=storage_key,
    )
    session.add(attachment)
    await session.flush()
    return _attachment_out(attachment)


@admin_router.delete("/{notice_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    notice_id: uuid.UUID,
    attachment_id: uuid.UUID,
) -> Response:
    attachment = await session.scalar(
        select(NoticeAttachment).where(
            NoticeAttachment.id == attachment_id,
            NoticeAttachment.notice_id == notice_id,
            NoticeAttachment.tenant_id == ctx.tenant_id,
        )
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="첨부를 찾을 수 없음")
    storage_key = attachment.storage_key
    await session.delete(attachment)
    await session.flush()
    await storage.delete(storage_key)  # DB 행 삭제 확정 후 객체 제거(하드 삭제)
    return Response(status_code=204)
