"""공지 계약 (docs/03 §4.4, docs/01 §13).

초안은 AI 생성(근거 강제)이고 발행은 사람 확정이다(규칙 6) — 요청/응답을 분리한다.
audience는 현재 "ALL"만(building·household 타게팅은 백로그).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, Field, field_validator

NoticeStatus = Literal["draft", "published", "retracted", "superseded"]
Audience = Literal["ALL"]

__all__ = [
    "Audience",
    "DraftDetailOut",
    "DraftOut",
    "DraftRequestIn",
    "NoticeCitationOut",
    "NoticeListOut",
    "NoticeOut",
    "NoticeStatus",
    "PublishIn",
]


class DraftRequestIn(BaseModel):
    keywords: list[str] = Field(min_length=1, max_length=10)

    @field_validator("keywords")
    @classmethod
    def _non_empty_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [k.strip() for k in value if k.strip()]
        if not cleaned:
            raise ValueError("빈 키워드")
        if any(len(k) > 100 for k in cleaned):
            raise ValueError("키워드는 100자 이하")
        return cleaned


class NoticeCitationOut(BaseModel):
    document_id: uuid.UUID
    document_title: str
    chunk_id: uuid.UUID
    quote: str


class DraftOut(BaseModel):
    draft_id: uuid.UUID
    title: str
    body: str
    citations: list[NoticeCitationOut]
    confidence: float


class DraftDetailOut(BaseModel):
    draft_id: uuid.UUID
    title: str
    body: str
    keywords: list[str]
    review_status: str
    notice_id: uuid.UUID | None
    created_at: datetime.datetime


class PublishIn(BaseModel):
    draft_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    audience: Audience = "ALL"
    scheduled_at: datetime.datetime | None = None


class NoticeOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    status: NoticeStatus
    audience: str
    scheduled_at: datetime.datetime | None
    published_at: datetime.datetime | None
    published_by: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class NoticeListOut(BaseModel):
    items: list[NoticeOut]
