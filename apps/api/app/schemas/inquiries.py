"""민원 계약 (docs/03 §4.4, docs/01 §13, ADR-0018)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

Priority = Literal["urgent", "normal", "low"]
InquiryStatus = Literal["received", "assigned", "in_progress", "done"]
# "ai_classified"는 과거 행 읽기 호환용(신규 생성 없음, ADR-0018).
EventType = Literal["created", "ai_classified", "assigned", "status_changed", "comment"]

__all__ = [
    "AssignIn",
    "CommentIn",
    "EventType",
    "InquiryCategoryListOut",
    "InquiryCategoryOut",
    "InquiryCreateIn",
    "InquiryEventListOut",
    "InquiryEventOut",
    "InquiryListOut",
    "InquiryOut",
    "InquiryStatus",
    "Priority",
    "PriorityIn",
    "StatusChangeIn",
]


class InquiryCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    category_code_id: uuid.UUID | None = None


class InquiryOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    status: InquiryStatus
    priority: Priority | None
    category_code_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    author_user_id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class InquiryListOut(BaseModel):
    items: list[InquiryOut]


class InquiryCategoryOut(BaseModel):
    id: uuid.UUID
    label: str


class InquiryCategoryListOut(BaseModel):
    items: list[InquiryCategoryOut]


class InquiryEventOut(BaseModel):
    id: uuid.UUID
    type: EventType
    actor_user_id: uuid.UUID | None
    payload: dict[str, Any] | None
    created_at: datetime.datetime


class InquiryEventListOut(BaseModel):
    items: list[InquiryEventOut]


class AssignIn(BaseModel):
    assignee_user_id: uuid.UUID


class StatusChangeIn(BaseModel):
    status: InquiryStatus


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class PriorityIn(BaseModel):
    priority: Priority | None
