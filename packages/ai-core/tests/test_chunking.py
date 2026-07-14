from ai_core.rag import Chunk, chunk_text


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("") == []


def test_short_text_is_single_chunk() -> None:
    chunks = chunk_text("지하주차장은 24시간 개방합니다.")
    assert len(chunks) == 1
    assert chunks[0].index == 0
    assert chunks[0].heading is None


def test_article_markers_start_new_sections() -> None:
    text = "제1조 목적\n이 규약은 관리 사항을 정한다.\n\n제2조 정의\n용어의 뜻은 다음과 같다."
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert chunks[0].heading == "제1조 목적"
    assert chunks[1].heading == "제2조 정의"
    assert "제2조" in chunks[1].content


def test_markdown_heading_is_section_boundary() -> None:
    text = "## 주차 규정\n\n방문 차량은 등록해야 합니다.\n\n## 소음 규정\n\n야간 공사는 금지됩니다."
    chunks = chunk_text(text)
    assert [c.heading for c in chunks] == ["주차 규정", "소음 규정"]


def test_paragraphs_merge_within_token_budget() -> None:
    text = "첫 문단입니다.\n\n둘째 문단입니다.\n\n셋째 문단입니다."
    chunks = chunk_text(text, max_tokens=1000)
    assert len(chunks) == 1


def test_paragraphs_split_when_budget_exceeded() -> None:
    paragraph = "관리 규정 내용입니다. " * 30  # 문단당 상당량
    text = f"{paragraph}\n\n{paragraph}"
    chunks = chunk_text(text, max_tokens=200)
    assert len(chunks) >= 2
    assert all(isinstance(c, Chunk) for c in chunks)


def test_oversized_single_paragraph_splits_by_sentence() -> None:
    paragraph = " ".join(f"이것은 {i}번째 문장입니다." for i in range(60))
    chunks = chunk_text(paragraph, max_tokens=150)
    assert len(chunks) >= 2
    assert all(c.token_count <= 200 for c in chunks)  # 문장 경계 여유 포함 상한 부근


def test_indices_are_sequential() -> None:
    text = "제1조 가\n내용1\n\n제2조 나\n내용2\n\n제3조 다\n내용3"
    chunks = chunk_text(text)
    assert [c.index for c in chunks] == list(range(len(chunks)))
