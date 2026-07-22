"""관리비 — fees·excel_uploads (docs/03 §4.6).

엑셀 업로드가 원천. AI는 설명만(계산·부과 금지, CLAUDE 절대규칙5).
"""

from __future__ import annotations

import decimal
import uuid
from typing import Any

from sqlalchemy import Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, CreatedAtMixin, IdMixin, TenantMixin, tenant_fk, tenant_id_unique


class ExcelUpload(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """엑셀 업로드 이력 (관리비·명부 공통)."""

    __tablename__ = "excel_uploads"
    __table_args__ = (
        tenant_id_unique("excel_uploads"),
        tenant_fk("uploaded_by", "users", name="fk_excel_uploads_uploaded_by"),
    )

    type: Mapped[str] = mapped_column(String, nullable=False)  # fee|roster
    period: Mapped[str | None] = mapped_column(String, nullable=True)  # fee일 때 YYYY-MM
    file_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)  # uploaded|validated|applied|failed
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class Fee(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """세대별 월 관리비. 재업로드 = (tenant, period) 전 행 교체(§4.6·docs/11)."""

    __tablename__ = "fees"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "household_id", "period", name="uq_fees_tenant_household_period"
        ),
        tenant_fk("household_id", "households", name="fk_fees_household"),
        tenant_fk("upload_id", "excel_uploads", name="fk_fees_upload"),
    )

    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period: Mapped[str] = mapped_column(String, nullable=False)  # YYYY-MM
    # H8-7: 순서 보존 트리 리스트 [{"name","level","amount"}, ...] (구 dict 포맷 대체)
    breakdown: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # 금액: KRW 원 단위 정수(§3)
    total_amount: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 0), nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)  # excel|erp(추후)
    upload_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
