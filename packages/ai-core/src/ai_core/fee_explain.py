"""관리비 설명 — 확정 데이터 기반 스트리밍 설명 (규칙 5, docs/01 §13, docs/09 §8.2).

확정 업로드 데이터(본인 세대 breakdown·total, 전월 total, 단지 평균)를 컨텍스트로
LLM이 **설명만** 한다. 계산·예측·부과 금지(규칙 5) — 새 금액을 만들지 않고 제공된 수치만 인용.

notice_draft와 달리 검색·인용검증이 없다(원천이 RAG가 아닌 확정 SQL). 마스킹 게이트는
동일하게 통과한다(fail-closed, 규칙 2). 인용은 합성 카드 1건(문서 아님 → document_id 없음).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass

from ai_core.llm.client import LlmClient, LlmUnavailableError
from ai_core.masking import MaskingFailedError, ensure_masked, unmask

FEE_EXPLAIN_MAX_TOKENS = 500  # 설명 한 건 상한(비용, docs/08)
FEE_PREVIEW_ITEMS = 3  # 인용 카드에 노출할 주요 항목 수

FALLBACK_MASKING = "masking_failed"
FALLBACK_LLM_UNAVAILABLE = "llm_unavailable"

FEE_SYSTEM_PROMPT = """당신은 아파트 관리비 설명 도우미입니다. 규칙:
1. 아래 [확정 데이터]에 있는 수치만 사용해 설명하십시오. 데이터에 없는 값은 절대 지어내지 마십시오.
2. 계산·예측·부과를 하지 마십시오. 이미 확정된 금액을 안내·설명만 하십시오.
3. 새로운 합계나 금액을 만들어내지 말고, 제공된 확정 수치만 인용하십시오.
4. 정중하고 간결한 한국어로 설명하십시오."""


@dataclass(frozen=True)
class ExplainStatus:
    stage: str  # generating


@dataclass(frozen=True)
class ExplainToken:
    text: str


@dataclass(frozen=True)
class ExplainCitation:
    document_title: str  # "관리비 YYYY-MM 확정 데이터"
    quote: str


@dataclass(frozen=True)
class ExplainDone:
    status: str  # answered | fallback
    confidence: float
    needs_review: bool
    fallback_reason: str | None = None


ExplainEvent = ExplainStatus | ExplainToken | ExplainCitation | ExplainDone


async def explain_fee(
    *,
    llm: LlmClient,
    period: str,
    breakdown: Mapping[str, int],
    total: int,
    prev_total: int | None,
    avg_total: int | None,
) -> AsyncIterator[ExplainEvent]:
    """확정 관리비 컨텍스트로 설명 스트림 생성. 항상 마지막에 ExplainDone."""
    context = build_fee_context(period, breakdown, total, prev_total, avg_total)
    yield ExplainStatus(stage="generating")

    try:
        masked = ensure_masked(context)  # fail-closed(규칙 2)
    except MaskingFailedError:
        yield ExplainDone("fallback", 0.0, True, FALLBACK_MASKING)
        return

    messages = [
        {"role": "system", "content": FEE_SYSTEM_PROMPT},
        {"role": "user", "content": masked.masked_text},
    ]
    parts: list[str] = []
    try:
        async for delta in llm.chat_stream(messages, max_tokens=FEE_EXPLAIN_MAX_TOKENS):
            parts.append(delta)
            yield ExplainToken(text=delta)
    except LlmUnavailableError:
        yield ExplainDone("fallback", 0.0, False, FALLBACK_LLM_UNAVAILABLE)
        return

    answer = unmask("".join(parts).strip(), masked.replacements)
    if not answer:
        yield ExplainDone("fallback", 0.0, False, FALLBACK_LLM_UNAVAILABLE)
        return

    yield ExplainCitation(
        document_title=f"관리비 {period} 확정 데이터",
        quote=_summary_quote(period, breakdown, total),
    )
    # 신뢰도는 컨텍스트 완전성 기준 단순값(전월·평균 존재 여부). 검색 점수 아님.
    yield ExplainDone("answered", confidence=_confidence(prev_total, avg_total), needs_review=False)


def build_fee_context(
    period: str,
    breakdown: Mapping[str, int],
    total: int,
    prev_total: int | None,
    avg_total: int | None,
) -> str:
    """LLM 프롬프트용 확정 수치 블록. 여기 없는 값은 답에 등장하면 안 된다(규칙 5)."""
    lines = [f"[확정 데이터] 관리비 {period}"]
    for name, amount in breakdown.items():
        lines.append(f"- {name}: {amount:,}원")
    lines.append(f"- 합계: {total:,}원")
    if prev_total is not None:
        lines.append(f"- 전월 합계: {prev_total:,}원")
    if avg_total is not None:
        lines.append(f"- 단지 평균 합계: {avg_total:,}원")
    return "\n".join(lines)


def _summary_quote(period: str, breakdown: Mapping[str, int], total: int) -> str:
    top = list(breakdown.items())[:FEE_PREVIEW_ITEMS]
    items = ", ".join(f"{name} {amount:,}원" for name, amount in top)
    return f"{period} 합계 {total:,}원 (주요 항목: {items})"


def _confidence(prev_total: int | None, avg_total: int | None) -> float:
    score = 0.6
    if prev_total is not None:
        score += 0.2
    if avg_total is not None:
        score += 0.2
    return round(score, 2)
