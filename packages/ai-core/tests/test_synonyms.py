"""생활어 사전 단위 테스트 (H20-7) — 확장·비확장·오탐 방지."""

from __future__ import annotations

from ai_core.synonyms import expand_query

DUMMY_QUERY = "두꺼비집이 어디에 있지?"


def test_expand_query_appends_standard_term_for_colloquial_word() -> None:
    expanded = expand_query(DUMMY_QUERY)

    assert expanded.startswith(DUMMY_QUERY)  # 원문 보존
    assert "분전함" in expanded


def test_expand_query_returns_original_when_no_colloquial_word() -> None:
    assert expand_query("이번 달 관리비가 왜 올랐나요") == "이번 달 관리비가 왜 올랐나요"


def test_expand_query_skips_standard_term_already_in_text() -> None:
    """이미 표준어가 있으면 넓힐 이유가 없다 — 토큰만 늘어난다."""
    query = "분전함(두꺼비집) 점검 주기"

    assert expand_query(query) == query


def test_expand_query_appends_each_standard_term_once() -> None:
    expanded = expand_query("엘리베이터랑 물탱크 점검이 언제인가요")

    assert expanded.endswith("(승강기 저수조)")


def test_expand_query_does_not_match_inside_other_word() -> None:
    """'전구역'은 '전구'가 아니다 — 코퍼스 실측 오탐(전구역·전구간)이라 사전에서 뺐다."""
    query = "지하 전구역 소등 시간"

    assert expand_query(query) == query


def test_expand_query_passes_through_empty_text() -> None:
    assert expand_query("") == ""
