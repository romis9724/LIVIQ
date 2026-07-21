"""명부 계약 — /admin/roster 업로드·목록 (docs/01 §13, docs/03 §4.1 diff 병합, H7-9)."""

from __future__ import annotations

import datetime
import uuid

from pydantic import BaseModel

__all__ = [
    "RosterCounts",
    "RosterEntry",
    "RosterLastUpload",
    "RosterListOut",
    "RosterRowError",
    "RosterStateIn",
    "RosterUploadOut",
]


class RosterRowError(BaseModel):
    row: int  # 엑셀 행 번호(헤더=1, 데이터 첫 행=2)
    reason: str


class RosterUploadOut(BaseModel):
    upload_id: uuid.UUID
    applied: int  # 신규 사전등록된 행 수
    marked_inactive: int  # 명부에서 사라져 inactive 표시된 pre_registered 행 수
    errors: list[RosterRowError]


class RosterEntry(BaseModel):
    """명부 한 행(H7-9) — 성함 마스킹·생년월일 비표시(상시 노출 최소화, 운영자 결정)."""

    user_id: uuid.UUID  # 상태 변경·삭제 대상 식별(H7-9 보강)
    name_masked: str
    building_name: str | None
    floor: int | None
    unit_no: int | None
    state: str  # unregistered=미가입 · joined=가입완료(소진) · moved_out=전출 후보


class RosterStateIn(BaseModel):
    """명부 행 수동 상태 변경 — 미가입 ↔ 전출 후보(소장 판단, H7-9 보강)."""

    state: str  # unregistered | moved_out


class RosterCounts(BaseModel):
    total: int
    unregistered: int
    joined: int
    moved_out: int


class RosterLastUpload(BaseModel):
    uploaded_at: datetime.datetime
    row_count: int
    error_count: int


class RosterListOut(BaseModel):
    items: list[RosterEntry]
    total: int  # 필터 적용 후 전체 건수(페이지네이션 분모)
    counts: RosterCounts  # 필터 무관 전체 총계
    last_upload: RosterLastUpload | None
