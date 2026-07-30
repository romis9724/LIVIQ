"""주차장 대시보드 — parking_layouts·parking_vehicles (H9-5).

지하주차장 2D 배치도(단지당 1행 JSONB — viewBox·buildings·boxes·cores·spots)와 입주민 차량
명부를 담는다. layout JSONB는 렌더 페이로드 그대로 — 서버는 내용을 해석하지 않는다(YAGNI).
차량번호는 평문 저장 금지 — plate_enc에 AES-256-GCM 봉투 암호문만 저장한다(규칙 2).
둘 다 표준 tenant RLS.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TenantMixin, TimestampMixin, tenant_fk, tenant_id_unique

_OCCUPANT_CHECK = (
    "(is_external = false AND parking_vehicle_id IS NOT NULL AND external_plate_enc IS NULL) "
    "OR (is_external = true AND parking_vehicle_id IS NULL AND external_plate_enc IS NOT NULL)"
)


class ParkingLayout(IdMixin, TenantMixin, TimestampMixin, Base):
    """지하주차장 배치도 — 단지당 1행(전량 교체). layout은 렌더 페이로드 그대로 저장."""

    __tablename__ = "parking_layouts"
    __table_args__ = (
        tenant_id_unique("parking_layouts"),
        UniqueConstraint("tenant_id", name="uq_parking_layouts_tenant"),
    )

    layout: Mapped[dict] = mapped_column(JSONB, nullable=False)


class ParkingVehicle(IdMixin, TenantMixin, TimestampMixin, Base):
    """입주민 차량 1대 — 세대당 다건 허용(UNIQUE 없음). 차량번호는 암호문만 저장."""

    __tablename__ = "parking_vehicles"
    __table_args__ = (
        tenant_id_unique("parking_vehicles"),
        Index("ix_parking_vehicles_household", "household_id"),
        Index("ix_parking_vehicles_tenant_household", "tenant_id", "household_id"),
        tenant_fk(
            "household_id",
            "households",
            name="fk_parking_vehicles_household",
            ondelete="CASCADE",
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    plate_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # 차량번호 암호문
    model: Mapped[str | None] = mapped_column(String, nullable=True)  # 차종 (예 "아이오닉5")
    is_ev: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class ParkingOccupancy(IdMixin, TenantMixin, TimestampMixin, Base):
    """면 점유 1행 — 면당 1행(UNIQUE(tenant_id, spot_no)·전량 교체), 점유의 단일 사실 원천(SoR).

    is_external=false면 입주민 차(parking_vehicle_id composite FK, ON DELETE CASCADE)이고,
    is_external=true면 외부/방문차(external_plate_enc 봉투 암호문 — 평문 금지, 규칙2). 둘 중 정확히
    하나만 채워지도록 CHECK로 강제한다. parked_hours는 상대 경과(뷰 표시용)라 시간이 지나도 안정적.
    """

    __tablename__ = "parking_occupancy"
    __table_args__ = (
        tenant_id_unique("parking_occupancy"),
        UniqueConstraint("tenant_id", "spot_no", name="uq_parking_occupancy_tenant_spot"),
        Index("ix_parking_occupancy_tenant", "tenant_id"),
        tenant_fk(
            "parking_vehicle_id",
            "parking_vehicles",
            name="fk_parking_occupancy_vehicle",
            ondelete="CASCADE",
        ),
        CheckConstraint(_OCCUPANT_CHECK, name="occupant"),
    )

    spot_no: Mapped[str] = mapped_column(Text, nullable=False)  # parking_layouts.layout.spots[].no
    is_external: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    parking_vehicle_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )  # 입주민 차 (is_external=false)
    external_plate_enc: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )  # 외부/방문차 번호판 암호문 (is_external=true)
    parked_hours: Mapped[float | None] = mapped_column(Float, nullable=True)  # 입차 경과(뷰 표시용)
