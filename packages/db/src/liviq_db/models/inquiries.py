"""민원 — inquiries·inquiry_events (docs/03 §4.4, ADR-0018).

분류는 공통 코드 그룹 INQUIRY_CATEGORY로 흡수(ADR-0017·0018) — inquiry_categories 테이블 폐기.
"""

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


class Inquiry(IdMixin, TenantMixin, TimestampMixin, Base):
    """민원. soft delete 대상(§3)."""

    __tablename__ = "inquiries"
    __table_args__ = (
        tenant_id_unique("inquiries"),  # inquiry_events composite FK 대상(§5)
        Index("ix_inquiries_tenant_status", "tenant_id", "status"),
        tenant_fk("household_id", "households", name="fk_inquiries_household"),
        tenant_fk("author_user_id", "users", name="fk_inquiries_author"),
        tenant_fk("assignee_user_id", "users", name="fk_inquiries_assignee"),
        # 분류는 INQUIRY_CATEGORY 그룹 코드 참조(RESTRICT, 참조 중 삭제 거부 — ADR-0018).
        tenant_fk("category_code_id", "codes", name="fk_inquiries_category_code"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category_code_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str | None] = mapped_column(String, nullable=True)  # urgent|normal|low
    # received|assigned|in_progress|done
    status: Mapped[str] = mapped_column(String, nullable=False)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attachments: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InquiryEvent(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """민원 타임라인 이벤트 — 상태·배정 변경마다 append(§4.4, H2-3).

    append-only: UPDATE/DELETE는 권한으로 차단(마이그레이션 GRANT SELECT·INSERT).
    """

    __tablename__ = "inquiry_events"
    __table_args__ = (
        Index("ix_inquiry_events_tenant_inquiry", "tenant_id", "inquiry_id", "created_at"),
        tenant_fk("inquiry_id", "inquiries", name="fk_inquiry_events_inquiry", ondelete="CASCADE"),
    )

    inquiry_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # created|ai_classified|assigned|status_changed|comment
    type: Mapped[str] = mapped_column(String, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(  # NULL = 시스템(AI 분류 등)
        UUID(as_uuid=True), nullable=True
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
