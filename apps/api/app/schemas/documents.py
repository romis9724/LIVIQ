"""documents 계약 (docs/03 §4.2)."""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, Field

SourceType = Literal["규약", "회의록", "공지", "지침", "매뉴얼"]
Visibility = Literal["ALL", "RESIDENT", "ADMIN", "COUNCIL"]
IndexStatus = Literal["pending", "indexing", "indexed", "failed"]

__all__ = [
    "DocumentListOut",
    "DocumentOut",
    "DocumentPatchIn",
    "DocumentUploadOut",
    "IndexStatus",
    "SourceType",
    "Visibility",
]


class DocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    source_type: SourceType
    visibility: Visibility
    index_status: IndexStatus
    created_at: datetime.datetime


class DocumentPatchIn(BaseModel):
    """부분 수정 — 지정한 필드만 갱신(둘 다 None이면 no-op 아님, 422)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    visibility: Visibility | None = None


class DocumentListOut(BaseModel):
    items: list[DocumentOut]


class DocumentUploadOut(BaseModel):
    id: uuid.UUID
    index_status: IndexStatus
    duplicate: bool = False  # content_hash 중복(멱등 인제스트 — 기존 문서 반환)
