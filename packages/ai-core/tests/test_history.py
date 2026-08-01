"""히스토리 관련성 선별 테스트 (ADR-0027 결정 2) — LLM·임베딩 호출 없는 순수 함수."""

from __future__ import annotations

from ai_core.history import (
    HISTORY_CANDIDATE_TURNS,
    HISTORY_INJECT_TURNS,
    select_relevant_messages,
)

# 주차 대화 2턴 + 관리비 대화 1턴 — 관리비를 다시 물으면 주차 턴은 실리지 않아야 한다.
MIXED_HISTORY = (
    ("user", "지하주차장 방문차량 등록은 어떻게 해?"),
    ("assistant", "방문차량은 앱에서 등록하시면 됩니다."),
    ("user", "주차 자리 남았어?"),
    ("assistant", "B2에 12면 비어 있습니다."),
    ("user", "지난달 관리비 얼마 나왔어?"),
    ("assistant", "지난달 관리비는 18만 원입니다."),
)


def test_selects_related_turn_over_unrelated_one() -> None:
    # Arrange: 마지막 턴은 무관한 잡담이라 관련 턴은 점수로만 뽑혀야 한다.
    history = (*MIXED_HISTORY, ("user", "고마워"), ("assistant", "도움이 되었길 바랍니다."))

    # Act
    selected = select_relevant_messages("관리비 왜 이렇게 많이 나왔어?", history)

    # Assert: 관리비 턴은 포함, 주차 턴은 배제.
    texts = [text for _role, text in selected]
    assert "지난달 관리비는 18만 원입니다." in texts
    assert "B2에 12면 비어 있습니다." not in texts
    assert "방문차량은 앱에서 등록하시면 됩니다." not in texts


def test_last_turn_is_always_included() -> None:
    """지시대명사("그거 언제야?")는 직전 턴이 없으면 해소되지 않는다 — 점수 무관 포함."""
    selected = select_relevant_messages("그거 언제야?", MIXED_HISTORY)

    assert selected[-2:] == MIXED_HISTORY[-2:]


def test_injection_is_capped_even_when_every_turn_is_related() -> None:
    """후보가 10턴 전부 관련이어도 주입은 3턴 — 넓힌 것은 후보뿐이다(토큰=비용)."""
    history = tuple(
        item
        for i in range(HISTORY_CANDIDATE_TURNS)
        for item in (("user", f"관리비 {i}월분 알려줘"), ("assistant", f"관리비 {i}월분입니다."))
    )

    selected = select_relevant_messages("관리비 알려줘", history)

    assert len(selected) == HISTORY_INJECT_TURNS * 2


def test_selection_keeps_chronological_order() -> None:
    """선별이 순서를 뒤섞지 않는다 — 대화는 시간순이어야 모델이 읽는다."""
    selected = select_relevant_messages("주차 자리 지금도 남았어?", MIXED_HISTORY)

    assert list(selected) == [m for m in MIXED_HISTORY if m in selected]


def test_empty_history_returns_empty() -> None:
    assert select_relevant_messages("관리비 얼마야?", ()) == ()


def test_blank_bodies_are_dropped_entirely() -> None:
    """본문이 빈 메시지만 있으면 실을 턴이 없다(폴백 메시지 등)."""
    assert select_relevant_messages("관리비 얼마야?", (("user", "  "), ("assistant", ""))) == ()


def test_one_character_turn_scores_zero_without_crashing() -> None:
    """bigram을 만들 수 없는 짧은 발화("넵")는 점수 0 — 마지막 턴이 아니면 탈락한다."""
    history = (("user", "넵"), ("user", "관리비 얼마야?"), ("assistant", "18만 원입니다."))

    selected = select_relevant_messages("관리비 왜 올랐어?", history)

    assert ("user", "넵") not in selected


def test_consecutive_user_messages_do_not_break_pairing() -> None:
    """되묻기 뒤 재질문(user 연속)도 각각 한 턴 — 답변이 엉뚱한 질문에 붙지 않는다."""
    history = (
        ("user", "관리비 얼마야?"),
        ("assistant", "어느 기간을 말씀하시나요?"),
        ("user", "지난달"),
        ("user", "지난달 관리비 알려줘"),
        ("assistant", "지난달 관리비는 18만 원입니다."),
    )

    selected = select_relevant_messages("그럼 이번 달은?", history)

    assert selected[-2:] == history[-2:]  # 마지막 턴(user+assistant)이 통째로 붙는다


def test_leading_assistant_message_forms_its_own_turn() -> None:
    """복원 상한에 질문이 잘려 assistant로 시작해도 버리지 않는다(방어적)."""
    history = (
        ("assistant", "지난달 관리비는 18만 원입니다."),
        ("user", "주차 자리 남았어?"),
        ("assistant", "B2에 12면 비어 있습니다."),
    )

    selected = select_relevant_messages("관리비 왜 올랐어?", history)

    assert ("assistant", "지난달 관리비는 18만 원입니다.") in selected


def test_unrelated_turn_is_dropped_even_below_the_cap() -> None:
    """상한에 여유가 있어도 점수 0인 턴은 싣지 않는다 — 무관 턴이 도구 결정을 오염시킨다."""
    history = (
        ("user", "택배함 비밀번호 뭐야?"),
        ("assistant", "동별 택배함 비밀번호는 관리사무소에서 확인하세요."),
        ("user", "ㅇㅋ"),
        ("assistant", "네."),
    )

    selected = select_relevant_messages("엘리베이터 점검 언제야?", history)

    assert selected == history[-2:]
