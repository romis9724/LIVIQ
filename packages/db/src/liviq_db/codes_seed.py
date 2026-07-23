"""기본 공통 코드 시드 정의 — 마이그레이션과 단지 생성 API의 단일 출처(ADR-0017, docs/03 §4.10).

시스템 그룹(is_system=true)의 기본 코드다. `code`는 단지 생성 시점의 초기 식별자이며,
DOC_CATEGORY는 기존 `documents.source_type` 라벨과 값을 일치시켜 H8-6 참조 전환을 단순화한다.
코드 행은 단지별로 추가·수정·정렬·비활성·삭제할 수 있다(그룹 자체만 잠금).
"""

from __future__ import annotations

from typing import NamedTuple


class CodeSeed(NamedTuple):
    code: str
    label: str


class CodeGroupSeed(NamedTuple):
    group_key: str
    name: str
    codes: tuple[CodeSeed, ...]


def _codes(*labels: str) -> tuple[CodeSeed, ...]:
    """seed 코드는 code=label(한글) — 초기 식별자 겸 표시명(ADR-0017)."""
    return tuple(CodeSeed(label, label) for label in labels)


DEFAULT_CODE_GROUPS: tuple[CodeGroupSeed, ...] = (
    CodeGroupSeed(
        group_key="NOTICE_CATEGORY",
        name="공지 분류",
        codes=_codes("일반", "시설점검", "방역소독", "회의결과", "주민행사", "시스템장애"),
    ),
    CodeGroupSeed(
        group_key="DOC_CATEGORY",
        name="문서 카테고리",
        codes=_codes("규약", "회의록", "공지", "지침", "매뉴얼"),
    ),
    CodeGroupSeed(
        group_key="INQUIRY_CATEGORY",
        name="민원 카테고리",
        codes=_codes("설비", "하자", "소음", "주차", "공용부", "보안", "기타"),
    ),
)
