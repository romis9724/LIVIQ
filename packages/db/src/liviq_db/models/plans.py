"""평면도·디지털트윈 — floor_plans·plan_devices (docs/03 §4.8).

배경 이미지 + 좌표 레이어. 마커는 정적 데이터(IoT 미연동).
"""

from __future__ import annotations

import decimal
import uuid

from sqlalchemy import Index, Integer, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TenantMixin, TimestampMixin, tenant_fk, tenant_id_unique


class FloorPlan(IdMixin, TenantMixin, TimestampMixin, Base):
    """평면도 (세대타입 / 동 공용층 / 단지 배치도 공통)."""

    __tablename__ = "floor_plans"
    __table_args__ = (
        tenant_id_unique("floor_plans"),
        tenant_fk("unit_type_id", "unit_types", name="fk_floor_plans_unit_type"),
        tenant_fk("building_id", "buildings", name="fk_floor_plans_building"),
    )

    scope: Mapped[str] = mapped_column(String, nullable=False)  # unit_type|building_common|site
    unit_type_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    building_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    floor_label: Mapped[str | None] = mapped_column(String, nullable=True)
    image_key: Mapped[str] = mapped_column(String, nullable=False)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class PlanDevice(IdMixin, TenantMixin, TimestampMixin, Base):
    """장치/포인트 (타입 기본 + 세대 오버라이드 단일 테이블)."""

    __tablename__ = "plan_devices"
    __table_args__ = (
        tenant_id_unique("plan_devices"),
        Index("ix_plan_devices_tenant_floor_plan", "tenant_id", "floor_plan_id"),
        Index("ix_plan_devices_tenant_household", "tenant_id", "household_id"),
        tenant_fk("floor_plan_id", "floor_plans", name="fk_plan_devices_floor_plan"),
        tenant_fk("household_id", "households", name="fk_plan_devices_household"),
        tenant_fk("base_device_id", "plan_devices", name="fk_plan_devices_base_device"),
        tenant_fk("facility_id", "facilities", name="fk_plan_devices_facility"),
    )

    floor_plan_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    household_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    base_device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)  # base|add|move|hide
    device_type: Mapped[str] = mapped_column(String, nullable=False)
    x: Mapped[decimal.Decimal] = mapped_column(Numeric, nullable=False)
    y: Mapped[decimal.Decimal] = mapped_column(Numeric, nullable=False)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    memo: Mapped[str | None] = mapped_column(Text, nullable=True)
    photo_key: Mapped[str | None] = mapped_column(String, nullable=True)
    facility_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
