"""다음 행동 제안 — tool_path 기반 **코드 규칙** (ADR-0025 §7).

LLM 호출을 추가하지 않는다. 방금 어떤 도구로 답했는지(`tool_path`)와 최종 상태만 보고
후보 문자열을 고른다. 지웠던 고정 추천 칩과 다른 점은 **맥락 의존**이라는 것 — 도구를 쓰지
않은 질의에는 폴백 1개만 나가거나 아무것도 안 나간다.

문구는 프론트가 그대로 칩에 쓴다(H18-3). 딥링크·행동 배선은 프론트 몫이라 여기서는
사람이 읽는 라벨만 확정한다.
"""

from __future__ import annotations

from collections.abc import Sequence

# 도구 → 그 도구를 쓴 뒤 자연스러운 다음 행동. 여러 도구가 같은 문구로 모이면 중복 제거된다
# (증상 추적·유사 민원은 둘 다 "접수"로 이어진다).
TOOL_SUGGESTIONS: dict[str, str] = {
    "search_similar_inquiries": "민원 접수하기",
    "trace_home_device_issue": "민원 접수하기",
    "get_my_inquiries": "내 민원 진행 상황 보기",
    "get_fees": "지난달과 비교하기",
    "find_nearest_available_parking": "주차맵에서 보기",
    "find_in_floor_plan": "평면도에서 위치 보기",
    "search_documents": "원문 문서 열어보기",
    "get_facilities": "시설 현황 보기",
    "get_overdue_checks": "점검 일정 확인하기",
}

FALLBACK_SUGGESTION = "관리사무소에 문의하기"
# 칩 3개면 375px 한 줄이 찬다(H18-3) — 그 이상은 화면에 못 들어간다.
MAX_SUGGESTIONS = 3

ANSWERED_STATUS = "answered"


def suggest_next_actions(tool_path: Sequence[str], *, status: str) -> tuple[str, ...]:
    """다음 행동 후보 최대 3개(중복 제거·호출 순서 유지).

    답을 못 준 경우(폴백·되묻기)에는 담당자 연결이 최우선 행동이라 맨 앞에 둔다(규칙 1).
    """
    candidates: list[str] = []
    if status != ANSWERED_STATUS:
        candidates.append(FALLBACK_SUGGESTION)
    candidates.extend(
        suggestion for name in tool_path if (suggestion := TOOL_SUGGESTIONS.get(name)) is not None
    )
    return tuple(dict.fromkeys(candidates))[:MAX_SUGGESTIONS]
