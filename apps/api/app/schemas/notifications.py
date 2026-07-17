"""인앱 알림함 계약 (docs/03 §4.4, ADR-0012).

인앱 함 적재만 — 외부 자동발송 아님. 본인 알림만 조회·읽음 처리(규칙 4).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Literal

from pydantic import BaseModel

NotificationType = Literal["notice", "inquiry_status", "approval", "system"]

__all__ = [
    "NotificationListOut",
    "NotificationOut",
    "NotificationType",
]


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None
    link: str | None  # 앱 내 딥링크
    read_at: datetime.datetime | None
    created_at: datetime.datetime


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    total: int
    page: int
    limit: int
