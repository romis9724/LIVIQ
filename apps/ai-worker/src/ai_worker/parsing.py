"""업로드 원본 → 정규화 텍스트 (docs/01 §5.1, 11 §3.1).

# ponytail: H1은 텍스트·마크다운·PDF(pypdf)만. HWP·이미지 OCR·opendataloader-pdf
# (docs/01 §5.1 지정 파서)는 파일럿 문서 유형 확정 후 이 인터페이스 뒤로 교체/추가.
"""

from __future__ import annotations

import io
import re
from pathlib import PurePosixPath

_TEXT_SUFFIXES = {".txt", ".md", ".markdown"}
_PDF_SUFFIX = ".pdf"

# 연속 공백·빈 줄 정리(청킹 품질·토큰 절약)
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)


class UnsupportedFormatError(Exception):
    """지원하지 않는 파일 형식 — 문서 index_status=failed로 기록."""


def extract_text(storage_key: str, data: bytes) -> str:
    """원본 바이트 → 정규화 텍스트. 형식은 확장자로 판별."""
    suffix = PurePosixPath(storage_key).suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        text = data.decode("utf-8", errors="replace")
    elif suffix == _PDF_SUFFIX:
        text = _extract_pdf(data)
    else:
        raise UnsupportedFormatError(f"지원하지 않는 형식: {suffix or '(확장자 없음)'}")
    return normalize(text)


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n\n".join(pages)


def normalize(text: str) -> str:
    """클린징: 트레일링 공백 제거·과다 빈 줄 축소·양끝 정리."""
    text = _TRAILING_WS_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    return text.strip()
