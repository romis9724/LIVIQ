"""documents 계약 (docs/03 §4.2, ADR-0016)."""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["규약", "회의록", "공지", "지침", "매뉴얼"]
Visibility = Literal["ALL", "RESIDENT", "ADMIN"]
IndexStatus = Literal["pending", "indexing", "indexed", "failed"]

BODY_MAX = 20000

__all__ = [
    "DocumentDetailOut",
    "DocumentListOut",
    "DocumentOut",
    "DocumentPatchIn",
    "DocumentVersionOut",
    "IndexStatus",
    "SourceType",
    "Visibility",
]


class DocumentVersionOut(BaseModel):
    version: int
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime.datetime


class DocumentOut(BaseModel):
    """게시판 목록 항목 — 본문 제외(경량). 상세는 DocumentDetailOut."""

    id: uuid.UUID
    title: str
    source_type: SourceType
    visibility: Visibility
    version: int
    index_status: IndexStatus
    created_at: datetime.datetime
    updated_at: datetime.datetime


class DocumentDetailOut(DocumentOut):
    body: str | None = None
    versions: list[DocumentVersionOut]


class DocumentListOut(BaseModel):
    items: list[DocumentOut]


class DocumentPatchIn(BaseModel):
    """부분 수정 — 지정한 필드만 갱신(None = 미변경, body는 빈 문자열로 비운다)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=BODY_MAX)
    source_type: SourceType | None = None
    visibility: Visibility | None = None
