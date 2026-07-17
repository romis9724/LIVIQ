"""AI 검수 큐 계약 (docs/01 §13, docs/03 §4.3, docs/04 §3).

사후 검수 — 신뢰도 낮은 assistant 답변을 사람이 승인/반려한다(규칙 6). 회수·재발송 없음.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

ReviewStatus = Literal["needs_review", "approved", "rejected"]
ReviewAction = Literal["approve", "reject"]

__all__ = [
    "DecideIn",
    "ReviewAction",
    "ReviewCitationOut",
    "ReviewItemOut",
    "ReviewListOut",
    "ReviewStatus",
]


class ReviewCitationOut(BaseModel):
    document_title: str | None
    quote: str | None


class ReviewItemOut(BaseModel):
    message_id: uuid.UUID
    question: str | None  # 직전 user 메시지(없으면 null)
    answer: str
    confidence: float | None
    status: str | None  # answered|fallback|handed_off
    citations: list[ReviewCitationOut]
    created_at: datetime.datetime
    review_status: ReviewStatus
    reviewed_at: datetime.datetime | None
    review_note: str | None


class ReviewListOut(BaseModel):
    items: list[ReviewItemOut]
    total: int
    page: int
    limit: int


class DecideIn(BaseModel):
    action: ReviewAction
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_note_on_reject(self) -> Self:
        if self.action == "reject" and not (self.note and self.note.strip()):
            raise ValueError("반려 사유(note)는 필수입니다")
        return self
