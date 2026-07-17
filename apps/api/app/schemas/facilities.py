"""시설 계약 (docs/03 §4.5, docs/01 §13).

시설 CRUD·장애·정비 이력. AI 제안·자동 상태 변경 없음 — 쓰기는 전부 사람 폼(규칙 8).
Neo4j 반영은 outbox 경유(직접 그래프 쓰기 없음, §13.3).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

FacilityStatus = Literal["normal", "check", "fault", "risk"]

__all__ = [
    "FacilityCreateIn",
    "FacilityDetailOut",
    "FacilityListOut",
    "FacilityOut",
    "FacilityPatchIn",
    "FacilityStatus",
    "IncidentCreateIn",
    "IncidentOut",
    "MaintenanceCreateIn",
    "MaintenanceOut",
]


class FacilityCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    type: str | None = Field(default=None, max_length=100)
    status: FacilityStatus = "normal"
    next_check_at: datetime.datetime | None = None


class FacilityPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    location: str | None = Field(default=None, max_length=200)
    type: str | None = Field(default=None, max_length=100)
    status: FacilityStatus | None = None
    next_check_at: datetime.datetime | None = None


class FacilityOut(BaseModel):
    id: uuid.UUID
    name: str
    location: str | None
    type: str | None
    status: FacilityStatus
    next_check_at: datetime.datetime | None
    created_at: datetime.datetime
    updated_at: datetime.datetime


class FacilityListOut(BaseModel):
    items: list[FacilityOut]
    total: int


class IncidentCreateIn(BaseModel):
    symptom: str = Field(min_length=1, max_length=4000)
    occurred_at: datetime.datetime | None = None
    resolution: str | None = Field(default=None, max_length=4000)
    root_cause: str | None = Field(default=None, max_length=4000)


class IncidentOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    occurred_at: datetime.datetime | None
    symptom: str
    resolution: str | None
    root_cause: str | None
    created_at: datetime.datetime


class MaintenanceCreateIn(BaseModel):
    work: str = Field(min_length=1, max_length=4000)
    performed_at: datetime.datetime | None = None
    performer: str | None = Field(default=None, max_length=200)
    parts: dict[str, Any] | None = None


class MaintenanceOut(BaseModel):
    id: uuid.UUID
    facility_id: uuid.UUID
    performed_at: datetime.datetime | None
    work: str
    performer: str | None
    parts: dict[str, Any] | None
    created_at: datetime.datetime


class FacilityDetailOut(FacilityOut):
    incidents: list[IncidentOut]
    maintenance_logs: list[MaintenanceOut]
