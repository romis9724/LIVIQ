"""auth 계약 — /me 응답(상태별 화면 분기 단일 출처, docs/01 §13)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel

__all__ = ["MeOut"]


class MeOut(BaseModel):
    kind: Literal["user", "onboarding"]
    status: str
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID | None
    roles: list[str]
