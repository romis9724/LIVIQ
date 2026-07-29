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
    # 호출한 도구 이름 순서(H3-4) — additive 필드, SSE 이벤트 4종 계약 불변.
    tool_path: list[str] = Field(default_factory=list)
    # 토큰 usage(H15-2 질의당 원가 계량) — additive 필드, SSE 이벤트 4종 계약 불변.
    # usage 없는 경로(근거 0 폴백 등)는 None. token_estimated=True면 프로바이더 미제공 추정치다.
    token_input: int | None = None
    token_output: int | None = None
    token_estimated: bool = False
    # 서버가 확정한 답변 본문 — 클라이언트는 이 값이 있으면 **정본으로** 쓴다(additive 필드).
    # 인용 누락 재요청(H15-2 R21) 때 1차 답변은 이미 token으로 흘렀고 재요청 결과는 스트리밍하지
    # 않는다(두 답변이 화면에서 이어붙는다). 그래서 최종본을 여기로 전달한다.
    answer: str | None = None
