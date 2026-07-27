"""시설 — facilities·maintenance_logs·incidents (docs/03 §4.5).

시설 텍스트 임베딩은 PG에 저장하지 않는다(Neo4j 전용, §4.5·docs/11).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import DateTime, String, Text, UniqueConstraint
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


class Facility(IdMixin, TenantMixin, TimestampMixin, Base):
    """시설. soft delete 대상(§3).

    `code`는 시설 코드번호(H14-2, `EL-401-01`) — 서버가 생성 시 부여하고 수정 경로가 없다.
    단지 안에서만 유일하다(단지가 다르면 같은 코드가 공존 — 규칙 3 격리).
    """

    __tablename__ = "facilities"
    __table_args__ = (
        tenant_id_unique("facilities"),
        UniqueConstraint("tenant_id", "code", name="uq_facilities_tenant_code"),
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    # nullable — 코드 도입 전 행이 있을 수 있고(백필 대상), NULL은 unique 제약에서 자유롭다.
    code: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)  # normal|check|fault|risk
    next_check_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class MaintenanceLog(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "maintenance_logs"
    __table_args__ = (tenant_fk("facility_id", "facilities", name="fk_maintenance_logs_facility"),)

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    performed_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    work: Mapped[str] = mapped_column(Text, nullable=False)
    performer: Mapped[str | None] = mapped_column(String, nullable=True)
    parts: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class Incident(IdMixin, TenantMixin, CreatedAtMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (tenant_fk("facility_id", "facilities", name="fk_incidents_facility"),)

    facility_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    occurred_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    symptom: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
