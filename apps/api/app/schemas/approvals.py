"""가입 승인 계약 — /admin/approvals (docs/01 §13). 이름은 마스킹만 노출(docs/06 §6)."""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel, Field

__all__ = ["ApprovalListOut", "ApprovalOut", "RejectIn"]


class ApprovalOut(BaseModel):
    user_id: uuid.UUID
    name_masked: str  # 복호화 후 마스킹(홍*동) — 원문 노출 금지
    roster_matched: bool
    # 불일치 사유(H7-9) — roster_matched=False일 때만: no_household_roster(명부에 해당 세대
    # 없음) · person_mismatch(세대는 있으나 성함·생년 불일치) · all_consumed(세대 명부 전원 가입).
    mismatch_reason: str | None = None
    building_name: str | None
    floor: int | None
    unit_no: int | None
    requested_at: datetime.datetime


class ApprovalListOut(BaseModel):
    items: list[ApprovalOut]


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
