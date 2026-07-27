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

GraphNodeLabel = Literal[
    "facility", "incident", "maintenance", "floor_plan", "plan_device", "location", "complex"
]
GraphLinkKind = Literal[
    "HAS_INCIDENT", "HAS_MAINTENANCE", "HAS_DEVICE", "LINKED_TO", "LOCATED_IN", "PART_OF"
]

__all__ = [
    "FacilityCreateIn",
    "FacilityDetailOut",
    "FacilityGraphOut",
    "FacilityListOut",
    "FacilityOut",
    "FacilityPatchIn",
    "FacilityStatus",
    "GraphLinkKind",
    "GraphLinkOut",
    "GraphNodeLabel",
    "GraphNodeOut",
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


class GraphNodeOut(BaseModel):
    """그래프 노드(H13-1, ADR-0022). 라벨별로 채워지는 필드가 다르다 — embedding은 없음."""

    pg_id: str
    label: GraphNodeLabel
    name: str | None = None  # 시설명 | 장애 증상 | 정비 작업
    type: str | None = None  # 시설 계통(계통 렌즈)
    location: str | None = None
    # 파생 그래프 값이라 Literal로 좁히지 않는다(동기화 지연 값이 500이 되면 안 됨)
    status: str | None = None
    at: str | None = None  # 장애 발생/정비 수행 시각(그래프 스냅샷 문자열)
    resolved: bool | None = None  # 장애: 조치 내역 유무


class GraphLinkOut(BaseModel):
    source: str
    target: str
    kind: GraphLinkKind


class FacilityGraphOut(BaseModel):
    nodes: list[GraphNodeOut]
    links: list[GraphLinkOut]
    degraded: bool = False  # Neo4j 미가용 → PG 축약 그래프(노드만)
