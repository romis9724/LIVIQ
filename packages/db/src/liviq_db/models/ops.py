"""운영·AI 품질·큐 — audit_logs·ai_eval_golden·jobs·outbox_events·ai_backend_config
(docs/03 §4.7·4.9)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
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


class AiBackendConfig(Base):
    """AI 백엔드·튜닝 런타임 설정 — 전역 단일 행(id=1). tenant_id·RLS 없음(§4.7, H15-1·H15-3).

    NULL 컬럼은 env/코드 기본값 폴백(행 없음 = 전부 env — 기존 배포 무변화). 해석 규칙은
    `ai_core.backend_config`가 단일 지점(api는 요청 단위, ai-worker는 잡 단위로 소비).
    임베딩·chunk_max_tokens는 **위험 노브** — 변경은 재색인으로만 완성된다(§4.7 규율).
    """

    __tablename__ = "ai_backend_config"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # 응답에는 항상 마스킹
    reasoning_effort: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 임베딩 백엔드(H15-3) — 차원은 스키마 Vector(1024) 고정, 저장 전 실측 검증(§4.7).
    embedding_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # 항상 마스킹
    # 튜닝 노브(H15-3) — NULL = env/코드 기본값.
    chunk_max_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 재색인 필요
    retrieval_top_k: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_timeout_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    tool_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_cache_ttl_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


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
