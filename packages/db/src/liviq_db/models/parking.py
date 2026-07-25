"""주차장 대시보드 — parking_assignments (H9-5).

1행 = 세대 배정 주차면 1개(위치·차량번호는 선택). 세대당 다건 허용(UNIQUE 없음). 차량번호는
평문 저장 금지 — plate_enc에 AES-256-GCM 봉투 암호문만 저장한다(규칙 2). 표준 tenant RLS.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Index, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, IdMixin, TenantMixin, TimestampMixin, tenant_fk, tenant_id_unique


class ParkingAssignment(IdMixin, TenantMixin, TimestampMixin, Base):
    """세대 배정 주차면 1건(위치·차량번호 선택, 세대당 다건 — 주차장 대시보드)."""

    __tablename__ = "parking_assignments"
    __table_args__ = (
        tenant_id_unique("parking_assignments"),
        Index("ix_parking_assignments_household", "household_id"),
        Index("ix_parking_assignments_tenant_household", "tenant_id", "household_id"),
        tenant_fk(
            "household_id",
            "households",
            name="fk_parking_assignments_household",
            ondelete="CASCADE",
        ),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    location_code: Mapped[str | None] = mapped_column(String, nullable=True)  # 예 "B2-A-12"
    plate_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # 차량번호 암호문
