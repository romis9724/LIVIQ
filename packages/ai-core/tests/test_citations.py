import uuid

from ai_core.citations import verify_citations
from ai_core.rag.retrieval import RetrievedChunk


def _chunk(content: str = "지하주차장은 24시간 개방한다.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="관리규약",
        content=content,
        heading="제3조",
        page=2,
        clause="제3조",
        score=0.8,
    )


def test_valid_citation_maps_to_chunk() -> None:
    chunks = [_chunk(), _chunk("주차 등록은 관리사무소에서 한다.")]
    answer = "주차장은 24시간 개방합니다 [1]. 등록은 사무소에서 합니다 [2]."
    check = verify_citations(answer, chunks)
    assert check.is_valid
    assert [c.ref for c in check.citations] == [1, 2]
    assert check.citations[0].chunk_id == chunks[0].chunk_id
    assert check.citations[0].quote.startswith("지하주차장")


def test_out_of_range_ref_is_invalid() -> None:
    check = verify_citations("규정에 따릅니다 [3].", [_chunk()])
    assert check.invalid_refs == (3,)
    assert not check.is_valid


def test_no_citation_is_invalid() -> None:
    check = verify_citations("그냥 답변입니다.", [_chunk()])
    assert check.citations == ()
    assert not check.is_valid


def test_duplicate_refs_deduplicated() -> None:
    check = verify_citations("개방합니다 [1]. 24시간입니다 [1].", [_chunk()])
    assert [c.ref for c in check.citations] == [1]
