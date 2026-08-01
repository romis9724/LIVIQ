"""다음 행동 제안 규칙 테스트 (ADR-0025 §7) — LLM 호출 없는 순수 함수."""

from __future__ import annotations

from unittest.mock import patch

from ai_core.suggestions import (
    FALLBACK_SUGGESTION,
    TOOL_SUGGESTIONS,
    suggest_next_actions,
)


def _from(path: list[str], mapping: dict[str, str], *, status: str = "answered") -> tuple[str, ...]:
    """매핑을 갈아끼고 규칙을 검증한다 — 매핑이 빈 지금도 순서·중복 규칙은 살아 있어야 한다."""
    with patch.dict(TOOL_SUGGESTIONS, mapping, clear=True):
        return suggest_next_actions(path, status=status)


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


def test_tool_map_is_empty_for_now() -> None:
    """맥락을 못 읽는 고정 문구를 전부 뺐다 — 매핑이 비어도 계약(빈 튜플)은 살아 있다.

    마지막으로 뺀 것은 get_fees "지난달과 비교하기"다: "6,7월 평균"을 물어 답을 받은
    화면에 또 비교를 권했다(2026-08-01 사용자 실측).
    """
    assert TOOL_SUGGESTIONS == {}
    assert suggest_next_actions(["get_fees"], status="answered") == ()


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
    """매핑 없는 도구는 건너뛰고 남은 것만 호출 순서대로(매핑이 다시 찰 때를 위한 계약)."""
    mapping = {"tool_b": "질문 B", "tool_c": "질문 C"}
    assert _from(["tool_a", "tool_c", "tool_b"], mapping) == ("질문 C", "질문 B")


def test_deduplicates_repeated_calls() -> None:
    """같은 도구를 두 번 부른 경로에도 칩은 하나만 나간다."""
    assert _from(["tool_b", "tool_b"], {"tool_b": "질문 B"}) == ("질문 B",)


def test_no_tool_answered_gives_nothing() -> None:
    """도구를 안 쓴 답변에는 맥락이 없다 — 고정 칩을 되살리지 않는다."""
    assert suggest_next_actions([], status="answered") == ()


def test_no_tool_fallback_gives_only_the_desk_contact() -> None:
    assert suggest_next_actions([], status="fallback") == (FALLBACK_SUGGESTION,)


def test_fallback_puts_desk_contact_first() -> None:
    assert _from(["tool_b"], {"tool_b": "질문 B"}, status="fallback") == (
        FALLBACK_SUGGESTION,
        "질문 B",
    )


def test_unknown_tool_is_ignored() -> None:
    """매핑 없는 도구는 조용히 건너뛴다 — 도구가 늘 때마다 예외가 나면 안 된다."""
    assert "그런_도구_없음" not in TOOL_SUGGESTIONS
    assert suggest_next_actions(["그런_도구_없음"], status="answered") == ()
