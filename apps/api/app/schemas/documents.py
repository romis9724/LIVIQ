"""documents 계약 (docs/03 §4.2, ADR-0016)."""

from __future__ import annotations

import datetime
import unicodedata
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

Visibility = Literal["ALL", "RESIDENT", "ADMIN"]
IndexStatus = Literal["pending", "indexing", "indexed", "failed"]

BODY_MAX = 20000
TITLE_MAX = 200

__all__ = [
    "BODY_MAX",
    "TITLE_MAX",
    "DocumentDetailOut",
    "DocumentListOut",
    "DocumentOut",
    "DocumentPatchIn",
    "DocumentTitle",
    "DocumentVersionOut",
    "IndexStatus",
    "Visibility",
    "clean_title",
]

# 제어(Cc)·서식(Cf) 문자 — zero-width(U+200B~200D)·BOM(U+FEFF)·word joiner(U+2060) 포함.
# 개행·탭은 남겨 뒀다가 공백 접기에서 한 칸으로 바뀐다.
_KEEP_CONTROL = {"\n", "\r", "\t"}
_INVISIBLE_CATEGORIES = {"Cc", "Cf"}


def clean_title(value: str) -> str:
    """제목 정규화 — NFC 합성 + 보이지 않는 문자 제거 + 공백 접기(빈 제목은 거부).

    macOS 파일명은 한글이 NFD(자모 분해)로 오고, 웹 업로드 폼이 파일명을 제목 기본값으로
    채운다 — 그대로 저장하면 화면엔 같아 보여도 LIKE·검색이 전부 어긋난다(dev 실측).
    """
    composed = unicodedata.normalize("NFC", value)
    visible = "".join(
        ch
        for ch in composed
        if ch in _KEEP_CONTROL or unicodedata.category(ch) not in _INVISIBLE_CATEGORIES
    )
    cleaned = " ".join(visible.split())
    if not cleaned:
        raise ValueError("제목이 비어 있음")
    return cleaned


# 제목 저장 경로 공용 타입(작성 Form·수정 PATCH) — 경계에서 한 번만 정규화한다.
DocumentTitle = Annotated[
    str, Field(min_length=1, max_length=TITLE_MAX), AfterValidator(clean_title)
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
    category_code_id: uuid.UUID  # DOC_CATEGORY 그룹 코드(작성 시 필수)
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

    title: DocumentTitle | None = None
    body: str | None = Field(default=None, max_length=BODY_MAX)
    category_code_id: uuid.UUID | None = None
    visibility: Visibility | None = None
