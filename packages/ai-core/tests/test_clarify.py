"""되묻기 문장 생성 — 모델이 아니라 코드가 만든다 (H18-3 후속, ADR-0025 §4).

여기서 고정하는 것은 두 가지다: 항목별로 **무엇을 묻는 문장이 나오는가**(스냅샷)와,
모델이 인자를 엉터리로 채웠을 때 **되묻기가 아예 발생하지 않는가**(경계 검증).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_core.tools.clarify import _GENERIC_QUESTION as GENERIC
from ai_core.tools.clarify import (
    ClarificationArgs,
    ask_clarification_tool,
    build_clarification,
)


@pytest.mark.parametrize(
    ("missing", "context", "expected"),
    [
        # 흔한 항목 — 전용 문구(예시 포함).
        ("기간", "관리비", "관리비에 대해 어느 기간을 말씀하시나요? (예: 이번 달, 지난달)"),
        ("대상 설비", None, "어떤 설비를 말씀하시나요? (예: 승강기, 급수펌프)"),
        ("동/호수", None, "어느 동·호수를 말씀하시나요? (예: 401동 201호)"),
        ("차량", "주차 위치", "주차 위치에 대해 어떤 차량을 말씀하시나요? (예: 12가3456)"),
        # 모르는 항목 — 일반 템플릿 폴백. 받침에 따라 을/를이 갈린다.
        # 모르는 항목은 낱말을 문장에 넣지 않는다 — 모델이 항목 대신 주제어를 넣는
        # 실측 사례("온수")에서 "온수에 대해 온수를…"로 무너졌다.
        ("방문 목적", None, GENERIC),
        ("담당 부서", "민원 이관", f"민원 이관에 대해 {GENERIC}"),
        # 주제가 항목과 겹치면 붙이지 않는다(같은 말 반복 방지).
        ("온수", "온수", GENERIC),
        # 모델이 원 질문을 그대로 넣어도(H18-3 실패 사례) 문장은 코드 것이 나간다.
        ("그거 언제 하나요?", None, "어느 기간을 말씀하시나요? (예: 이번 달, 지난달)"),
    ],
)
def test_build_clarification_snapshots(missing: str, context: str | None, expected: str) -> None:
    assert build_clarification(missing, context) == expected


def test_build_clarification_ignores_blank_context() -> None:
    """공백뿐인 주제어는 '에 대해'만 남겨 문장을 망친다 — 없는 것으로 취급."""
    assert build_clarification("기간", "   ") == build_clarification("기간")


@pytest.mark.parametrize(
    "payload",
    [
        {},  # 항목 미지정
        {"missing": ""},  # 빈 값
        {"missing": "   "},  # 공백뿐(strip 후 빈 값)
        {"missing": "가" * 41},  # 항목이 아니라 문장을 밀어넣은 경우
    ],
)
def test_invalid_args_are_rejected_at_the_boundary(payload: dict[str, str]) -> None:
    """검증 실패는 곧 '되묻기 미발생' — 오케스트레이터가 None으로 흘려보낸다."""
    with pytest.raises(ValidationError):
        ClarificationArgs.model_validate(payload)


def test_context_is_optional_and_trimmed() -> None:
    args = ClarificationArgs.model_validate({"missing": " 기간 ", "context": " 관리비 "})
    assert (args.missing, args.context) == ("기간", "관리비")
    assert ClarificationArgs.model_validate({"missing": "기간"}).context is None


def test_tool_description_still_states_the_narrow_trigger() -> None:
    """라우팅 신호(발동 조건·비발동 조건)는 인자 스키마를 바꿔도 유지한다(H15-2 R22)."""
    description = ask_clarification_tool().description
    assert "정하지 못할 때만" in description
    assert "먼저 다른 도구로 찾아본다" in description
