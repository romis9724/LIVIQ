"""공통 코드 레지스트리 계약 — /admin/code-groups·/admin/codes (docs/01 §13 · ADR-0017).

그룹 조회는 코드를 **평면 리스트 + parent_id 포함**으로 반환한다(프론트가 트리 구성). group_key는
대문자 스네이크(생성 시만, 이후 불변). 코드 계층 순환 방지는 라우터가 소유(스키마는 형태만 검증).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

# 대문자 스네이크(첫 글자 영문 대문자, 이후 대문자·숫자·언더스코어).
GROUP_KEY_PATTERN = r"^[A-Z][A-Z0-9_]*$"

__all__ = [
    "CodeCreateIn",
    "CodeGroupCreateIn",
    "CodeGroupListOut",
    "CodeGroupOut",
    "CodeGroupUpdateIn",
    "CodeOut",
    "CodeUpdateIn",
]


class CodeOut(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    parent_id: uuid.UUID | None
    code: str
    label: str
    sort_order: int
    active: bool


class CodeGroupOut(BaseModel):
    id: uuid.UUID
    group_key: str
    name: str
    description: str | None
    is_system: bool
    codes: list[CodeOut] = []


class CodeGroupListOut(BaseModel):
    items: list[CodeGroupOut]


class CodeGroupCreateIn(BaseModel):
    group_key: str = Field(pattern=GROUP_KEY_PATTERN, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class CodeGroupUpdateIn(BaseModel):
    """name·description만 수정 — group_key는 불변(스키마에 없음)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class CodeCreateIn(BaseModel):
    group_id: uuid.UUID
    code: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None
    sort_order: int = 0


class CodeUpdateIn(BaseModel):
    """label·sort_order·active·parent_id 수정. parent_id 미지정 시 불변(model_fields_set)."""

    label: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = None
    active: bool | None = None
    parent_id: uuid.UUID | None = None
