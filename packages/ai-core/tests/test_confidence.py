from ai_core.confidence import FALLBACK_THRESHOLD, REVIEW_THRESHOLD, assess


def test_high_retrieval_and_valid_citation_passes() -> None:
    verdict = assess(top_retrieval_score=0.9, citations_valid=True, invalid_citation_count=0)
    assert not verdict.should_fallback
    assert not verdict.needs_review
    assert verdict.score >= REVIEW_THRESHOLD


def test_invalid_citations_drop_confidence() -> None:
    good = assess(top_retrieval_score=0.9, citations_valid=True, invalid_citation_count=0)
    bad = assess(top_retrieval_score=0.9, citations_valid=False, invalid_citation_count=2)
    assert bad.score < good.score
    assert bad.should_fallback or bad.needs_review


def test_low_retrieval_triggers_fallback() -> None:
    verdict = assess(top_retrieval_score=0.1, citations_valid=False, invalid_citation_count=0)
    assert verdict.score < FALLBACK_THRESHOLD
    assert verdict.should_fallback


def test_score_clamped_to_unit_range() -> None:
    verdict = assess(top_retrieval_score=5.0, citations_valid=True, invalid_citation_count=0)
    assert 0.0 <= verdict.score <= 1.0
