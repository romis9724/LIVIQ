"""관리 계약 — /admin/tenants(SYS_ADMIN)·/admin/staff(MANAGER) (H7-2, ADR-0014).

이메일은 초대 요청 입력으로만 받고(EmailStr) 응답엔 노출하지 않는다 — pii_vault 암호화만.
"""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, EmailStr, Field

__all__ = [
    "InviteIn",
    "StaffItem",
    "StaffListOut",
    "TenantCreateIn",
    "TenantItem",
    "TenantListOut",
    "TenantOut",
]


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantOut(BaseModel):
    id: uuid.UUID
    name: str


class TenantItem(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime.datetime


class TenantListOut(BaseModel):
    items: list[TenantItem]


class InviteIn(BaseModel):
    email: EmailStr  # 초대 대상 — login_id는 HMAC 해시, 평문은 pii_vault.email_enc


class StaffItem(BaseModel):
    user_id: uuid.UUID
    roles: list[str]
    status: str
    invited_at: datetime.datetime  # 초대(=생성) 시각


class StaffListOut(BaseModel):
    items: list[StaffItem]
