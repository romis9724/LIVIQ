"""컨텍스트 예산 — 검색 청크를 토큰 예산 안으로 절단 (docs/08 §3).

점수순 정렬 → 근사 중복 제거 → 예산 내 그리디 선택. 순서는 결정적(score desc, id asc).
근거가 충분하면 더 넣지 않는다 — 많을수록 좋다 ✗.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from ai_core.llm.tokens import estimate_tokens

# 모델 입력 상한 중 검색 컨텍스트에 할당하는 기본 비율(docs/08 §3)
DEFAULT_CONTEXT_RATIO = 0.5
# 근사 중복 판정: 정규화된 내용 앞부분 비교 길이
_DEDUPE_PREFIX_CHARS = 80

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class ScoredChunk:
    id: str
    content: str
    score: float
    token_count: int | None = None

    @property
    def tokens(self) -> int:
        return self.token_count if self.token_count is not None else estimate_tokens(self.content)


def budget_for_model(input_limit_tokens: int, ratio: float = DEFAULT_CONTEXT_RATIO) -> int:
    """모델 입력 상한에서 검색 컨텍스트에 할당할 토큰 예산."""
    if input_limit_tokens <= 0:
        return 0
    return int(input_limit_tokens * ratio)


def _dedupe_key(content: str) -> str:
    return _WHITESPACE.sub(" ", content.strip())[:_DEDUPE_PREFIX_CHARS]


def fit_chunks(chunks: Sequence[ScoredChunk], *, budget_tokens: int) -> list[ScoredChunk]:
    """점수 상위부터 예산 내 그리디 선택(초과 청크는 건너뛰고 계속), 근사 중복 제거."""
    if budget_tokens <= 0:
        return []
    ordered = sorted(chunks, key=lambda c: (-c.score, c.id))
    selected: list[ScoredChunk] = []
    seen: set[str] = set()
    remaining = budget_tokens
    for chunk in ordered:
        key = _dedupe_key(chunk.content)
        if not key or key in seen:
            continue
        if chunk.tokens > remaining:
            continue
        selected.append(chunk)
        seen.add(key)
        remaining -= chunk.tokens
    return selected
