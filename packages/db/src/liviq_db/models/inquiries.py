"""민원 — inquiry_categories·inquiries (docs/03 §4.4)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TenantMixin, TimestampMixin, tenant_fk, tenant_id_unique


class InquiryCategory(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "inquiry_categories"
    __table_args__ = (tenant_id_unique("inquiry_categories"),)

    name: Mapped[str] = mapped_column(String, nullable=False)
    default_assignee_role: Mapped[str | None] = mapped_column(String, nullable=True)
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Inquiry(IdMixin, TenantMixin, TimestampMixin, Base):
    """민원. soft delete 대상(§3)."""

    __tablename__ = "inquiries"
    __table_args__ = (
        Index("ix_inquiries_tenant_status", "tenant_id", "status"),
        tenant_fk("household_id", "households", name="fk_inquiries_household"),
        tenant_fk("author_user_id", "users", name="fk_inquiries_author"),
        tenant_fk("assignee_user_id", "users", name="fk_inquiries_assignee"),
        tenant_fk("category_id", "inquiry_categories", name="fk_inquiries_category"),
        tenant_fk(
            "ai_suggested_category_id",
            "inquiry_categories",
            name="fk_inquiries_ai_category",
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    ai_suggested_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    ai_priority: Mapped[str | None] = mapped_column(String, nullable=True)  # urgent|normal|low
    # received|assigned|in_progress|done
    status: Mapped[str] = mapped_column(String, nullable=False)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attachments: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
