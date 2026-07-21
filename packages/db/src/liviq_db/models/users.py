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
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
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
    # 명부 대조 키(성함+생일+동호) 구성용 해시(H2-1, §4.1)
    birth_date_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # 이 레코드 암호화에 쓴 DEK 버전(무중단 키 회전, ADR-0010)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))


class TenantKey(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """per-tenant DEK 저장(KEK로 감싼 wrapped key, ADR-0010).

    append-only — 키 회전은 새 key_version INSERT로만. UPDATE/DELETE는 권한으로 차단.
    """

    __tablename__ = "tenant_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key_version", name="uq_tenant_keys_tenant_key_version"),
    )

    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


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
    # 로그인 식별자 = 이메일 keyed HMAC 해시(평문 이메일은 pii_vault.email_enc, ADR-0014)
    login_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # 비밀번호 Argon2id 해시(평문·복호가능 형태 금지). 초대 미설정 계정은 NULL(ADR-0014)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    # 이메일 검증 완료 시각 — NULL이면 로그인 불가(가입 검증 메일 필수, ADR-0014)
    email_verified_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 임시 비밀번호 강제 변경 플래그(부트스트랩 SYS_ADMIN) — True면 세션이 password-change·
    # logout·me 외 엔드포인트에서 403(app.deps.get_context 가드, ADR-0014·H7-2)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # registered=가입 완료·프로필 미제출(온보딩 필요 신호). 이후 pending→active(승인)
    # invited=초대 발송·수락 전(SYS_ADMIN→소장·소장→직원, H7-2). 수락 시 active 전환
    # pre_registered|invited|registered|pending|active|inactive|rejected|withdrawn
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
    """역할(다대다). role: RESIDENT|MANAGER|STAFF|SYS_ADMIN(H7-2에서 FACILITY·COUNCIL 제거)."""

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "role", name="uq_user_roles_tenant_user_role"),
        tenant_fk("user_id", "users", name="fk_user_roles_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)


class AuthToken(IdMixin, TenantMixin, CreatedAtMixin, Base):
    """이메일 인증·초대·재설정 1회용 토큰(ADR-0014).

    원문 토큰은 URL로만 전달하고 DB엔 SHA-256 해시만 저장한다(유출 시에도 원문 복원 불가).
    token_hash는 클릭 시점 tenant 확정 전 전역 조회 대상 = 글로벌 unique. 소진은 used_at 기록.
    """

    __tablename__ = "auth_tokens"
    __table_args__ = (
        tenant_fk("user_id", "users", name="fk_auth_tokens_user"),
        Index("uq_auth_tokens_token_hash", "token_hash", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String, nullable=False
    )  # verify_email|invite|reset_password
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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
