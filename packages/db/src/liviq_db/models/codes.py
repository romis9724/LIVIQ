"""공통 코드 레지스트리 — code_groups·codes (docs/03 §4.10 · ADR-0017).

분류를 하드코딩하지 않고 tenant 스코프 계층 코드로 관리한다. `codes.parent_id`는 자기참조
composite FK(계층)이며, 순환 방지는 앱 검증이 소유한다(DB 깊이 제한 없음). soft delete 대상
아님 — 하드 삭제(그룹→코드 CASCADE, 자식 있는 코드는 앱에서 409).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from .base import (
    Base,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    tenant_fk,
    tenant_id_unique,
)


class CodeGroup(IdMixin, TenantMixin, TimestampMixin, Base):
    """코드 그룹(예: NOTICE_CATEGORY·DOC_CATEGORY). is_system 그룹은 삭제·group_key 변경 불가."""

    __tablename__ = "code_groups"
    __table_args__ = (
        tenant_id_unique("code_groups"),  # codes.group_id composite FK 대상(§5)
        UniqueConstraint("tenant_id", "group_key", name="uq_code_groups_tenant_group_key"),
    )

    group_key: Mapped[str] = mapped_column(String, nullable=False)  # 대문자 스네이크
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=expression.false()
    )


class Code(IdMixin, TenantMixin, TimestampMixin, Base):
    """계층 코드(parent_id 자기참조). 그룹 삭제 시 CASCADE, 순환 방지는 앱 검증(docs/03 §4.10)."""

    __tablename__ = "codes"
    __table_args__ = (
        tenant_id_unique("codes"),  # parent_id 자기참조 composite FK 대상(§5)
        tenant_fk("group_id", "code_groups", name="fk_codes_group", ondelete="CASCADE"),
        # parent는 CASCADE 아님 — 자식 있는 코드 삭제는 앱에서 명시 409(ADR-0017).
        tenant_fk("parent_id", "codes", name="fk_codes_parent"),
        UniqueConstraint("tenant_id", "group_id", "code", name="uq_codes_tenant_group_code"),
        Index("ix_codes_tenant_group", "tenant_id", "group_id", "sort_order"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    code: Mapped[str] = mapped_column(String, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=expression.text("0")
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.true())
