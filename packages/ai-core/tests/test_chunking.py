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


def test_bracketed_and_english_article_markers_start_new_sections() -> None:
    text = (
        "[제18조] 공사 시간\n세대 공사는 평일 09시부터.\n\n"
        "Article 9 Quiet Hours\nQuiet hours run from 22:00."
    )
    chunks = chunk_text(text)
    assert len(chunks) == 2
    assert chunks[0].heading == "제18조 공사 시간"
    assert chunks[1].heading == "Article 9 Quiet Hours"


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


def test_pdf_single_line_document_respects_token_limit() -> None:
    """PDF 추출문(개행 없는 장문 한 줄)에서도 청크가 상한을 지켜야 한다.

    실측 결함(H15-2 #3): 섹션 제목 정규식이 줄 끝까지 삼켜 제목이 900토큰까지 커지고,
    그 제목이 매 청크에 붙어 청크가 상한의 3배(평균 1,217/상한 400)가 됐다.
    """
    body = "이 조항은 관리 사항을 정한다." * 60  # 개행 없이 이어지는 한 줄
    text = f"제48조(주택관리업자 선정방법) {body}"
    chunks = chunk_text(text, max_tokens=400)

    assert chunks[0].heading == "제48조(주택관리업자 선정방법)"
    # 제목이 줄 전체를 삼키지 않는다 — 삼키면 아래 상한 검사가 무너진다.
    assert all(len(c.heading or "") < 60 for c in chunks)
    assert len(chunks) > 1  # 한 줄이라도 문장 경계로 쪼갠다
    assert max(c.token_count for c in chunks) <= 500  # 제목 오버헤드 포함 여유분


def test_toc_line_is_dropped_entirely() -> None:
    """점선 리더가 있는 줄은 목차다 — 리더만 지우면 목차 항목이 가짜 조항 섹션이 된다.

    첫마을 관리규약 실측: 목차 6줄이 조항 90개를 담고 있어 조항마다 중복 섹션이 생겼다.
    """
    text = "제24조(회의방청)" + "·" * 80 + "12\n\n회의는 공개한다."
    chunks = chunk_text(text)
    assert [c.content for c in chunks] == ["회의는 공개한다."]
    assert chunks[0].clause is None  # 목차의 조항 번호를 본문 근거로 쓰지 않는다


def test_ellipsis_is_not_treated_as_toc() -> None:
    """말줄임표를 목차로 오인하면 본문이 사라진다 — 마침표는 6개 이상만 리더로 본다."""
    chunks = chunk_text("제3조(정의) 용어의 뜻은... 다음과 같다.")
    assert chunks and "다음과 같다" in chunks[0].content


def test_midline_clause_headings_split_sections() -> None:
    """PDF 추출문은 조 사이에 개행이 없다 — 줄 중간 조항도 경계로 잡아야 한다.

    줄머리만 보면 우연히 줄머리에 걸린 조항이 뒤따르는 청크의 제목을 가로채, 제1조 내용이
    제64조로 인용된다(틀린 조항을 가리키므로 NULL보다 나쁘다 — H15-2 #3 실측).
    """
    text = (
        "제9조(입주자 등의 자격) 소유자의 자격은 취득 시점부터다."
        "제10조(권리) 입주자는 권리를 가진다."
    )
    chunks = chunk_text(text)
    clauses = [c.clause for c in chunks]
    assert clauses == ["제9조(입주자 등의 자격)", "제10조(권리)"]
    # 각 청크의 조항 라벨은 그 청크 본문에 실제로 존재해야 한다.
    for chunk in chunks:
        assert chunk.clause is not None and chunk.clause.split("(")[0] in chunk.content


def test_legal_reference_is_not_a_clause_heading() -> None:
    """`법 제18조제2항` 같은 참조는 조항 제목이 아니다 — 섹션을 만들면 근거가 흐려진다."""
    text = (
        "제1조(목적) 이 규약은 「공동주택관리법」제18조제2항 및 "
        "같은 법 시행령 제19조에 따라 정한다."
    )
    chunks = chunk_text(text)
    assert [c.clause for c in chunks] == ["제1조(목적)"]


def test_sentence_boundary_without_space_after_period() -> None:
    """PDF는 마침표 뒤 공백을 잃는다(`적용한다.2.`) — 그래도 문장 경계로 쪼갠다."""
    # 마침표 바로 뒤에 다음 문장이 붙는다(공백 없음) — 실측된 PDF 추출 형태.
    text = "".join(f"제{i}항은 다음과 같이 적용한다." for i in range(1, 40))
    assert ". " not in text
    chunks = chunk_text(text, max_tokens=100)
    assert len(chunks) > 1
    assert max(c.token_count for c in chunks) <= 150


def test_clause_is_derived_from_article_heading() -> None:
    """조항 제목은 clause로 승격 — 인용 출처 줄에 조항 번호를 붙이기 위한 값이다."""
    text = "제48조(주택관리업자 선정방법)\n입주자대표회의는 주택관리업자를 선정한다."
    chunks = chunk_text(text)
    assert chunks[0].clause == "제48조(주택관리업자 선정방법)"


def test_non_article_heading_has_no_clause() -> None:
    """마크다운·일반 제목은 조항이 아니다 — 조항인 척하면 인용 근거가 흐려진다."""
    chunks = chunk_text("## 주차 규정\n\n방문 차량은 등록해야 합니다.")
    assert chunks[0].heading == "주차 규정"
    assert chunks[0].clause is None


def test_english_article_heading_is_clause() -> None:
    chunks = chunk_text("Article 9 Quiet Hours\nQuiet hours run from 22:00.")
    assert chunks[0].clause == "Article 9 Quiet Hours"
