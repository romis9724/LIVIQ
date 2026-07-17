"""assistant SSE 계약 — 이벤트 4종(token·citation·status·done), 스키마 불변(docs/09 §1.1)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

QUESTION_MAX_CHARS = 2000  # 거대 붙여넣기 거절(docs/08 §8)

StatusStage = Literal["searching", "generating", "verifying"]
AnswerStatus = Literal["answered", "fallback"]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=QUESTION_MAX_CHARS)
    conversation_id: uuid.UUID | None = None


# ── SSE data 페이로드 (이벤트 이름은 token|citation|status|done) ────────


class StatusData(BaseModel):
    stage: StatusStage


class TokenData(BaseModel):
    text: str


class CitationData(BaseModel):
    ref: int
    document_id: uuid.UUID | None = None  # 문서 인용은 UUID, 확정 데이터(관리비 등) 인용은 null
    document_title: str
    quote: str
    page: int | None = None
    clause: str | None = None


class DoneData(BaseModel):
    message_id: uuid.UUID | None = None  # 폴백 등 미저장 시 None
    conversation_id: uuid.UUID
    status: AnswerStatus
    confidence: float
    needs_review: bool
    fallback_reason: str | None = None
