"""다음 행동 제안 — tool_path 기반 **코드 규칙** (ADR-0025 §7).

LLM 호출을 추가하지 않는다. 방금 어떤 도구로 답했는지(`tool_path`)와 최종 상태만 보고
후보 문자열을 고른다. 지웠던 고정 추천 칩과 다른 점은 **맥락 의존**이라는 것 — 도구를 쓰지
않은 질의에는 폴백 1개만 나가거나 아무것도 안 나간다.

문구는 프론트가 그대로 **새 질문으로 전송한다**(H18-3). 그래서 여기 담을 수 있는 것은
**질문형뿐**이다 — 이동·행동 문구를 담았더니 "원문 문서 열어보기"가 사용자 말풍선으로
전송되고 AI 가 근거를 못 찾아 폴백했다(2026-08-01 사용자 실측). 화면 이동은 칩이 아니라
CTA 링크가, 행동은 폼이 한다. 잘못된 칩은 없느니만 못하므로 빈 칸을 억지로 채우지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

# 도구 → 그 도구로 답한 뒤 **그대로 물어도 말이 되는** 질문. 이동·행동 문구는 넣지 않는다.
#
# 지금 남은 것은 하나다. 뺀 것과 이유:
#   - search_documents "원문 문서 열어보기" · find_in_floor_plan · get_facilities
#     · get_my_inquiries → 화면 이동. 질문으로 보내면 AI 가 답할 근거가 없다.
#   - search_similar_inquiries · trace_home_device_issue "민원 접수하기" ·
#     find_nearest_available_parking "주차맵에서 보기" → 이미 CTA 버튼이 있는 행동.
#   - get_overdue_checks "점검 일정 확인하기" → 방금 준 답을 다시 묻는 제자리 질문.
#   - get_recent_notices → 목록 다음의 자연스러운 질문("그 공지 자세히")은 어느 공지인지에
#     달려 있는데 칩은 고정 문구다. 특정 공지를 못박으면 다른 답변에서 헛돈다.
TOOL_SUGGESTIONS: dict[str, str] = {
    # get_fees 는 전월 대비를 실제로 조회한다 — 칩을 눌러 다시 물으면 답이 나온다.
    "get_fees": "지난달과 비교하기",
}

FALLBACK_SUGGESTION = "관리사무소에 문의하기"
# 칩 3개면 375px 한 줄이 찬다(H18-3) — 그 이상은 화면에 못 들어간다. 매핑이 하나뿐인
# 지금은 최대 2개(폴백+관리비)라 잘릴 일이 없지만, 매핑이 늘 때 화면부터 깨지지 않도록 남긴다.
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
