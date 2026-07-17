"""질의 오케스트레이터 — 읽기 전용 도구호출 에이전트 (ADR-0007, docs/01 §5.2).

흐름(스텝 상한 있는 도구 루프):
1. 도구 결정 turn = **비스트리밍 chat(tools=역할 필터 스펙)** — 질문은 ensure_masked 후 전송.
2. tool_calls 반환 시: 인자 Pydantic 검증(실패=오류 메시지, 크래시 없음) → 실행 → 결과를
   마스킹해 대화에 추가 → 재호출. 스텝 상한(MAX_TOOL_STEPS) 초과 시 현재 근거로 종료.
3. 최종 답변 turn = **chat_stream** — 문서 청크(_fit)+도구 결과 카드를 근거로 생성.
4. 인용검증·신뢰도(기존 재사용). 도구 결과 인용은 별도 CitationEvent로 방출(document_id=None).

이벤트 스트림(AsyncIterator[AssistantEvent]) → api가 SSE 4종(status·token·citation·done)으로
매핑한다(docs/09 §1.1, 이벤트 계약 불변 — status stage 3종·citation 리터럴 확장 없음).

폴백 원칙(규칙 1·2):
- 근거 0 / NO_EVIDENCE / 신뢰도 미달 → 담당자 연결 폴백(지어내지 않음)
- 마스킹 실패 → LLM 호출 중단(fail-closed) 후 폴백
- LLM 미가용 → 검색 발췌만 출처와 함께 제공(docs/01 §10)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field

from ai_core.budget import ScoredChunk, fit_chunks
from ai_core.citations import Citation, verify_citations
from ai_core.confidence import assess
from ai_core.llm.client import ChatUsage, LlmError, LlmUnavailableError, ToolCallRequest
from ai_core.llm.tokens import estimate_tokens
from ai_core.masking import MaskingFailedError, ensure_masked, unmask
from ai_core.rag.prompt import (
    AGENT_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    NO_EVIDENCE_MARKER,
    build_context_block,
)
from ai_core.rag.retrieval import MIN_SCORE, RetrievedChunk
from ai_core.tools.registry import (
    ToolCard,
    ToolContext,
    ToolDeps,
    ToolRegistry,
    ToolResult,
    execute_tool,
)

logger = logging.getLogger("ai_core.orchestrator")

# 검색 컨텍스트 토큰 예산(모델 8k 가정 × 0.5 중 실용 초기값 — 파일럿 보정)
CONTEXT_BUDGET_TOKENS = 2400
# 도구 결정 turn 상한(ADR-0007) — 초과 시 현재 근거로 답변/폴백.
MAX_TOOL_STEPS = 3
# 확정 데이터·도구 결과만으로 답할 때의 신뢰도(검색 점수 아님 — fee_explain와 동일 원칙).
TOOL_ONLY_CONFIDENCE = 0.8


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
class ToolCitation:
    """도구 결과 출처 카드 — 문서 인용과 달리 document_id/chunk_id 없음(source_kind=tool:*)."""

    ref: int
    title: str
    quote: str
    source_kind: str


@dataclass(frozen=True)
class ToolCitationEvent:
    citation: ToolCitation


@dataclass(frozen=True)
class DoneEvent:
    status: str  # answered | fallback
    confidence: float
    needs_review: bool
    usage: ChatUsage | None
    fallback_reason: str | None = None
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    tool_citations: tuple[ToolCitation, ...] = field(default_factory=tuple)
    answer: str = ""
    # 호출한 도구 이름 순서(골든셋 회귀·규칙 8 관측용, H3-4). additive 필드 — SSE 4종 불변.
    tool_path: tuple[str, ...] = field(default_factory=tuple)


AssistantEvent = StatusEvent | TokenEvent | CitationEvent | ToolCitationEvent | DoneEvent

FALLBACK_NO_EVIDENCE = "no_evidence"
FALLBACK_MASKING = "masking_failed"
FALLBACK_LOW_CONFIDENCE = "low_confidence"
FALLBACK_LLM_UNAVAILABLE = "llm_unavailable"


async def answer_question(
    question: str,
    *,
    registry: ToolRegistry,
    deps: ToolDeps,
    ctx: ToolContext,
    extra_names: Sequence[str] = (),
    answer_prompt: str = ANSWER_SYSTEM_PROMPT,
) -> AsyncIterator[AssistantEvent]:
    """질의 1건 처리(도구 에이전트). 항상 마지막에 DoneEvent를 낸다.

    answer_prompt: 최종 답변 turn의 시스템 프롬프트(기본 = 일반 응대). 시설 도우미(H3-4)는
    FACILITY_ANSWER_SYSTEM_PROMPT를 주입해 원인 후보 형식을 강제한다 — 나머지 경로는 공유.
    """
    llm = deps.llm
    yield StatusEvent(stage="searching")

    # 질문 마스킹(fail-closed, 규칙 2) — 실패면 즉시 폴백.
    try:
        masked_question = ensure_masked(question, extra_names=extra_names).masked_text
    except MaskingFailedError:
        yield _fallback(FALLBACK_MASKING, needs_review=True)
        return

    specs = registry.specs_for(ctx.roles, graph_available=deps.graph_available)
    messages: list[dict[str, object]] = [
        {"role": "system", "content": AGENT_SYSTEM_PROMPT},
        {"role": "user", "content": masked_question},
    ]

    doc_chunks: list[RetrievedChunk] = []
    seen_chunk_ids: set[str] = set()
    cards: list[ToolCard] = []
    tool_path: list[str] = []
    llm_down = False

    # ── 도구 결정 루프(스텝 상한) ──────────────────────────────────────
    for _step in range(MAX_TOOL_STEPS):
        try:
            decision = await llm.chat(messages, tools=specs, tool_choice="auto")
        except LlmUnavailableError:
            llm_down = True
            break
        except LlmError:
            break
        if not decision.tool_calls:
            break
        messages.append(_assistant_tool_calls_message(decision.tool_calls))
        for call in decision.tool_calls:
            execution = await execute_tool(call, ctx=ctx, deps=deps, registry=registry)
            tool_path.append(call.name)
            content = _absorb_and_mask(
                execution.result, doc_chunks, seen_chunk_ids, cards, extra_names
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

    logger.info(
        "assistant tool_path", extra={"tool_path": tool_path, "tenant_id": str(ctx.tenant_id)}
    )

    path = tuple(tool_path)
    if llm_down and not doc_chunks and not cards:
        yield _fallback(FALLBACK_LLM_UNAVAILABLE, tool_path=path)
        return

    # ── 근거 조립 ──────────────────────────────────────────────────────
    evidence = _fit(doc_chunks)
    if not evidence and not cards:
        yield _fallback(FALLBACK_NO_EVIDENCE, tool_path=path)
        return

    final_user = _build_final_user_message(question, evidence, cards)
    try:
        masked_final = ensure_masked(final_user, extra_names=extra_names)
    except MaskingFailedError:
        yield _fallback(FALLBACK_MASKING, needs_review=True, tool_path=path)
        return

    # ── 최종 답변(스트리밍) ────────────────────────────────────────────
    yield StatusEvent(stage="generating")
    final_messages = [
        {"role": "system", "content": answer_prompt},
        {"role": "user", "content": masked_final.masked_text},
    ]
    parts: list[str] = []
    try:
        async for delta in llm.chat_stream(final_messages):
            parts.append(delta)
            yield TokenEvent(text=delta)
    except LlmUnavailableError:
        async for event in _excerpt_fallback(evidence, cards, tool_path=path):
            yield event
        return

    answer = unmask("".join(parts).strip(), masked_final.replacements)
    usage = ChatUsage(
        input_tokens=sum(estimate_tokens(str(m["content"])) for m in final_messages),
        output_tokens=estimate_tokens(answer),
        estimated=True,
    )

    # ── 인용검증·신뢰도 ────────────────────────────────────────────────
    yield StatusEvent(stage="verifying")
    if not answer or NO_EVIDENCE_MARKER in answer:
        yield _fallback(FALLBACK_NO_EVIDENCE, usage=usage, tool_path=path)
        return

    check = verify_citations(answer, evidence)
    doc_citations = check.citations
    if not doc_citations and not cards:
        # 답변에 유효한 [n] 인용이 없고 도구 카드도 없다 → 근거 미검증(규칙 1).
        yield _fallback(FALLBACK_NO_EVIDENCE, usage=usage, tool_path=path)
        return

    if evidence:
        verdict = assess(
            top_retrieval_score=evidence[0].score,
            citations_valid=check.is_valid or bool(cards),
            invalid_citation_count=len(check.invalid_refs),
        )
        score = verdict.score
        needs_review = verdict.needs_review
        # 도구 카드(확정 데이터)가 있으면 저신뢰 폴백하지 않는다 — 카드가 권위 있는 근거.
        should_fallback = verdict.should_fallback and not cards
    else:
        # 도구 카드만으로 답변(확정 SQL 데이터) — 검색 점수 없음, 폴백 안 함.
        score = TOOL_ONLY_CONFIDENCE
        needs_review = False
        should_fallback = False

    if should_fallback:
        yield _fallback(
            FALLBACK_LOW_CONFIDENCE,
            confidence=score,
            needs_review=True,
            usage=usage,
            tool_path=path,
        )
        return

    for citation in doc_citations:
        yield CitationEvent(citation=citation)
    tool_citations = _tool_citations(cards, start=len(evidence) + 1)
    for tc in tool_citations:
        yield ToolCitationEvent(citation=tc)

    yield DoneEvent(
        status="answered",
        confidence=score,
        needs_review=needs_review,
        usage=usage,
        citations=doc_citations,
        tool_citations=tool_citations,
        answer=answer,
        tool_path=path,
    )


# ── 헬퍼 ───────────────────────────────────────────────────────────────


def _fallback(
    reason: str,
    *,
    confidence: float = 0.0,
    needs_review: bool = False,
    usage: ChatUsage | None = None,
    tool_path: Sequence[str] = (),
) -> DoneEvent:
    return DoneEvent(
        status="fallback",
        confidence=confidence,
        needs_review=needs_review,
        usage=usage,
        fallback_reason=reason,
        tool_path=tuple(tool_path),
    )


def _assistant_tool_calls_message(tool_calls: Sequence[ToolCallRequest]) -> dict[str, object]:
    """OpenAI 규약의 assistant tool_calls 메시지 재구성(재호출 컨텍스트용)."""
    calls = [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.name, "arguments": tc.arguments},
        }
        for tc in tool_calls
    ]
    return {"role": "assistant", "content": None, "tool_calls": calls}


def _absorb_and_mask(
    result: ToolResult,
    doc_chunks: list[RetrievedChunk],
    seen_chunk_ids: set[str],
    cards: list[ToolCard],
    extra_names: Sequence[str],
) -> str:
    """도구 결과를 근거에 누적하고, LLM에 되먹일 텍스트를 마스킹해 반환(규칙 2).

    마스킹 불가한 근거는 사용하지 않는다(evidence에도 추가하지 않음) — 최종 답변 rebuild가
    2차 게이트지만, 루프 turn에도 원문 PII가 새면 안 되므로 여기서 fail-closed.
    """
    if result.doc_chunks:
        new = [c for c in result.doc_chunks if str(c.chunk_id) not in seen_chunk_ids]
        if not new:
            return "이미 조회한 문서입니다."
        block = build_context_block(new, start=len(doc_chunks) + 1)
        masked, ok = _safe_mask(block, extra_names)
        if not ok:
            return "(민감정보 포함으로 생략됨)"
        for c in new:
            seen_chunk_ids.add(str(c.chunk_id))
        doc_chunks.extend(new)
        return masked
    if result.card is not None:
        masked, ok = _safe_mask(result.llm_text(), extra_names)
        if not ok:
            return "(민감정보 포함으로 생략됨)"
        cards.append(result.card)
        return masked
    # 데이터 없음/오류 안내 — 근거 아님(카드·청크 생성 안 함)이나 그대로도 마스킹.
    masked, ok = _safe_mask(result.note, extra_names)
    return masked if ok else "(처리 불가)"


def _safe_mask(text_value: str, extra_names: Sequence[str]) -> tuple[str, bool]:
    if not text_value:
        return "", True
    try:
        return ensure_masked(text_value, extra_names=extra_names).masked_text, True
    except MaskingFailedError:
        return "", False


def _build_final_user_message(
    question: str, chunks: Sequence[RetrievedChunk], cards: Sequence[ToolCard]
) -> str:
    parts: list[str] = []
    if chunks:
        parts.append("[문서 근거]\n" + build_context_block(chunks))
    if cards:
        lines = "\n".join(f"- {c.title}: {c.quote}" for c in cards)
        parts.append("[확정 데이터·도구 결과]\n" + lines)
    parts.append(f"[질문]\n{question}")
    return "\n\n".join(parts)


def _tool_citations(cards: Sequence[ToolCard], *, start: int) -> tuple[ToolCitation, ...]:
    return tuple(
        ToolCitation(ref=start + i, title=c.title, quote=c.quote, source_kind=c.source_kind)
        for i, c in enumerate(cards)
    )


async def _excerpt_fallback(
    evidence: Sequence[RetrievedChunk],
    cards: Sequence[ToolCard],
    *,
    tool_path: Sequence[str] = (),
) -> AsyncIterator[AssistantEvent]:
    """LLM 미가용 시 발췌 폴백 — 출처(문서 최상위 발췌 + 도구 카드)는 유지(docs/01 §10)."""
    doc_citations: tuple[Citation, ...] = ()
    if evidence:
        doc_citations = verify_citations("[1]", evidence).citations
        for citation in doc_citations:
            yield CitationEvent(citation=citation)
    tool_citations = _tool_citations(cards, start=len(evidence) + 1)
    for tc in tool_citations:
        yield ToolCitationEvent(citation=tc)
    yield DoneEvent(
        status="fallback",
        confidence=0.0,
        needs_review=False,
        usage=None,
        fallback_reason=FALLBACK_LLM_UNAVAILABLE,
        citations=doc_citations,
        tool_citations=tool_citations,
        tool_path=tuple(tool_path),
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
