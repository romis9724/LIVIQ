from ai_core.budget import ScoredChunk, budget_for_model, fit_chunks


def _chunk(id_: str, score: float, tokens: int, content: str | None = None) -> ScoredChunk:
    return ScoredChunk(id=id_, content=content or f"내용-{id_}", score=score, token_count=tokens)


def test_budget_for_model_applies_ratio() -> None:
    assert budget_for_model(8000, 0.5) == 4000
    assert budget_for_model(0) == 0


def test_fit_selects_by_score_within_budget() -> None:
    chunks = [_chunk("a", 0.9, 50), _chunk("b", 0.8, 60), _chunk("c", 0.7, 50)]
    selected = fit_chunks(chunks, budget_tokens=100)
    assert [c.id for c in selected] == ["a", "c"]  # b(60)는 예산 초과로 건너뜀


def test_fit_dedupes_near_identical_content() -> None:
    same = "지하주차장 이용 규정 제3조 내용 " * 5
    chunks = [
        ScoredChunk(id="a", content=same, score=0.9, token_count=10),
        ScoredChunk(id="b", content=same + " (사본)", score=0.8, token_count=10),
    ]
    selected = fit_chunks(chunks, budget_tokens=100)
    assert [c.id for c in selected] == ["a"]


def test_fit_is_deterministic_on_score_tie() -> None:
    chunks = [_chunk("b", 0.5, 10), _chunk("a", 0.5, 10)]
    assert [c.id for c in fit_chunks(chunks, budget_tokens=100)] == ["a", "b"]


def test_fit_empty_and_zero_budget() -> None:
    assert fit_chunks([], budget_tokens=100) == []
    assert fit_chunks([_chunk("a", 1.0, 1)], budget_tokens=0) == []


def test_tokens_falls_back_to_estimate() -> None:
    chunk = ScoredChunk(id="a", content="관리비 안내", score=1.0)
    assert chunk.tokens > 0
