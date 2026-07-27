"""기본 공통 코드 시드 정의 — 마이그레이션과 단지 생성 API의 단일 출처(ADR-0017, docs/03 §4.10).

시스템 그룹(is_system=true)의 기본 코드다. `code`는 단지 생성 시점의 초기 식별자이며,
DOC_CATEGORY는 기존 `documents.source_type` 라벨과 값을 일치시켜 H8-6 참조 전환을 단순화한다.
코드 행은 단지별로 추가·수정·정렬·비활성·삭제할 수 있다(그룹 자체만 잠금).
"""

from __future__ import annotations

from typing import NamedTuple

from liviq_db.facility_systems import FACILITY_SYSTEMS


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
    # 시설 코드(H14-2)의 계통 약어 — code=약어·label=한글. facility_systems 단일 출처에서 파생.
    CodeGroupSeed(
        group_key="FACILITY_SYSTEM",
        name="시설 계통",
        codes=tuple(CodeSeed(s.abbr, s.label) for s in FACILITY_SYSTEMS),
    ),
    # 평면도 요소·방 종류(H14-2) — 값은 ai_core.tools.floor_plan_parser의 사전 키와 일치해야
    # 한다(패키지 의존 방향상 임포트 불가 — 드리프트는 apps/api 테스트가 잡는다).
    CodeGroupSeed(
        group_key="PLAN_DEVICE_TYPE",
        name="평면도 요소 종류",
        codes=_codes(
            "콘센트",
            "분전함",
            "통신단자함",
            "TV·인터넷 단자",
            "가스밸브",
            "수도 차단밸브",
            "보일러",
            "난방 분배기",
            "온도조절기",
            "에어컨 배관",
            "소화기",
            "화재감지기",
            "경량칸막이",
            "월패드",
        ),
    ),
    CodeGroupSeed(
        group_key="PLAN_ROOM",
        name="평면도 방",
        codes=_codes(
            "거실",
            "주방",
            "안방",
            "침실1",
            "침실2",
            "욕실1",
            "욕실2",
            "현관",
            "팬트리",
            "다용도실",
            "발코니(전면)",
            "발코니(후면)",
            "발코니(측면)",
            "실외기실",
        ),
    ),
)
