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

import json
import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from ai_core.backend_config import DEFAULT_TOOL_CONFIDENCE
from ai_core.budget import ScoredChunk, fit_chunks
from ai_core.citations import Citation, verify_citations
from ai_core.confidence import assess
from ai_core.llm.client import (
    ChatUsage,
    LlmError,
    LlmUnavailableError,
    ToolCallRequest,
)
from ai_core.llm.tokens import estimate_tokens
from ai_core.masking import MaskingFailedError, ensure_masked, unmask
from ai_core.rag.prompt import (
    AGENT_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    NO_EVIDENCE_MARKER,
    build_context_block,
)
from ai_core.rag.retrieval import MIN_SCORE, RetrievedChunk
from ai_core.suggestions import suggest_next_actions
from ai_core.tools.clarify import CLARIFY_TOOL_NAME, ClarificationArgs, build_clarification
from ai_core.tools.registry import (
    ToolCard,
    ToolContext,
    ToolDeps,
    ToolRegistry,
    ToolResult,
    execute_tool,
)

logger = logging.getLogger("ai_core.orchestrator")

# 검색 컨텍스트 토큰 예산(모델 8k 가정 × 0.5 중 실용 초기값).
# 운영 문서 청크가 평균 488토큰이라 2400은 top_k 16 중 4~5개만 최종 프롬프트에 넣는다.
# 4000으로 올려 실측했으나(H15-2 R17) pass·인용·폴백 전부 기존 변동폭 내, 지연만 p50 +7%·
# p95 +17% — 8B 모델은 근거를 더 줘도 선별을 못 한다(lost-in-the-middle). 2400 유지.
CONTEXT_BUDGET_TOKENS = 2400
# 도구 결정 turn 상한(ADR-0007) — 초과 시 현재 근거로 답변/폴백.
# 3 → 4(ADR-0025 §2): 계획 turn 1회가 도구 turn 예산을 먹지 않게 한 칸 늘렸다(계획 1 + 도구 3).
MAX_TOOL_STEPS = 4
# 계획 turn 상한 — 무-도구 turn을 계획으로 재해석하는 횟수. 1로 고정한다: 2회 이상 허용하면
# 도구를 안 부르는 모델이 상한까지 빈 turn을 돌며 토큰만 태운다(무한 루프 방지).
MAX_PLAN_TURNS = 1
# 확정 데이터·도구 결과만으로 답할 때의 신뢰도(검색 점수 아님 — fee_explain와 동일 원칙).
# 정본은 backend_config(관리자 노브 `tool_confidence`의 기본값과 같은 값이어야 한다, H15-3).
TOOL_ONLY_CONFIDENCE = DEFAULT_TOOL_CONFIDENCE
# 멀티턴 컨텍스트(ADR-0025 §3) — 직전 3턴(user/assistant 쌍)만, 턴당 400자.
# 더 넣으면 도구 결정 turn의 입력이 선형으로 불어난다(질의 원가의 대부분이 이 turn — H15-2).
HISTORY_MAX_TURNS = 3
HISTORY_MAX_CHARS = 400


# ── 이벤트 (SSE 계약과 1:1) ─────────────────────────────────────────────


@dataclass(frozen=True)
class StatusEvent:
    stage: str  # searching | generating | verifying
    # 지금 실행 중인 도구 이름(ADR-0025 §5) — additive 필드, stage 리터럴 3종은 불변.
    # 기존 소비자는 stage만 읽으면 그대로 동작한다.
    tool: str | None = None


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
    # 화면 전용 구조화 페이로드 — ToolCard.data 그대로(재가공 금지, ADR-0025 §6).
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolCitationEvent:
    citation: ToolCitation


