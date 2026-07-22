"""공지·알림 — notices·notice_attachments·notifications (docs/03 §4.4).

공지는 일반 게시판이다(H8-1, ADR-0015 — AI 초안 폐기). 작성·수정·삭제(soft)·상단 고정·
임시저장(draft)·예약 발행(scheduled)·첨부(MinIO)를 지원한다. published 전이 시 인앱 알림
생성(외부 자동발송 아님, ADR-0012). soft delete 대상(§3).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from .base import (
    Base,
    CreatedAtMixin,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    tenant_fk,
    tenant_id_unique,
)


class Notice(IdMixin, TenantMixin, TimestampMixin, Base):
    """공지 게시글. soft delete 대상(§3). 예약 발행은 ai-worker cron이 도달 시 전이(ADR-0015)."""

    __tablename__ = "notices"
    __table_args__ = (
        tenant_id_unique("notices"),
        Index("ix_notices_tenant_status_published", "tenant_id", "status", "published_at"),
        tenant_fk("published_by", "users", name="fk_notices_published_by"),
        # 분류는 NOTICE_CATEGORY 그룹 코드 참조(NULL 허용·RESTRICT, H8-6 · ADR-0017).
        tenant_fk(
            "category_code_id", "codes", name="fk_notices_category_code", ondelete="RESTRICT"
        ),
        Index("ix_notices_tenant_category", "tenant_id", "category_code_id"),
    )

    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # draft|scheduled|published (ADR-0015 — retracted|superseded 제거)
    status: Mapped[str] = mapped_column(String, nullable=False)
    # NOTICE_CATEGORY 그룹 코드 FK(NULL 허용 — 임시저장·기존 무분류, H8-6).
    category_code_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 표시용 행사/작업 기간(게시 노출 제어 아님 — scheduled_at과 무관).
    event_start: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    event_end: Mapped[datetime.date | None] = mapped_column(Date, nullable=True)
    # 대상 동 building id 배열(NULL=전체동). 표시용 — 알림 타게팅은 백로그.
    target_buildings: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    # 콤마 구분 키워드. H8-3 공지 임베딩 텍스트에 포함(본문+키워드).
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    scheduled_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    audience: Mapped[str] = mapped_column(String, nullable=False)  # ALL|building|household
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class NoticeAttachment(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """공지 첨부(MinIO 저장). 다운로드는 API 경유(§4.4). 하드 삭제(soft delete 아님)."""

    __tablename__ = "notice_attachments"
    __table_args__ = (
        tenant_fk("notice_id", "notices", name="fk_notice_attachments_notice", ondelete="CASCADE"),
        Index("ix_notice_attachments_tenant_notice", "tenant_id", "notice_id"),
    )

    notice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(String, nullable=False)


class Notification(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """인앱 알림함(외부 자동발송 아님). RLS + 본인 알림만 열람(§4.4)."""

    __tablename__ = "notifications"
    __table_args__ = (tenant_fk("user_id", "users", name="fk_notifications_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # notice|inquiry_status|approval|system
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(String, nullable=True)  # 앱 내 딥링크
    read_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
