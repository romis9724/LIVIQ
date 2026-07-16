"""공지·알림 — notices·notice_drafts·notifications (docs/03 §4.4)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

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
    """공지. soft delete 대상(§3). 자동발송 금지 — 검수 후 발행(§CLAUDE 절대규칙6)."""

    __tablename__ = "notices"
    __table_args__ = (
        tenant_id_unique("notices"),
        Index("ix_notices_tenant_status_published", "tenant_id", "status", "published_at"),
        tenant_fk("published_by", "users", name="fk_notices_published_by"),
    )

    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # draft|published|retracted|superseded
    status: Mapped[str] = mapped_column(String, nullable=False)
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


class NoticeDraft(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """AI 공지 초안. 검수 후 notices로 승격(자동발송 금지)."""

    __tablename__ = "notice_drafts"
    __table_args__ = (
        tenant_fk("notice_id", "notices", name="fk_notice_drafts_notice"),
        tenant_fk("reviewed_by", "users", name="fk_notice_drafts_reviewed_by"),
    )

    notice_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    prompt_keywords: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ai_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    review_status: Mapped[str] = mapped_column(String, nullable=False)  # pending|approved|rejected


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
