"""대화·인용·피드백 — conversations·messages·citations·ai_feedback (docs/03 §4.3·4.7)."""

from __future__ import annotations

import datetime
import decimal
import uuid

from sqlalchemy import DateTime, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
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


class Conversation(IdMixin, TenantMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        tenant_id_unique("conversations"),
        tenant_fk("user_id", "users", name="fk_conversations_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)  # resident|admin


class Message(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        tenant_id_unique("messages"),
        tenant_fk("conversation_id", "conversations", name="fk_messages_conversation"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # user|assistant|system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    intent: Mapped[str | None] = mapped_column(String, nullable=True)  # ai|handoff
    confidence: Mapped[decimal.Decimal | None] = mapped_column(Numeric, nullable=True)
    # answered|fallback|handed_off
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    # needs_review|approved|rejected
    review_status: Mapped[str | None] = mapped_column(String, nullable=True)
    # 사후 검수 결정 기록(docs/01 §13, H2-6) — 검수자·시각·메모. FK 없음(actor_user_id 패턴).
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[decimal.Decimal | None] = mapped_column(Numeric, nullable=True)


class Citation(IdMixin, TenantMixin, TimestampMixin, Base):
    """응답 근거. 문서에 한정하지 않음(도구 결과 근거도 동일 테이블, §4.3)."""

    __tablename__ = "citations"
    __table_args__ = (
        tenant_fk("message_id", "messages", name="fk_citations_message"),
        tenant_fk("document_id", "documents", name="fk_citations_document"),
        # 청크 재색인·삭제 시 chunk_id만 NULL, 답변 시점 근거(quote·source_revision) 보존(§4.3)
        tenant_fk(
            "chunk_id",
            "content_chunks",
            name="fk_citations_chunk",
            ondelete="SET NULL (chunk_id)",
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_kind: Mapped[str] = mapped_column(String, nullable=False)  # document_chunk|fee_data|...
    source_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    source_revision: Mapped[str | None] = mapped_column(String, nullable=True)
    observed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clause: Mapped[str | None] = mapped_column(String, nullable=True)


class AiFeedback(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "ai_feedback"
    __table_args__ = (tenant_fk("message_id", "messages", name="fk_ai_feedback_message"),)

    message_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    rating: Mapped[str] = mapped_column(String, nullable=False)  # up|down
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