@dataclass(frozen=True)
class DoneEvent:
    status: str  # answered | fallback | clarify(되묻기 — ADR-0025 §4)
    confidence: float
    needs_review: bool
    # 질의 1건의 **전 turn 합산**(도구 결정 turn + 최종 답변 turn, H15-2). LLM 호출 0회면 None.
    # estimated=True면 추정치 혼입(최종 답변 turn은 스트리밍이라 프로바이더 usage가 없다).
    usage: ChatUsage | None
    fallback_reason: str | None = None
    citations: tuple[Citation, ...] = field(default_factory=tuple)
    tool_citations: tuple[ToolCitation, ...] = field(default_factory=tuple)
    answer: str = ""
    # 호출한 도구 이름 순서(골든셋 회귀·규칙 8 관측용, H3-4). additive 필드 — SSE 4종 불변.
    tool_path: tuple[str, ...] = field(default_factory=tuple)
    # 다음 행동 제안(ADR-0025 §7) — tool_path 기반 코드 규칙, LLM 호출 0. 빈 튜플이면 렌더 안 함.
    suggestions: tuple[str, ...] = field(default_factory=tuple)


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
    history: Sequence[tuple[str, str]] = (),
    allow_clarify: bool = True,
    extra_names: Sequence[str] = (),
    answer_prompt: str = ANSWER_SYSTEM_PROMPT,
    tool_confidence: float = TOOL_ONLY_CONFIDENCE,
) -> AsyncIterator[AssistantEvent]:
    """질의 1건 처리(도구 에이전트). 항상 마지막에 DoneEvent를 낸다.

    history: 직전 턴의 `(role, text)`(오래된 것 → 최신). 답변 **본문만** 넣는다 — 도구
    카드·인용 원문을 재전송하면 토큰이 폭증한다(ADR-0025 §3). 상한은 HISTORY_MAX_*.
    allow_clarify: 되묻기 도구 노출 여부. 직전 턴이 되묻기였으면 False로 넘겨 스펙에서
    빼야 한다 — 연속 되묻기 금지(ADR-0025 §4). LLM 인자로 받지 않는다.
    answer_prompt: 최종 답변 turn의 시스템 프롬프트(기본 = 일반 응대). 시설 도우미(H3-4)는
    FACILITY_ANSWER_SYSTEM_PROMPT를 주입해 원인 후보 형식을 강제한다 — 나머지 경로는 공유.
    tool_confidence: 도구 결과만으로 답할 때의 신뢰도(관리자 노브, 기본=코드 상수 H15-3).
    """
    llm = deps.llm
    yield StatusEvent(stage="searching")

    # 질문·히스토리 마스킹(fail-closed, 규칙 2) — 실패면 즉시 폴백.
    # 히스토리라고 조용히 버리지 않는다: 마스킹 실패는 컨텍스트 품질 문제가 아니라
    # PII 잔존 신호이므로 질문과 똑같이 LLM 호출을 중단해야 한다.
    try:
        masked_question = ensure_masked(question, extra_names=extra_names).masked_text
        recent = _prepare_history(history, extra_names)
    except MaskingFailedError:
        yield _fallback(FALLBACK_MASKING, needs_review=True)
        return

    specs = registry.specs_for(ctx.roles, graph_available=deps.graph_available)
    if not allow_clarify:
        specs = [s for s in specs if s["function"]["name"] != CLARIFY_TOOL_NAME]
    messages: list[dict[str, object]] = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
    # 히스토리는 OpenAI 규약대로 개별 user/assistant 메시지로 넣는다(도구 결정 turn).
    for role, content in recent:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": masked_question})

    doc_chunks: list[RetrievedChunk] = []
    seen_chunk_ids: set[str] = set()
    cards: list[ToolCard] = []
    seen_cards: set[tuple[str, str]] = set()
    # 이미 실행한 (도구, 정규화 인자) — 같은 호출의 재실행을 막는다(아래 루프 주석).
    seen_calls: set[tuple[str, str]] = set()
    tool_path: list[str] = []
    llm_down = False
    # turn별 usage — 도구 결정 turn이 비용의 대부분(도구 결과가 다음 turn에 재전송된다).
    # 최종 답변만 세면 원가가 3분의 1 수준 하한으로 나온다(H15-2 실측).
    usage_turns: list[ChatUsage] = []

    # ── 도구 결정 루프(스텝 상한) ──────────────────────────────────────
    plan_turns = 0
    for _step in range(MAX_TOOL_STEPS):
        try:
            decision = await llm.chat(messages, tools=specs, tool_choice="auto")
        except LlmUnavailableError:
            llm_down = True
            break
        except LlmError:
            break
        usage_turns.append(decision.usage)
        if not decision.tool_calls:
            # 무-도구 turn 재해석(ADR-0025 §2): content가 있으면 "계획"으로 보고 대화에 남긴 뒤
            # 계속 돈다. 계획은 MAX_PLAN_TURNS회 한정 — 그 다음 무-도구 turn은 종료 신호로
            # 되돌아간다(도구를 안 부르는 모델이 상한까지 빈 turn을 도는 것을 막는다).
            plan = decision.text.strip()
            if plan and plan_turns < MAX_PLAN_TURNS:
                plan_turns += 1
                messages.append({"role": "assistant", "content": plan})
                continue
            break
        # 되묻기는 실행하지 않고 즉시 종료한다(ADR-0025 §4). 같은 turn에 다른 도구가 함께
        # 호출돼도 되묻기가 우선 — 되물을 것이 있으면 나머지 조회 결과는 어차피 못 쓴다.
        # 근거 조립·인용 검증을 타지 않는다: 되묻기는 답변이 아니라 질문이라 인용할 근거가
        # 없다(규칙 1 저촉 아님).
        clarify = _clarify_question(decision.tool_calls) if allow_clarify else None
        if clarify is not None:
            tool_path.append(CLARIFY_TOOL_NAME)
            yield DoneEvent(
                status="clarify",
                confidence=0.0,
                needs_review=False,
                # 여기까지 쓴 결정 turn 토큰은 반드시 실어 보낸다(폴백 경로와 같은 원칙).
                usage=_sum_usage(usage_turns),
                answer=clarify,
                tool_path=tuple(tool_path),
            )
            return
        messages.append(_assistant_tool_calls_message(decision.tool_calls))
        executed_any = False
        for call in decision.tool_calls:
            # 같은 도구를 **같은 인자로** 다시 부르면 실행하지 않는다(2026-08-01 dev 실측:
            # find_in_floor_plan 4연속 호출로 스텝 상한을 전부 태웠다 — 지연·토큰 낭비).
            # 인자가 다른 재호출은 정당할 수 있어(다른 달·다른 기기) 키에 인자를 넣는다.
            # 프로토콜상 tool_call마다 응답 메시지가 있어야 하므로 안내만 되돌린다.
            key = (call.name, _args_key(call.arguments))
            if key in seen_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": "이미 같은 조건으로 조회했습니다. 조회한 결과로 답변하십시오.",
                    }
                )
                continue
            seen_calls.add(key)
            executed_any = True
            # 진행 중인 도구를 화면에 노출(ADR-0025 §5) — stage는 searching 그대로.
            yield StatusEvent(stage="searching", tool=call.name)
            execution = await execute_tool(call, ctx=ctx, deps=deps, registry=registry)
            tool_path.append(call.name)
            content = _absorb_and_mask(
                execution.result, doc_chunks, seen_chunk_ids, cards, seen_cards, extra_names
            )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
        if not executed_any:
            # 이번 turn이 전부 중복 = 모델이 같은 자리를 맴돈다. 남은 스텝을 태워도 새 근거가
            # 생기지 않으므로 지금 근거로 답변 turn으로 넘어간다. 루프 종료는 스텝 상한과
            # 이 조기 종료 둘 다로 보장된다(무한 루프 없음 — 상한은 그대로 4, ADR-0025 §2).
            break

    logger.info(
        "assistant tool_path", extra={"tool_path": tool_path, "tenant_id": str(ctx.tenant_id)}
    )

    path = tuple(tool_path)
    # 폴백도 결정 루프 토큰을 이미 썼다 — 비용 기록에서 빠지면 원가가 새어나간다.
    spent = _sum_usage(usage_turns)
    if llm_down and not doc_chunks and not cards:
        yield _fallback(FALLBACK_LLM_UNAVAILABLE, usage=spent, tool_path=path)
        return

    # ── 근거 조립 ──────────────────────────────────────────────────────
    evidence = _fit(doc_chunks)
    if not evidence and not cards:
        yield _fallback(FALLBACK_NO_EVIDENCE, usage=spent, tool_path=path)
        return

    final_user = _build_final_user_message(question, evidence, cards, recent)
    try:
        masked_final = ensure_masked(final_user, extra_names=extra_names)
    except MaskingFailedError:
        yield _fallback(FALLBACK_MASKING, needs_review=True, usage=spent, tool_path=path)
        return

    # ── 최종 답변(스트리밍) ────────────────────────────────────────────
    yield StatusEvent(stage="generating")
    final_messages = [
        {"role": "system", "content": answer_prompt},
        {"role": "user", "content": masked_final.masked_text},
    ]
    parts: list[str] = []
    # 마커 판정이 끝나기 전에는 토큰을 내보내지 않는다 — 아래 폴백 검사는 스트림이 끝난 뒤에야
    # 돌기 때문에, 그때까지 흘려보낸 토큰은 이미 사용자 화면에 남는다(H15-2 #4 실측: 모델이
    # "NO_EVIDENCE" 뒤에 답변을 이어 쓰면 내부 마커와 미검증 답변이 몇 초간 노출됐다).
    streaming = False
    try:
        async for delta in llm.chat_stream(final_messages):
            parts.append(delta)
            if streaming:
                yield TokenEvent(text=delta)
                continue
            gate = _no_evidence_gate(parts)
            if gate == "fallback":
                break
            if gate == "flush":
                streaming = True
                yield TokenEvent(text="".join(parts))
    except LlmUnavailableError:
        async for event in _excerpt_fallback(evidence, cards, tool_path=path, usage=spent):
            yield event
        return

    answer = unmask("".join(parts).strip(), masked_final.replacements)
    # 최종 답변 turn은 스트리밍이라 프로바이더 usage가 없다 → 추정치(estimated=True 전파).
    final_turn = ChatUsage(
        input_tokens=sum(estimate_tokens(str(m["content"])) for m in final_messages),
        output_tokens=estimate_tokens(answer),
        estimated=True,
    )
    usage = _sum_usage([*usage_turns, final_turn])

    # ── 인용검증·신뢰도 ────────────────────────────────────────────────
    yield StatusEvent(stage="verifying")
    if not answer or NO_EVIDENCE_MARKER in answer:
        yield _fallback(FALLBACK_NO_EVIDENCE, usage=usage, tool_path=path)
        return

    check = verify_citations(answer, evidence)
    doc_citations = check.citations
    # 인용 누락 시 1회 재요청을 실측했으나 기각했다(H15-2 R21). 폐기된 답변은 35→23건으로
    # 줄었지만 기대 출처 적중이 122→110/169으로 함께 떨어졌다(양쪽 범위 비겹침). 원인은
    # 재요청이 답변을 22% 짧게 만들며(528→413자) 근거 있는 문장까지 지운 것 — 8B 모델은
    # 사후 귀속을 신뢰성 있게 못 한다(마커를 애초에 안 붙인 것과 같은 한계). 출처 정확성을
    # 답변 가용성과 맞바꾸는 것은 규칙 1의 방향이 아니다 — 틀린 인용은 폴백보다 나쁘다.
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
        score = tool_confidence
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
        suggestions=suggest_next_actions(path, status="answered"),
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
        suggestions=suggest_next_actions(tool_path, status="fallback"),
    )


