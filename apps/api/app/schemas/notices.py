"""공지 게시판 계약 (docs/03 §4.4, docs/01 §13 · ADR-0015).

공지는 일반 게시판이다(AI 초안 폐기). 작성/수정 입력, 조회 출력, 첨부 메타를 분리한다.
audience는 현재 "ALL"만(building·household 타게팅은 백로그).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

NoticeStatus = Literal["draft", "scheduled", "published"]
Audience = Literal["ALL"]

__all__ = [
    "AttachmentOut",
    "Audience",
    "NoticeCreateIn",
    "NoticeListOut",
    "NoticeOut",
    "NoticeStatus",
    "NoticeUpdateIn",
]


def _ensure_future(value: datetime.datetime) -> datetime.datetime:
    """예약 시각은 미래여야 한다. naive는 UTC로 간주(경계 정규화)."""
    at = value if value.tzinfo is not None else value.replace(tzinfo=datetime.UTC)
    if at <= datetime.datetime.now(datetime.UTC):
        raise ValueError("scheduled_at은 미래 시각이어야 함")
    return at


class NoticeCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    audience: Audience = "ALL"
    status: NoticeStatus = "draft"
    pinned: bool = False
    scheduled_at: datetime.datetime | None = None

    @model_validator(mode="after")
    def _validate_schedule(self) -> NoticeCreateIn:
        if self.status == "scheduled":
            if self.scheduled_at is None:
                raise ValueError("status=scheduled는 scheduled_at 필수")
            object.__setattr__(self, "scheduled_at", _ensure_future(self.scheduled_at))
        else:
            object.__setattr__(self, "scheduled_at", None)  # 비예약은 예약 시각 무시
        return self


class NoticeUpdateIn(BaseModel):
    """부분 수정. 미지정 필드는 불변(model_fields_set로 판별)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=20000)
    audience: Audience | None = None
    pinned: bool | None = None
    status: NoticeStatus | None = None
    scheduled_at: datetime.datetime | None = None

    @model_validator(mode="after")
    def _validate_schedule(self) -> NoticeUpdateIn:
        if self.status == "scheduled":
            if self.scheduled_at is None:
                raise ValueError("status=scheduled는 scheduled_at 필수")
            object.__setattr__(self, "scheduled_at", _ensure_future(self.scheduled_at))
        return self


class AttachmentOut(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime.datetime


class NoticeOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    status: NoticeStatus
    pinned: bool
    audience: str
    scheduled_at: datetime.datetime | None
    published_at: datetime.datetime | None
    published_by: uuid.UUID | None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    attachments: list[AttachmentOut] = []


class NoticeListOut(BaseModel):
    items: list[NoticeOut]
