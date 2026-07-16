"""구조 인지 청킹 — 조/항·제목·문단 경계 우선, 토큰 상한 내 병합 (docs/01 §5.1, 08 §3).

오버랩은 두지 않는다(중복=토큰 낭비). 경계 우선순위:
1) 조항 마커(제N조)·마크다운 제목 → 새 섹션(제목 메타 유지)
2) 빈 줄(문단) → 병합 단위
3) 상한 초과 장문 문단 → 문장 단위 분할
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_core.llm.tokens import estimate_tokens

# 청크 토큰 상한(bge-m3 입력·컨텍스트 예산 균형 — 파일럿 보정 대상)
CHUNK_MAX_TOKENS = 400

# 섹션 경계: 마크다운 제목 또는 조항 마커로 시작하는 줄
_SECTION_RE = re.compile(r"^(#{1,6}\s+.+|제\s?\d+\s?조[^\n]*)$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+")


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str
    heading: str | None
    token_count: int


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    """(제목, 본문) 섹션 목록. 첫 경계 이전 텍스트는 제목 None."""
    sections: list[tuple[str | None, str]] = []
    matches = list(_SECTION_RE.finditer(text))
    if not matches:
        return [(None, text)]
    if matches[0].start() > 0:
        sections.append((None, text[: matches[0].start()]))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading = m.group(0).lstrip("# ").strip()
        sections.append((heading, text[m.end() : end]))
    return sections


def _split_oversized(paragraph: str, max_tokens: int) -> list[str]:
    """상한 초과 문단을 문장 단위로 분할(그래도 초과하는 단일 문장은 그대로 통과)."""
    if estimate_tokens(paragraph) <= max_tokens:
        return [paragraph]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(paragraph):
        if not sentence.strip():
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and estimate_tokens(candidate) > max_tokens:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, *, max_tokens: int = CHUNK_MAX_TOKENS) -> list[Chunk]:
    """텍스트를 구조 경계 우선으로 청킹. 빈 입력은 빈 목록."""
    chunks: list[Chunk] = []
    for heading, body in _split_sections(text):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        pieces: list[str] = []
        for paragraph in paragraphs:
            pieces.extend(_split_oversized(paragraph, max_tokens))

        current = ""
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if current and estimate_tokens(candidate) > max_tokens:
                chunks.append(_make_chunk(len(chunks), current, heading))
                current = piece
            else:
                current = candidate
        if current:
            chunks.append(_make_chunk(len(chunks), current, heading))
    return chunks


def _make_chunk(index: int, content: str, heading: str | None) -> Chunk:
    body = f"{heading}\n{content}" if heading else content
    return Chunk(index=index, content=body, heading=heading, token_count=estimate_tokens(body))
