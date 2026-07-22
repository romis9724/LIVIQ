"""인용 추출·실재 검증 (규칙 1 — 출처 없는 답변 금지).

LLM 응답의 [n] 인용을 파싱해 실제 근거 청크와 대조한다.
- 존재하지 않는 번호 인용 = 환각 신호(무효 인용으로 집계).
- 유효 인용 0개면 상위(오케스트레이터)가 폴백 판단.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from ai_core.rag.retrieval import RetrievedChunk

_CITATION_REF_RE = re.compile(r"\[(\d+)\]")
# 출처 카드에 싣는 발췌 길이
_QUOTE_MAX_CHARS = 200


@dataclass(frozen=True)
class Citation:
    """검증된 인용 — citations 테이블(source_kind=document_chunk)에 대응."""

    ref: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID | None  # notice 청크 인용은 None(source는 document_title로 표기)
    document_title: str
    quote: str
    page: int | None
    clause: str | None


@dataclass(frozen=True)
class CitationCheck:
    citations: tuple[Citation, ...]
    invalid_refs: tuple[int, ...]  # 근거에 없는 번호를 인용(환각 신호)

    @property
    def is_valid(self) -> bool:
        return bool(self.citations) and not self.invalid_refs


def verify_citations(answer: str, chunks: Sequence[RetrievedChunk]) -> CitationCheck:
    """응답 속 [n]을 근거 목록과 대조. n은 1-기반(프롬프트 빌더와 동일)."""
    refs = sorted({int(m) for m in _CITATION_REF_RE.findall(answer)})
    citations: list[Citation] = []
    invalid: list[int] = []
    for ref in refs:
        if 1 <= ref <= len(chunks):
            chunk = chunks[ref - 1]
            citations.append(
                Citation(
                    ref=ref,
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_title=chunk.document_title,
                    quote=chunk.content[:_QUOTE_MAX_CHARS],
                    page=chunk.page,
                    clause=chunk.clause,
                )
            )
        else:
            invalid.append(ref)
    return CitationCheck(citations=tuple(citations), invalid_refs=tuple(invalid))
