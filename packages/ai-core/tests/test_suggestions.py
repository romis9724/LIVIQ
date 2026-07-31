"""다음 행동 제안 규칙 테스트 (ADR-0025 §7) — LLM 호출 없는 순수 함수."""

from __future__ import annotations

from ai_core.suggestions import (
    FALLBACK_SUGGESTION,
    MAX_SUGGESTIONS,
    TOOL_SUGGESTIONS,
    suggest_next_actions,
)


def test_maps_tool_to_its_next_action() -> None:
    assert suggest_next_actions(["get_fees"], status="answered") == ("지난달과 비교하기",)
    assert suggest_next_actions(["find_nearest_available_parking"], status="answered") == (
        "주차맵에서 보기",
    )
    assert suggest_next_actions(["search_similar_inquiries"], status="answered") == (
        "민원 접수하기",
    )


def test_keeps_tool_call_order() -> None:
    assert suggest_next_actions(["get_fees", "search_documents"], status="answered") == (
        "지난달과 비교하기",
        "원문 문서 열어보기",
    )


def test_deduplicates_tools_that_share_one_action() -> None:
    """증상 추적·유사 민원은 둘 다 '민원 접수하기'로 이어진다 — 칩이 두 번 뜨면 안 된다."""
    suggestions = suggest_next_actions(
        ["trace_home_device_issue", "search_similar_inquiries"], status="answered"
    )
    assert suggestions == ("민원 접수하기",)


def test_caps_at_max_suggestions() -> None:
    path = ["get_fees", "search_documents", "find_in_floor_plan", "get_my_inquiries"]
    suggestions = suggest_next_actions(path, status="answered")
    assert len(suggestions) == MAX_SUGGESTIONS
    assert suggestions[0] == "지난달과 비교하기"  # 잘리는 쪽은 뒤


def test_no_tool_answered_gives_nothing() -> None:
    """도구를 안 쓴 답변에는 맥락이 없다 — 고정 칩을 되살리지 않는다."""
    assert suggest_next_actions([], status="answered") == ()


def test_no_tool_fallback_gives_only_the_desk_contact() -> None:
    assert suggest_next_actions([], status="fallback") == (FALLBACK_SUGGESTION,)


def test_fallback_puts_desk_contact_first() -> None:
    suggestions = suggest_next_actions(["get_fees"], status="fallback")
    assert suggestions == (FALLBACK_SUGGESTION, "지난달과 비교하기")


def test_unknown_tool_is_ignored() -> None:
    """매핑 없는 도구는 조용히 건너뛴다 — 도구가 늘 때마다 예외가 나면 안 된다."""
    assert "그런_도구_없음" not in TOOL_SUGGESTIONS
    assert suggest_next_actions(["그런_도구_없음"], status="answered") == ()
