"""질의 오케스트레이터 — 검색→마스킹→생성→인용검증→신뢰도 (docs/01 §5.2·§6).

이벤트 스트림(AsyncIterator[AssistantEvent])을 내보낸다 — api 계층이 SSE 4종
(status·token·citation·done)으로 그대로 매핑한다(docs/09 §1.1, 이벤트 계약 불변).

폴백 원칙(규칙 1·2):
- 근거 0 / NO_EVIDENCE / 신뢰도 미달 → 담당자 연결 폴백(지어내지 않음)
- 마스킹 실패 → LLM 호출 중단(fail-closed) 후 폴백
- LLM 미가용 → 검색 발췌만 출처와 함께 제공(docs/01 §10)

# ponytail: H1은 도구 1종(search_documents)이라 LLM 도구선택 루프 없이 고정 1스텝 검색.
# H2에서 도구 레지스트리 + tool-calling 루프(스텝 상한 2~3)로 확장(ADR-0007).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from ai_core.budget import ScoredChunk, fit_chunks
from ai_core.citations import Citation, verify_citations
from ai_core.confidence import assess
from ai_core.llm.client import ChatUsage, LlmClient, LlmError, LlmUnavailableError
from ai_core.llm.tokens import estimate_tokens
from ai_core.masking import MaskingFailedError, ensure_masked, unmask
from ai_core.rag.prompt import NO_EVIDENCE_MARKER, SYSTEM_PROMPT, build_user_message
from ai_core.rag.retrieval import MIN_SCORE, RetrievedChunk, Retriever

# 검색 컨텍스트 토큰 예산(모델 8k 가정 × 0.5 중 실용 초기값 — 파일럿 보정)
CONTEXT_BUDGET_TOKENS = 2400


# ── 이벤트 (SSE 계약과 1:1) ─────────────────────────────────────────────


@dataclass(frozen=True)
class StatusEvent:
    stage: str  # searching | generating | verifying


@dataclass(frozen=True)
class TokenEvent:
    text: str


@dataclass(frozen=True)
class CitationEvent:
    citation: Citation


@dataclass(frozen=True)
class DoneEvent:
    status: str  # answered | fallback
    confidence: float
    needs_review: bool
    usage: ChatUsage | None
    fallback_reason: str | None = None
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    answer: str = ""


AssistantEvent = StatusEvent | TokenEvent | CitationEvent | DoneEvent

FALLBACK_NO_EVIDENCE = "no_evidence"
FALLBACK_MASKING = "masking_failed"
FALLBACK_LOW_CONFIDENCE = "low_confidence"
FALLBACK_LLM_UNAVAILABLE = "llm_unavailable"


async def answer_question(
    question: str,
    *,
    llm: LlmClient,
    retriever: Retriever,
    tenant_id: uuid.UUID,
    visibilities: Sequence[str],
    extra_names: Sequence[str] = (),
) -> AsyncIterator[AssistantEvent]:
    """질의 1건 처리. 항상 마지막에 DoneEvent를 낸다."""
    # 1) 검색 (질의 임베딩 → pgvector)
    yield StatusEvent(stage="searching")
    try:
        query_vec = (await llm.embed([question]))[0]
    except LlmError:
        yield DoneEvent(
            status="fallback",
            confidence=0.0,
            needs_review=False,
            usage=None,
            fallback_reason=FALLBACK_LLM_UNAVAILABLE,
        )
        return
    chunks = await retriever.search(query_vec, tenant_id=tenant_id, visibilities=visibilities)
    evidence = _fit(chunks)
    if not evidence:
        yield DoneEvent(
            status="fallback",
            confidence=0.0,
            needs_review=False,
            usage=None,
            fallback_reason=FALLBACK_NO_EVIDENCE,
        )
        return

    # 2) 마스킹 게이트 (질문+근거, fail-closed — 규칙 2)
    try:
        masked_user = ensure_masked(build_user_message(question, evidence), extra_names=extra_names)
    except MaskingFailedError:
        yield DoneEvent(
            status="fallback",
            confidence=0.0,
            needs_review=True,
            usage=None,
            fallback_reason=FALLBACK_MASKING,
        )
        return

    # 3) 생성 (스트리밍) — LLM 다운이면 발췌 폴백(출처는 유지)
    yield StatusEvent(stage="generating")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": masked_user.masked_text},
    ]
    parts: list[str] = []
    try:
        async for delta in llm.chat_stream(messages):
            parts.append(delta)
            yield TokenEvent(text=delta)
    except LlmUnavailableError:
        check = verify_citations("[1]", evidence)  # 최상위 발췌 1건을 출처로
        for citation in check.citations:
            yield CitationEvent(citation=citation)
        yield DoneEvent(
            status="fallback",
            confidence=0.0,
            needs_review=False,
            usage=None,
            fallback_reason=FALLBACK_LLM_UNAVAILABLE,
            citations=check.citations,
        )
        return
    # 답변 속 플레이스홀더는 원문 복원(본인 데이터 표시·영속용).
    # 한계: TokenEvent 스트림은 마스킹된 그대로 나간다(플레이스홀더가 델타에 걸쳐
    # 쪼개질 수 있어 실시간 복원 불가) — 최종 표시는 done.answer 기준.
    answer = unmask("".join(parts).strip(), masked_user.replacements)
    # 스트리밍은 usage 미제공 → 추정치로 비용 기록(docs/08 §9)
    usage = ChatUsage(
        input_tokens=sum(estimate_tokens(m["content"]) for m in messages),
        output_tokens=estimate_tokens(answer),
        estimated=True,
    )

    # 4) 인용 검증·신뢰도 (규칙 1·6)
    yield StatusEvent(stage="verifying")
    if not answer or NO_EVIDENCE_MARKER in answer:
        yield DoneEvent(
            status="fallback",
            confidence=0.0,
            needs_review=False,
            usage=usage,
            fallback_reason=FALLBACK_NO_EVIDENCE,
        )
        return
    check = verify_citations(answer, evidence)
    verdict = assess(
        top_retrieval_score=evidence[0].score,
        citations_valid=check.is_valid,
        invalid_citation_count=len(check.invalid_refs),
    )
    if verdict.should_fallback or not check.citations:
        yield DoneEvent(
            status="fallback",
            confidence=verdict.score,
            needs_review=True,
            usage=usage,
            fallback_reason=FALLBACK_LOW_CONFIDENCE,
        )
        return
    for citation in check.citations:
        yield CitationEvent(citation=citation)
    yield DoneEvent(
        status="answered",
        confidence=verdict.score,
        needs_review=verdict.needs_review,
        usage=usage,
        citations=check.citations,
        answer=answer,
    )


def _fit(chunks: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    """MIN_SCORE 미달 제거 → 토큰 예산 절단(원본 RetrievedChunk 순서·매핑 유지)."""
    eligible = [c for c in chunks if c.score >= MIN_SCORE]
    by_id = {str(c.chunk_id): c for c in eligible}
    fitted = fit_chunks(
        [ScoredChunk(id=str(c.chunk_id), content=c.content, score=c.score) for c in eligible],
        budget_tokens=CONTEXT_BUDGET_TOKENS,
    )
    return [by_id[s.id] for s in fitted]
