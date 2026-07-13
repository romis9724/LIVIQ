"""운영·AI 품질·큐 — audit_logs·ai_eval_golden·jobs·outbox_events (docs/03 §4.7·4.9)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin, TenantMixin, TimestampMixin, tenant_fk


class AuditLog(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """append-only. UPDATE·DELETE는 런타임 role에서 REVOKE(H0-5, §4.7)."""

    __tablename__ = "audit_logs"
    __table_args__ = (tenant_fk("actor_user_id", "users", name="fk_audit_logs_actor"),)

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    target_type: Mapped[str | None] = mapped_column(String, nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip: Mapped[str | None] = mapped_column(String, nullable=True)


class AiEvalGolden(IdMixin, CreatedAtMixin, Base):
    """골든셋. tenant_id NULL=공용, 값=자기 단지(RLS 예외, §5). TenantMixin 미사용."""

    __tablename__ = "ai_eval_golden"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 문서 삭제·재색인과 느슨하게 결합(FK 없음) — eval 메타
    expected_doc_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tags: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Job(IdMixin, TenantMixin, TimestampMixin, Base):
    """비동기 작업 큐. 워커 role만 cross-tenant claim(§5)."""

    __tablename__ = "jobs"

    type: Mapped[str] = mapped_column(String, nullable=False)  # ingest|ocr|reembed|eval
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OutboxEvent(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """PG→Neo4j 동기화 아웃박스. 워커 role만 cross-tenant claim(§4.9·§5)."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_outbox_events_dedupe_key"),
        Index("ix_outbox_events_status_created", "status", "created_at"),
    )

    aggregate_type: Mapped[str] = mapped_column(String, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)  # created|updated|deleted
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)  # aggregate별 단조 증가
    dedupe_key: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # pending|processed|failed
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    processed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
