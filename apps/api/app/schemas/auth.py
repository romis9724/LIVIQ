"""auth 계약 — 가입·로그인·비밀번호 재설정 + /me(상태별 화면 분기, ADR-0014, docs/01 §13).

비밀번호 길이 정책(≥10자)은 경계에서 강제(위반 시 422). 이메일은 EmailStr로 형식 검증.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.password import MIN_PASSWORD_LENGTH

__all__ = [
    "InviteAcceptIn",
    "LoginIn",
    "LoginOut",
    "MeOut",
    "PasswordChangeIn",
    "PasswordResetConfirmIn",
    "PasswordResetIn",
    "SignupIn",
    "SignupOut",
]


class SignupIn(BaseModel):
    tenant_id: uuid.UUID  # 단지별 가입 링크가 실어 나르는 단지 식별자(ADR-0014)
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class SignupOut(BaseModel):
    user_id: uuid.UUID


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class LoginOut(BaseModel):
    status: str  # registered=온보딩 필요 · pending=승인 대기 · active=정상


class PasswordResetIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    token: str = Field(min_length=1)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=1)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)


class MeOut(BaseModel):
    status: str  # status='registered'가 온보딩 필요 신호(ADR-0014)
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None
    roles: list[str]
    must_change_password: bool = False  # True면 웹은 비밀번호 변경 화면으로 강제(H7-2)
