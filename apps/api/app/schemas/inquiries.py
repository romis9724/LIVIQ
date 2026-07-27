"""민원 계약 (docs/03 §4.4, docs/01 §13, ADR-0018)."""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

Priority = Literal["urgent", "normal", "low"]
InquiryStatus = Literal["received", "assigned", "in_progress", "done", "reopened"]
# "ai_classified"는 과거 행 읽기 호환용(신규 생성 없음, ADR-0018).
# "facility_linked"는 담당자가 승인한 민원-시설 정식 연결·해제(H13-2, ADR-0022).
EventType = Literal[
    "created", "ai_classified", "assigned", "status_changed", "comment", "facility_linked"
]

__all__ = [
    "AssignIn",
    "CategoryIn",
    "CommentIn",
    "EventType",
    "FacilityLinkIn",
    "FacilitySuggestCandidate",
    "FacilitySuggestOut",
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
    # 담당자가 승인한 정식 연결(FR-FAC-05 ①) — 미연결이면 화면이 "추정" 배지로 폴백한다.
    facility_id: uuid.UUID | None = None
    # 연결 액션 응답 편의 필드. 목록·상세에서는 채우지 않는다(프론트가 시설 목록에서 매핑).
    facility_name: str | None = None
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


class CategoryIn(BaseModel):
    category_code_id: uuid.UUID | None


class CommentIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


class FacilityLinkIn(BaseModel):
    """정식 연결 승인 입력. facility_id 또는 code 중 하나 — 둘 다 없으면 연결 해제(FR-FAC-05 ①).

    code는 시설 코드번호(H14-2) — 민원 접수에서 코드로 바로 연결하는 경로. 코드는 단지 안에서만
    유일하므로 resolve도 tenant 스코프다(타 단지 코드는 404).
    """

    facility_id: uuid.UUID | None = None
    code: str | None = Field(default=None, min_length=1, max_length=40)

    @model_validator(mode="after")
    def _only_one_reference(self) -> FacilityLinkIn:
        if self.facility_id is not None and self.code is not None:
            raise ValueError("facility_id와 code는 함께 지정할 수 없습니다")
        return self


class FacilitySuggestCandidate(BaseModel):
    facility_id: uuid.UUID
    name: str
    reason: str


class FacilitySuggestOut(BaseModel):
    """LLM 추천 후보(FR-FAC-05 ②) — 제시일 뿐 연결이 아니다(규칙 8)."""

    candidates: list[FacilitySuggestCandidate]
    masked: bool = True  # 마스킹 게이트 통과 표식 — 실패하면 응답 자체가 없다(규칙 2)


class PriorityIn(BaseModel):
    priority: Priority | None