def _prepare_history(
    history: Sequence[tuple[str, str]], extra_names: Sequence[str]
) -> tuple[tuple[str, str], ...]:
    """직전 턴을 상한만큼 자른 뒤 마스킹(규칙 2 — 실패는 MaskingFailedError로 전파).

    자르기를 마스킹보다 **먼저** 한다: 게이트를 통과해야 하는 것은 실제로 전송할 문자열
    그대로다(마스킹 후 자르면 플레이스홀더가 잘려 원문이 되살아날 수 있다).
    턴 = user/assistant 쌍이라 메시지 상한은 그 2배. 빈 본문(폴백 메시지 등)은 버린다 —
    답변 본문이 없는 턴은 맥락을 주지 않고 토큰만 먹는다.
    """
    turns: list[tuple[str, str]] = []
    for role, content in tuple(history)[-HISTORY_MAX_TURNS * 2 :]:
        body = content.strip()[:HISTORY_MAX_CHARS]
        if not body:
            continue
        # OpenAI 규약이 허용하는 역할로 접는다(system 등은 사용자 발화로 취급).
        speaker = "assistant" if role == "assistant" else "user"
        turns.append((speaker, ensure_masked(body, extra_names=extra_names).masked_text))
    return tuple(turns)


def _clarify_question(calls: Sequence[ToolCallRequest]) -> str | None:
    """ask_clarification 호출이면 되물을 문장, 아니면 None.

    ToolResult에 판별 필드를 더하지 않고 **도구 이름 상수**로 판별한다 — 나머지 도구의
    결과 계약을 건드리지 않는 쪽이 diff가 작고, "이 도구만 실행 경로가 다르다"는 사실도
    한 곳(오케스트레이터)에만 남는다. 인자는 다른 도구와 동일하게 Pydantic으로 검증하며,
    검증 실패(빈 항목·문장 통째 투입 등)면 되묻기를 포기한다(None → 일반 도구 경로로
    계속) — 빈 문장으로 되묻느니 낫다.

    문장은 모델이 아니라 build_clarification이 만든다(H18-3: 8B가 원 질문을 복사했다).
    """
    for call in calls:
        if call.name != CLARIFY_TOOL_NAME:
            continue
        try:
            args = ClarificationArgs.model_validate_json(call.arguments or "{}")
        except ValidationError:
            return None
        return build_clarification(args.missing, args.context)
    return None


