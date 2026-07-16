"""명부 업로드 계약 — /admin/roster/upload (docs/01 §13, docs/03 §4.1 diff 병합)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel

__all__ = ["RosterRowError", "RosterUploadOut"]


class RosterRowError(BaseModel):
    row: int  # 엑셀 행 번호(헤더=1, 데이터 첫 행=2)
    reason: str


class RosterUploadOut(BaseModel):
    upload_id: uuid.UUID
    applied: int  # 신규 사전등록된 행 수
    marked_inactive: int  # 명부에서 사라져 inactive 표시된 pre_registered 행 수
    errors: list[RosterRowError]
