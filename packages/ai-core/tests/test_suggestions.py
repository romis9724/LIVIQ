"""다음 행동 제안 규칙 테스트 (ADR-0025 §7) — LLM 호출 없는 순수 함수."""

from __future__ import annotations

from ai_core.suggestions import (
    FALLBACK_SUGGESTION,
    TOOL_SUGGESTIONS,
    suggest_next_actions,
)

# 칩 문구는 그대로 새 질문이 된다 — 이동·행동 문구가 매핑에 다시 들어오면 이 테스트가 막는다.
NAVIGATION_LABELS = frozenset(
    {
        "원문 문서 열어보기",
        "주차맵에서 보기",
        "평면도에서 위치 보기",
        "시설 현황 보기",
        "내 민원 진행 상황 보기",
        "민원 접수하기",
    }
)


def test_maps_tool_to_its_next_question() -> None:
    assert suggest_next_actions(["get_fees"], status="answered") == ("지난달과 비교하기",)


def test_navigation_labels_are_never_suggested() -> None:
    """이동·행동 문구를 질문으로 보내면 근거가 없어 폴백만 난다(2026-08-01 사용자 실측)."""
    assert not NAVIGATION_LABELS & set(TOOL_SUGGESTIONS.values())


def test_navigation_only_tools_give_nothing() -> None:
    """이동·행동이 다음 단계인 도구들은 칩을 만들지 않는다 — 그 자리는 CTA 링크 몫이다."""
    path = [
        "search_documents",
        "find_nearest_available_parking",
        "find_in_floor_plan",
        "get_facilities",
        "get_my_inquiries",
        "search_similar_inquiries",
        "trace_home_device_issue",
        "get_recent_notices",
        "get_overdue_checks",
    ]
    assert suggest_next_actions(path, status="answered") == ()


def test_keeps_tool_call_order() -> None:
    """매핑 없는 도구는 건너뛰고 남은 것만 호출 순서대로."""
    assert suggest_next_actions(["search_documents", "get_fees"], status="answered") == (
        "지난달과 비교하기",
    )


def test_deduplicates_repeated_calls() -> None:
    """같은 도구를 두 번 부른 경로에도 칩은 하나만 나간다."""
    assert suggest_next_actions(["get_fees", "get_fees"], status="answered") == (
        "지난달과 비교하기",
    )


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