def _args_key(arguments: str) -> str:
    """도구 인자 정규화 키 — 키 순서·공백이 달라도 같은 호출이면 같은 문자열.

    JSON이 아니면(모델이 깨진 인자를 낼 수 있다) 원문 그대로 키로 쓴다. 깨진 인자를 반복해도
    결과는 똑같이 검증 실패라 재실행할 이유가 없다.
    """
    try:
        parsed = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return arguments
    return json.dumps(parsed, sort_keys=True, ensure_ascii=False)


def _no_evidence_gate(parts: Sequence[str]) -> str:
    """스트림 앞부분으로 NO_EVIDENCE 마커 여부를 판정 — `hold` | `fallback` | `flush`.

    아직 마커일 수 있는 동안(마커의 접두사인 동안)은 hold로 토큰을 붙잡는다. 마커로 시작하면
    폴백 확정이라 한 글자도 내보내지 않고, 마커와 갈라지면 flush로 그때까지 모은 것을 흘린다.
    """
    head = "".join(parts).lstrip()
    if head.startswith(NO_EVIDENCE_MARKER):
        return "fallback"
    if NO_EVIDENCE_MARKER.startswith(head):  # 빈 문자열 포함 — 판정 유보
        return "hold"
    return "flush"


def _sum_usage(turns: Sequence[ChatUsage]) -> ChatUsage | None:
    """질의 1건의 turn별 usage 합계(도구 결정 turn + 최종 답변 turn).

    LLM 호출이 없었으면 None(0 토큰과 구분 — 캐시 히트만 0이다).
    estimated는 OR 집계 — 한 turn이라도 추정이면 합계도 추정치다(원가 신뢰도 표기용).
    """
    if not turns:
        return None
    return ChatUsage(
        input_tokens=sum(u.input_tokens for u in turns),
        output_tokens=sum(u.output_tokens for u in turns),
        estimated=any(u.estimated for u in turns),
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
    seen_cards: set[tuple[str, str]],
    extra_names: Sequence[str],
) -> str:
    """도구 결과를 근거에 누적하고, LLM에 되먹일 텍스트를 마스킹해 반환(규칙 2).

    마스킹 불가한 근거는 사용하지 않는다(evidence에도 추가하지 않음) — 최종 답변 rebuild가
    2차 게이트지만, 루프 turn에도 원문 PII가 새면 안 되므로 여기서 fail-closed.

    문서 청크·도구 카드 **양쪽 모두** 중복이면 근거에 쌓지 않고 안내만 되돌린다 —
    같은 내용을 컨텍스트에 다시 실으면 토큰만 태운다(규칙 7).
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
        # 카드 중복 제거 키 = (source_kind, quote). 8B는 같은 도구를 2~3회 반복 호출한다
        # (측정 로그: search_similar_inquiries 3연속) — 걸러내지 않으면 같은 카드가 출처로
        # 2~3개 뜬다. 인자를 키로 쓰지 않는 이유: 인자가 달라도 같은 결과가 나오는 호출이
        # 실재하고(예: period 생략 vs 최신월 명시) 사용자에겐 같은 근거다. 반대로 인자가
        # 달라 결과가 다르면 quote가 달라 별개 출처로 남는다(과도한 병합 방지).
        # title은 quote와 함께 움직이므로 키에 더해도 판별력이 늘지 않는다.
        key = (result.card.source_kind, result.card.quote)
        if key in seen_cards:
            return "이미 조회한 결과입니다."
        masked, ok = _safe_mask(result.llm_text(), extra_names)
        if not ok:
            return "(민감정보 포함으로 생략됨)"
        seen_cards.add(key)
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
    question: str,
    chunks: Sequence[RetrievedChunk],
    cards: Sequence[ToolCard],
    history: Sequence[tuple[str, str]] = (),
) -> str:
    parts: list[str] = []
    if history:
        # 최종 답변 turn은 user 메시지 하나로 조립되므로, 히스토리도 블록으로 넣는다
        # (후속 질문의 지시어 — "그럼 언제까지야?" — 를 풀려면 이 turn에도 맥락이 필요).
        lines = "\n".join(
            f"{'AI' if role == 'assistant' else '사용자'}: {content}" for role, content in history
        )
        parts.append("[이전 대화]\n" + lines)
    if chunks:
        parts.append("[문서 근거]\n" + build_context_block(chunks))
    if cards:
        lines = "\n".join(f"- {c.title}: {c.quote}" for c in cards)
        parts.append("[확정 데이터·도구 결과]\n" + lines)
    parts.append(f"[질문]\n{question}")
    return "\n\n".join(parts)


def _tool_citations(cards: Sequence[ToolCard], *, start: int) -> tuple[ToolCitation, ...]:
    return tuple(
        ToolCitation(
            ref=start + i,
            title=c.title,
            quote=c.quote,
            source_kind=c.source_kind,
            # 도구가 확정한 값을 그대로 통과시킨다 — 재가공하면 화면 숫자가 갈라진다(규칙 5·8).
            data=c.data,
        )
        for i, c in enumerate(cards)
    )


async def _excerpt_fallback(
    evidence: Sequence[RetrievedChunk],
    cards: Sequence[ToolCard],
    *,
    tool_path: Sequence[str] = (),
    usage: ChatUsage | None = None,
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
        usage=usage,  # 스트리밍 실패 전까지 쓴 결정 turn 토큰(비용 누락 방지)
        fallback_reason=FALLBACK_LLM_UNAVAILABLE,
        citations=doc_citations,
        tool_citations=tool_citations,
        tool_path=tuple(tool_path),
        suggestions=suggest_next_actions(tool_path, status="fallback"),
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
