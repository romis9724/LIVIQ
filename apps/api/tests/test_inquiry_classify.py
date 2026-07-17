"""inquiry_classify 단위 — 우선순위·카테고리 제안(순수 함수, DB 불필요)."""

from __future__ import annotations

import uuid

from app.inquiry_classify import classify_inquiry


def test_urgent_keyword_yields_urgent() -> None:
    result = classify_inquiry("천장 누수", "물이 새고 있습니다", [])
    assert result.priority == "urgent"


def test_normal_keyword_yields_normal() -> None:
    result = classify_inquiry("주차 문제", "이중주차로 불편합니다", [])
    assert result.priority == "normal"


def test_no_keyword_yields_low() -> None:
    result = classify_inquiry("문의", "궁금한 점이 있어요", [])
    assert result.priority == "low"


def test_urgent_takes_precedence_over_normal() -> None:
    result = classify_inquiry("주차장 화재", "주차장에서 불이 났습니다", [])
    assert result.priority == "urgent"


def test_suggests_first_matching_category() -> None:
    first = uuid.uuid4()
    second = uuid.uuid4()
    # 텍스트가 두 이름 모두 포함 → 순서상 첫 매치를 제안.
    categories = [(first, "신고"), (second, "누수")]
    result = classify_inquiry("누수 신고", "천장에서 물", categories)
    assert result.suggested_category_id == first


def test_category_match_by_name_in_body() -> None:
    plumbing = uuid.uuid4()
    result = classify_inquiry("신고", "누수가 발생", [(plumbing, "누수")])
    assert result.suggested_category_id == plumbing


def test_no_category_match_returns_none() -> None:
    result = classify_inquiry("문의", "일반 질문", [(uuid.uuid4(), "주차")])
    assert result.suggested_category_id is None
