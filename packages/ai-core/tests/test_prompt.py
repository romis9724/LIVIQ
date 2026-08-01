"""결정 turn 프롬프트의 오늘 날짜 주입 — 연도 없는 시점 표현("이번 달"·"8월") 해석 근거.

모델은 오늘을 모른다(학습 컷오프) — 날짜가 없으면 "8월 관리비"를 엉뚱한 연도의
YYYY-MM으로 옮겨 존재하지 않는 월을 조회하고 폴백으로 샌다(2026-08-01 실측,
get_fees 4회 공회전 → no_evidence).
"""

import datetime

from ai_core.rag.prompt import AGENT_SYSTEM_PROMPT, agent_system_prompt


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


def test_agent_system_prompt_is_stable_within_a_day() -> None:
    # Arrange · Act — 같은 날짜면 문자열이 동일해야 프리픽스 캐시가 하루 단위로만 갈린다
    a = agent_system_prompt(datetime.date(2026, 8, 1))
    b = agent_system_prompt(datetime.date(2026, 8, 1))

    # Assert
    assert a == b
