"""테넌시·마스터 — tenants·buildings·households·unit_types (docs/03 §4.1·4.8)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TenantMixin, TimestampMixin, tenant_fk, tenant_id_unique


class Tenant(IdMixin, TimestampMixin, Base):
    """단지. RLS 예외 — 멤버십 기반 인가로 접근 통제(§5). tenant_id 없음."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String, nullable=False)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


class Building(IdMixin, TenantMixin, TimestampMixin, Base):
    """동 (마스터)."""

    __tablename__ = "buildings"
    __table_args__ = (
        tenant_id_unique("buildings"),
        UniqueConstraint("tenant_id", "name", name="uq_buildings_tenant_name"),
    )

    name: Mapped[str] = mapped_column(String, nullable=False)
    floors: Mapped[int | None] = mapped_column(Integer, nullable=True)


class UnitType(IdMixin, TenantMixin, TimestampMixin, Base):
    """평면도 타입 (예: 84A)."""

    __tablename__ = "unit_types"
    __table_args__ = (tenant_id_unique("unit_types"),)

    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)


class Household(IdMixin, TenantMixin, TimestampMixin, Base):
    """세대 (동·층·호로 구조화)."""

    __tablename__ = "households"
    __table_args__ = (
        tenant_id_unique("households"),
        UniqueConstraint(
            "tenant_id",
            "building_id",
            "floor",
            "unit_no",
            name="uq_households_tenant_building_floor_unit",
        ),
        tenant_fk("building_id", "buildings", name="fk_households_building"),
        tenant_fk("unit_type_id", "unit_types", name="fk_households_unit_type"),
    )

    building_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    floor: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_no: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_type_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
