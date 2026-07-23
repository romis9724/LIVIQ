"""관리 계약 — /admin/tenants(SYS_ADMIN)·/admin/staff(MANAGER) (H7-2, ADR-0014).

직원 목록은 이메일을 표시한다(ADR-0014 개정, H7-5) — 이메일 없는 목록은 행 식별 불가.
저장은 여전히 pii_vault 암호화·login_id HMAC뿐, 응답은 MANAGER 인가 뒤에서만 복호.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, EmailStr, Field

__all__ = [
    "InviteIn",
    "InviteStaffIn",
    "StaffItem",
    "StaffListOut",
    "TenantCreateIn",
    "TenantItem",
    "TenantListOut",
    "TenantManagerItem",
    "TenantOut",
]


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str


class TenantManagerItem(BaseModel):
    """단지의 현재 소장(H7-6) — 이메일은 복호 실패·PII 부재 시 None."""

    user_id: uuid.UUID
    email: str | None = None
    status: str  # invited=수락 대기 · active=활동 중


class TenantItem(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime.datetime
    status: str = "active"  # active | inactive(비활성화 — 소속 로그인 차단, H7-6)
    manager: TenantManagerItem | None = None


class TenantListOut(BaseModel):
    items: list[TenantItem]


class InviteIn(BaseModel):
    email: EmailStr  # 초대 대상 — login_id는 HMAC 해시, 평문은 pii_vault.email_enc


class InviteStaffIn(BaseModel):
    """직원 초대 — 소장이 이름을 입력해 목록 식별이 가능하도록 name 필수(ADR-0018)."""

    email: EmailStr
    name: str = Field(min_length=1, max_length=100)  # pii_vault.name_enc 암호화 저장


class StaffItem(BaseModel):
    user_id: uuid.UUID
    roles: list[str]
    status: str
    invited_at: datetime.datetime  # 초대(=생성) 시각
    email: str | None = None  # 복호 실패·PII 부재 시 None(행은 유지)
    name: str | None = None  # 복호 실패·PII 부재(초대 대기 등) 시 None


class StaffListOut(BaseModel):
    items: list[StaffItem]
