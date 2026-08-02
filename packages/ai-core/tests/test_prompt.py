"""결정 turn 프롬프트의 오늘 날짜 주입 — 연도 없는 시점 표현("이번 달"·"8월") 해석 근거.

모델은 오늘을 모른다(학습 컷오프) — 날짜가 없으면 "8월 관리비"를 엉뚱한 연도의
YYYY-MM으로 옮겨 존재하지 않는 월을 조회하고 폴백으로 샌다(2026-08-01 실측,
get_fees 4회 공회전 → no_evidence).
"""

import datetime

import pytest

from ai_core.rag.prompt import (
    AGENT_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    FACILITY_ANSWER_SYSTEM_PROMPT,
    QUOTE_FIRST_RULE,
    agent_system_prompt,
    quote_first_prompt,
)


def test_agent_system_prompt_contains_today() -> None:
    # Arrange
    today = datetime.date(2026, 8, 1)

    # Act
    content = agent_system_prompt(today)

    # Assert — 날짜와 해석 지시가 함께 실린다
    assert "2026-08-01" in content
    assert "연도가 없는" in content


def test_agent_system_prompt_keeps_base_prompt() -> None:
    # Arrange
    today = datetime.date(2026, 8, 1)

    # Act
    content = agent_system_prompt(today)

    # Assert — 기존 결정 turn 지시(되묻기 조건 등)는 그대로 앞에 온다
    assert content.startswith(AGENT_SYSTEM_PROMPT)


@pytest.mark.parametrize("base", [ANSWER_SYSTEM_PROMPT, FACILITY_ANSWER_SYSTEM_PROMPT])
def test_quote_first_prompt_inserts_rule_zero_and_keeps_rules(base: str) -> None:
    """일반·시설 이력 프롬프트 모두 규칙 1 앞에 인용 선행 지시가 들어가고 본문은 보존된다."""
    # Act
    variant = quote_first_prompt(base)

    # Assert — 헤더("…규칙:") 다음 줄이 규칙 0, 기존 규칙은 그대로 뒤에 남는다
    header, rule_zero, rest = variant.split("\n", 2)
    assert header == base.split("\n", 1)[0]
    assert rule_zero == QUOTE_FIRST_RULE
    assert rest == base.split("\n", 1)[1]


def test_agent_system_prompt_is_stable_within_a_day() -> None:
    # Arrange · Act — 같은 날짜면 문자열이 동일해야 프리픽스 캐시가 하루 단위로만 갈린다
    a = agent_system_prompt(datetime.date(2026, 8, 1))
    b = agent_system_prompt(datetime.date(2026, 8, 1))

    # Assert
    assert a == b
