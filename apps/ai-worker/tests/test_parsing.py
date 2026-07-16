import pytest

from ai_worker.parsing import UnsupportedFormatError, extract_text, normalize


def test_txt_and_md_decode_utf8() -> None:
    assert extract_text("t/규약.txt", "관리 규약".encode()) == "관리 규약"
    assert extract_text("t/공지.md", b"# notice") == "# notice"


def test_pdf_extracts_page_text() -> None:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    # 빈 페이지 PDF → 텍스트 없음(파싱 자체는 성공)
    assert extract_text("t/문서.pdf", buf.getvalue()) == ""


def test_unsupported_format_raises() -> None:
    with pytest.raises(UnsupportedFormatError):
        extract_text("t/명부.hwp", b"...")


def test_normalize_collapses_blank_lines_and_trailing_ws() -> None:
    raw = "제1조  \n\n\n\n내용   \n"
    assert normalize(raw) == "제1조\n\n내용"
