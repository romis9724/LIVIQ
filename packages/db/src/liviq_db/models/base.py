"""SQLAlchemy 선언적 기반 + 공통 믹스인·헬퍼 (docs/03 §3·5).

- `Base`: 결정적 제약 이름을 위한 naming convention 부착.
- 믹스인: id PK · tenant_id FK · created_at/updated_at 타임스탬프.
- 헬퍼: composite tenant FK(cross-tenant 참조 차단, §5) · UNIQUE(tenant_id, id).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 제약·인덱스 이름을 결정적으로 생성 (마이그레이션 diff 안정화)
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    """id uuid PK — DB에서 gen_random_uuid()로 기본 생성 (PG 13+ 내장)."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TenantMixin:
    """tenant_id (NOT NULL) — tenants 직속 단순 FK. RLS 격리 기준 컬럼(§5)."""

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


class TimestampMixin:
    """created_at + updated_at (§3). updated_at은 DB 트리거로 자동 갱신."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CreatedAtMixin:
    """created_at만 (append·불변 계열 테이블, §4 DDL이 created_at만 명시)."""

    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def tenant_fk(
    local_col: str,
    parent_table: str,
    *,
    name: str,
    ondelete: str | None = None,
) -> ForeignKeyConstraint:
    """Composite tenant FK: (tenant_id, local_col) → parent(tenant_id, id).

    부모의 UNIQUE(tenant_id, id)를 참조해 다른 단지 행 참조를 DB가 거부한다(docs/03 §5).
    """
    return ForeignKeyConstraint(
        ["tenant_id", local_col],
        [f"{parent_table}.tenant_id", f"{parent_table}.id"],
        name=name,
        ondelete=ondelete,
    )


def tenant_id_unique(table: str) -> UniqueConstraint:
    """composite FK 대상용 UNIQUE(tenant_id, id) — 부모 테이블에 부여."""
    return UniqueConstraint("tenant_id", "id", name=f"uq_{table}_tenant_id_id")
