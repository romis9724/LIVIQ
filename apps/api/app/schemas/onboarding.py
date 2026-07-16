"""온보딩 제출 계약 — /onboarding/profile (docs/01 §13, docs/04 §2)."""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, Field

__all__ = ["ConsentIn", "ProfileIn", "ProfileOut"]

# 가입에 반드시 동의해야 하는 목적(개인정보 처리·명부 대조). 그 외(마케팅 등)는 선택.
REQUIRED_CONSENT_PURPOSES = frozenset({"privacy_required"})
CONSENT_POLICY_VERSION = "2026-07-v1"


class ConsentIn(BaseModel):
    purpose: str = Field(min_length=1, max_length=64)
    granted: bool


class ProfileIn(BaseModel):
    invite_code: str = Field(min_length=1, max_length=64)
    consents: list[ConsentIn]
    name: str = Field(min_length=1, max_length=64)
    birth_date: datetime.date
    building_name: str = Field(min_length=1, max_length=64)
    floor: int
    unit_no: int


class ProfileOut(BaseModel):
    user_id: uuid.UUID
    status: str
    roster_matched: bool
