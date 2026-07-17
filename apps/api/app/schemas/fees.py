"""관리비 계약 — 업로드·조회·AI 설명 SSE (docs/01 §13, docs/09 §8.2 H2-5)."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, field_validator

from app.schemas.assistant import AnswerStatus

__all__ = [
    "AdminFeeListOut",
    "AdminFeeRow",
    "FeeExplainDoneData",
    "FeeExplainRequest",
    "FeeOut",
    "FeePreviewRow",
    "FeeRowErrorOut",
    "FeeUploadDetailOut",
    "FeeUploadOut",
    "validate_period",
]

_PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_period(period: str) -> str:
    """YYYY-MM 형식 검증(월 01~12). 라우터 쿼리·바디 공용."""
    if not _PERIOD_RE.match(period):
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail="period는 YYYY-MM 형식이어야 합니다")
    return period


class FeeRowErrorOut(BaseModel):
    row: int
    reason: str


class FeePreviewRow(BaseModel):
    building_name: str  # 동
    floor: int
    unit_no: int
    breakdown: dict[str, int]  # 항목명 → 금액
    total: int


class FeeUploadOut(BaseModel):
    upload_id: uuid.UUID
    status: str  # validated|failed
    period: str
    row_count: int  # 구조 파싱된 데이터 행 수
    valid_rows: int  # 세대 매칭까지 성공한 행 수
    errors: list[FeeRowErrorOut]
    preview: list[FeePreviewRow]  # 첫 20행(업로드 시점 1회, 저장 안 함)


class FeeUploadDetailOut(BaseModel):
    upload_id: uuid.UUID
    type: str
    period: str | None
    status: str
    row_count: int | None
    errors: list[FeeRowErrorOut]
    # ponytail: 미리보기 rows는 저장하지 않는다 — 재확인은 원본 재업로드/apply로. errors만 재표시.


class FeeApplyOut(BaseModel):
    upload_id: uuid.UUID
    status: str  # applied
    period: str
    applied: int  # 적재된 세대 수


class FeeOut(BaseModel):
    period: str
    breakdown: dict[str, int] | None
    total: int | None
    prev_total: int | None  # 전월 합계(추이용, 있으면)


class AdminFeeRow(BaseModel):
    household_id: uuid.UUID
    building_name: str
    floor: int
    unit_no: int
    total: int


class AdminFeeListOut(BaseModel):
    period: str
    households: list[AdminFeeRow]
    total_sum: int
    household_count: int


class FeeExplainRequest(BaseModel):
    period: str

    @field_validator("period")
    @classmethod
    def _period(cls, v: str) -> str:
        if not _PERIOD_RE.match(v):
            raise ValueError("period는 YYYY-MM 형식이어야 합니다")
        return v


class FeeExplainDoneData(BaseModel):
    """explain SSE done 페이로드 — 대화·메시지 영속 없음(조회+설명 전용)."""

    status: AnswerStatus
    confidence: float
    needs_review: bool
    fallback_reason: str | None = None
