"""결정 turn 프롬프트의 오늘 날짜 주입 — 연도 없는 시점 표현("이번 달"·"8월") 해석 근거.

모델은 오늘을 모른다(학습 컷오프) — 날짜가 없으면 "8월 관리비"를 엉뚱한 연도의
YYYY-MM으로 옮겨 존재하지 않는 월을 조회하고 폴백으로 샌다(2026-08-01 실측,
get_fees 4회 공회전 → no_evidence).
"""

import datetime

import pytest

from ai_core.rag.prompt import (
    ADMIN_ANSWER_SYSTEM_PROMPT,
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


@pytest.mark.parametrize("base", [ANSWER_SYSTEM_PROMPT, FACILITY_ANSWER_SYSTEM_PROMPT])
def test_answer_prompt_treats_confirmed_absence_as_an_answer(base: str) -> None:
    """도구가 '없음'을 확정하면 그것이 답이다 — R36 도피 처방(0210·0211·CL-N2).

    발동 조건이 [확정 데이터·도구 결과]로 한정돼야 한다. 조건 없이 "없으면 없다고 답하라"가
    되면 문서 검색이 빈손일 때의 정당한 NO_EVIDENCE(규칙 1)까지 흔든다.
    """
    # Assert
    assert "NO_EVIDENCE로 처리하지 마십시오" in base
    assert "[확정 데이터·도구 결과]가" in base


@pytest.mark.parametrize("base", [ANSWER_SYSTEM_PROMPT, FACILITY_ANSWER_SYSTEM_PROMPT])
def test_quote_first_prompt_keeps_confirmed_absence_rule(base: str) -> None:
    """인용 선행 변형(R36-B)에서도 확정된 '없음' 단서가 살아 있어야 한다."""
    # Act
    variant = quote_first_prompt(base)

    # Assert
    assert "NO_EVIDENCE로 처리하지 마십시오" in variant


def test_admin_answer_prompt_extends_the_general_one_with_home_device_guidance() -> None:
    """관리자 변형(H20-16) — 기존 규칙 1~6은 그대로 두고 세대 내부 위치 규칙만 덧붙인다."""
    # Assert — 기존 프롬프트가 접두라 프리픽스 캐시·기존 규칙이 보존된다
    assert ADMIN_ANSWER_SYSTEM_PROMPT.startswith(ANSWER_SYSTEM_PROMPT)
    assert "트윈 대시보드" in ADMIN_ANSWER_SYSTEM_PROMPT
    assert "동·호수" in ADMIN_ANSWER_SYSTEM_PROMPT
    # 입주민 프롬프트는 오염되지 않는다 — 본인 세대 도구가 있어 이 안내가 틀린 답이 된다
    assert "트윈 대시보드" not in ANSWER_SYSTEM_PROMPT


def test_quote_first_prompt_handles_admin_variant() -> None:
    """규칙 0 삽입은 헤더 기준이라 규칙이 하나 늘어난 관리자 변형에서도 같게 동작한다."""
    # Act
    variant = quote_first_prompt(ADMIN_ANSWER_SYSTEM_PROMPT)

    # Assert
    header, rule_zero, rest = variant.split("\n", 2)
    assert header == ADMIN_ANSWER_SYSTEM_PROMPT.split("\n", 1)[0]
    assert rule_zero == QUOTE_FIRST_RULE
    assert "트윈 대시보드" in rest


def test_agent_system_prompt_is_stable_within_a_day() -> None:
    # Arrange · Act — 같은 날짜면 문자열이 동일해야 프리픽스 캐시가 하루 단위로만 갈린다
    a = agent_system_prompt(datetime.date(2026, 8, 1))
    b = agent_system_prompt(datetime.date(2026, 8, 1))

    # Assert
    assert a == b
