"""관리비 계약 — 업로드·조회·AI 설명 SSE (docs/01 §13, docs/09 §8.2 H2-5)."""

from __future__ import annotations

import re
import uuid

from pydantic import BaseModel, field_validator

from app.schemas.assistant import AnswerStatus

__all__ = [
    "AdminFeeDetailOut",
    "AdminFeeListOut",
    "AdminFeeRow",
    "BreakdownRow",
    "FeeApplyOut",
    "FeeExplainDoneData",
    "FeeExplainRequest",
    "FeeOut",
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


class BreakdownRow(BaseModel):
    """분배된 관리비 항목 1행 — 순서 보존 리스트로 저장·응답(H8-7)."""

    name: str  # 항목명
    level: int  # 트리 depth(0=대분류)
    amount: int  # 세대당 금액(원, 음수 허용)


class FeeUploadOut(BaseModel):
    upload_id: uuid.UUID
    status: str  # validated (트리 파싱 성공 — 형식 오류는 422)
    period: str
    row_count: int  # 트리 행 수
    total: int  # 분배 합계(합계행 amount, 없으면 대분류 합)
    preview: list[BreakdownRow]  # 상위 레벨(level<=1) 미리보기


class FeeUploadDetailOut(BaseModel):
    upload_id: uuid.UUID
    type: str
    period: str | None
    status: str
    row_count: int | None


class FeeApplyOut(BaseModel):
    upload_id: uuid.UUID
    status: str  # applied
    period: str
    applied: int  # 적재된 세대 수


class FeeOut(BaseModel):
    period: str
    breakdown: list[BreakdownRow] | None
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


class AdminFeeDetailOut(BaseModel):
    """관리자 고지서 상세 — 세대 1건의 분배 내역 전체."""

    period: str
    building_name: str
    floor: int
    unit_no: int
    breakdown: list[BreakdownRow]
    total: int


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
