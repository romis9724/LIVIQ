"""민원 계약 (docs/03 §4.4, docs/01 §13)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

AiPriority = Literal["urgent", "normal", "low"]
InquiryStatus = Literal["received", "assigned", "in_progress", "done"]
EventType = Literal["created", "ai_classified", "assigned", "status_changed", "comment"]

__all__ = [
    "AiPriority",
    "AssignIn",
    "EventType",
    "InquiryCreateIn",
    "InquiryEventListOut",
    "InquiryEventOut",
    "InquiryListOut",
    "InquiryOut",
    "InquiryStatus",
    "StatusChangeIn",
]


class InquiryCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    category_id: uuid.UUID | None = None


class InquiryOut(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    status: InquiryStatus
    ai_priority: AiPriority | None
    category_id: uuid.UUID | None
    ai_suggested_category_id: uuid.UUID | None
    assignee_user_id: uuid.UUID | None
    author_user_id: uuid.UUID
    created_at: datetime.datetime
    updated_at: datetime.datetime


class InquiryListOut(BaseModel):
    items: list[InquiryOut]


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
