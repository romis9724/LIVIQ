"""계정·개인정보 — users·user_roles·pii_vault·consents (docs/03 §4.1).

pii_vault는 봉투 암호화 암호문(bytea)만 보관 — 암호화 로직은 앱 서비스(H0 범위 아님, §6).
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import (
    Base,
    IdMixin,
    TenantMixin,
    TimestampMixin,
    tenant_fk,
    tenant_id_unique,
)


class PiiVault(IdMixin, TenantMixin, TimestampMixin, Base):
    """개인정보 분리 저장(암호화). 업무 테이블은 pii_ref만 참조(§6)."""

    __tablename__ = "pii_vault"
    __table_args__ = (tenant_id_unique("pii_vault"),)

    name_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    email_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    birth_date_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # 검색용 keyed HMAC 해시(평문 저장 금지, §6)
    name_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class User(IdMixin, TenantMixin, TimestampMixin, Base):
    """사용자. 식별정보는 pii_vault로 분리. soft delete 대상(§3)."""

    __tablename__ = "users"
    __table_args__ = (
        tenant_id_unique("users"),
        # login_id는 삭제 후 재등록 허용 위해 partial unique(§3)
        Index(
            "uq_users_login_id_active",
            "login_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        tenant_fk("household_id", "households", name="fk_users_household"),
        tenant_fk("pii_ref", "pii_vault", name="fk_users_pii_ref"),
        tenant_fk("approved_by", "users", name="fk_users_approved_by"),
    )

    household_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    login_id: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    roster_matched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    pii_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserRole(IdMixin, TenantMixin, TimestampMixin, Base):
    """역할(다대다). role: RESIDENT|MANAGER|STAFF|FACILITY|COUNCIL|SYS_ADMIN."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role", name="uq_user_roles_tenant_user_role"),
        tenant_fk("user_id", "users", name="fk_user_roles_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)


class Consent(IdMixin, TenantMixin, TimestampMixin, Base):
    """개인정보 동의."""

    __tablename__ = "consents"
    __table_args__ = (tenant_fk("user_id", "users", name="fk_consents_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    granted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    policy_version: Mapped[str | None] = mapped_column(String, nullable=True)
