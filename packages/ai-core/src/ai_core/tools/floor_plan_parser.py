"""평면도 위치 질의 규칙 파서 (FR-PLAN-03, ADR-0007 규칙 8).

동의어사전·묶음 사전은 참조 프로토타입 `apt-facility-finder/server/query.js`가 정본 —
그대로 이식(순서·항목 동일). 순수 함수만 담는다(LLM·세션 의존 없음, 0ms 1차 경로,
단위 테스트 대상). intent(count/count_max) 분기는 FR-PLAN-03 범위 밖(위치 조회만).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ELEMENT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "콘센트": ("콘센트", "플러그", "전기 코드", "코드 꽂", "충전"),
    "분전함": ("분전함", "두꺼비집", "누전차단기", "차단기", "브레이커"),
    "통신단자함": ("통신단자함", "단자함", "공유기", "허브"),
    "TV·인터넷 단자": (
        "tv·인터넷 단자",
        "tv 단자",
        "티비 단자",
        "인터넷 단자",
        "랜선",
        "랜 포트",
        "인터넷",
    ),
    "가스밸브": ("가스밸브", "가스 밸브", "가스 잠그", "가스 차단"),
    "수도 차단밸브": (
        "수도 차단밸브",
        "수도밸브",
        "수도 밸브",
        "물 잠그",
        "수도 잠그",
        "물 새",
        "누수",
    ),
    "보일러": ("보일러",),
    "난방 분배기": ("난방 분배기", "분배기", "난방 밸브", "온수 분배"),
    "온도조절기": ("온도조절기", "온도 조절", "난방 조절", "실내 온도"),
    "에어컨 배관": ("에어컨 배관", "에어컨"),
    "소화기": ("소화기",),
    "화재감지기": ("화재감지기", "화재 감지기", "감지기", "화재경보"),
    "경량칸막이": (
        "경량칸막이",
        "경량 칸막이",
        "비상탈출",
        "비상 탈출",
        "비상구",
        "대피",
        "탈출구",
    ),
    "월패드": ("월패드", "인터폰", "비디오폰", "도어폰"),
}

ELEMENT_GROUPS: dict[str, tuple[str, ...]] = {
    "안전": ("소화기", "화재감지기", "경량칸막이"),
    "소방": ("소화기", "화재감지기"),
    "불": ("소화기", "화재감지기", "경량칸막이"),
}

ROOM_SYNONYMS: dict[str, tuple[str, ...]] = {
    "거실": ("거실",),
    "주방": ("주방", "부엌", "키친"),
    "안방": ("안방", "큰방", "마스터룸"),
    "침실1": ("침실1", "작은방"),
    "침실2": ("침실2", "가운데방"),
    "욕실1": ("욕실1",),
    "욕실2": ("욕실2",),
    "현관": ("현관",),
    "팬트리": ("팬트리",),
    "다용도실": ("다용도실",),
    "발코니(전면)": ("발코니(전면)", "앞 발코니"),
    "발코니(후면)": ("발코니(후면)", "뒷 발코니"),
    "발코니(측면)": ("발코니(측면)", "옆 발코니"),
    "실외기실": ("실외기실", "실외기"),
}

ROOM_GROUPS: dict[str, tuple[str, ...]] = {
    "침실": ("안방", "침실1", "침실2"),
    "방": ("안방", "침실1", "침실2"),
    "욕실": ("욕실1", "욕실2"),
    "화장실": ("욕실1", "욕실2"),
    "발코니": ("발코니(전면)", "발코니(후면)", "발코니(측면)"),
    "베란다": ("발코니(전면)", "발코니(후면)", "발코니(측면)"),
}


# 동·호수 추출 — 패턴은 masking/masker.py의 UNIT과 **같은 형태**여야 한다(캡처 그룹만 추가).
# 갈라지면 마스킹은 가리는데 여기선 못 뽑는 조합(또는 그 반대)이 생겨, 관리자 분기가
# "동·호수 있음"으로 판정하고도 조회 대상이 없는 상태가 된다(H20-17).
# `(?!기)`도 같은 이유로 유지 — "403동 2호기"는 세대가 아니라 설비 호기다.
_UNIT_PATTERN = re.compile(
    r"(?P<dong>\d{1,4})\s*동\s*(?P<ho>\d{1,4})\s*호(?!기)"
    r"|(?:동호수|호수)\s*[:：]?\s*(?P<dong_alt>\d{1,4})\s*-\s*(?P<ho_alt>\d{1,4})"
)


def parse_unit(query: str) -> tuple[str, int] | None:
    """질의에서 (동 이름, 호수)를 뽑는다 — 없으면 None.

    관리자 채널에서 **코드가** 조회 대상 세대를 정하는 경로다(LLM 인자로 받지 않는다):
    동·호수는 LLM에 나가기 전에 마스킹되므로(규칙 2) 모델은 `<PII:UNIT:1>`만 본다.
    동은 문자열 그대로 둔다 — `buildings.name`이 "402"·"402동" 어느 쪽일 수 있다.
    """
    match = _UNIT_PATTERN.search(query)
    if match is None:
        return None
    dong = match.group("dong") or match.group("dong_alt")
    ho = match.group("ho") or match.group("ho_alt")
    return dong, int(ho)


@dataclass(frozen=True)
class ParsedSpec:
    """파서(또는 LLM 보조) 추출 결과 — elements·rooms 둘 다 비면 위치를 특정 못 한 것."""

    elements: tuple[str, ...] = ()
    rooms: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.elements and not self.rooms


def parse_query(query: str) -> ParsedSpec:
    """자연어 질의 → {elements, rooms}. 사전 미등록 표현이면 둘 다 빈 스펙(LLM 보조 트리거)."""
    text = query.lower()

    elements: list[str] = [
        name for name, syns in ELEMENT_SYNONYMS.items() if any(s in text for s in syns)
    ]
    if not elements:
        for word, group in ELEMENT_GROUPS.items():
            if word in text:
                elements.extend(n for n in group if n not in elements)

    rooms: list[str] = []
    room_hits: list[str] = []
    for name, syns in ROOM_SYNONYMS.items():
        hit = [s for s in syns if s in text]
        if hit:
            rooms.append(name)
            room_hits.extend(hit)
    # 묶음 단어("방")가 이미 매칭된 동의어(예: "큰방")에 포함돼 걸린 것이면 중복 확장 skip.
    for word, group in ROOM_GROUPS.items():
        if word not in text or any(word in h for h in room_hits):
            continue
        rooms.extend(n for n in group if n not in rooms)

    return ParsedSpec(elements=tuple(elements), rooms=tuple(rooms))
