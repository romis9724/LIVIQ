"""주차장 대시보드 — parking_layouts·parking_vehicles (H9-5).

지하주차장 2D 배치도(단지당 1행 JSONB — viewBox·buildings·boxes·cores·spots)와 입주민 차량
명부를 담는다. layout JSONB는 렌더 페이로드 그대로 — 서버는 내용을 해석하지 않는다(YAGNI).
차량번호는 평문 저장 금지 — plate_enc에 AES-256-GCM 봉투 암호문만 저장한다(규칙 2).
둘 다 표준 tenant RLS.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, LargeBinary, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TenantMixin, TimestampMixin, tenant_fk, tenant_id_unique


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
