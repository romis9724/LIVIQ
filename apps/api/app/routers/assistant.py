"""assistant — 질의 SSE 스트리밍 + 대화·인용 영속화 (docs/01 §5.2, 09 §1.1).

SSE 이벤트 4종: token(증분) · citation(근거 카드) · status(단계) · done(종료·신뢰도).
스트림 종료 전에 messages·citations를 기록하고 done에 message_id를 실어 보낸다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ai_core.backend_config import AiTuning
from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient
from ai_core.orchestrator import (
    HISTORY_MAX_TURNS,
    CitationEvent,
    DoneEvent,
    StatusEvent,
    TokenEvent,
    ToolCitationEvent,
    answer_question,
)
from ai_core.rag.prompt import ANSWER_SYSTEM_PROMPT, FACILITY_ANSWER_SYSTEM_PROMPT
from ai_core.rag.retrieval import PgVectorRetriever
from ai_core.tools import ToolContext, ToolDeps, default_registry
from app import answer_cache
from app.ai_backend import backend_id
from app.deps import (
    RequestContext,
    get_context,
    get_graph,
    get_llm,
    get_tenant_session,
    get_tuning,
    require_roles,
)
from app.rate_limit import enforce_rate_limit
from app.schemas.assistant import (
    AnswerStatus,
    AskRequest,
    CitationData,
    DoneData,
    StatusData,
    StatusStage,
    TokenData,
)
from app.session import get_redis
from liviq_db.models import Citation, Conversation, Message

_REGISTRY = default_registry()
# 한 턴 = user+assistant 두 메시지 — 자르기·마스킹 상한 자체는 ai-core가 단일 출처(H18-1).
_HISTORY_MESSAGE_LIMIT = HISTORY_MAX_TURNS * 2
# 시설 AI 도우미 접근 역할(docs/04 §4) — 시설은 소장 전용(H7-2에서 FACILITY 제거).
_FACILITY_ASSISTANT_ROLES = ("MANAGER",)

router = APIRouter(prefix="/assistant", tags=["assistant"])
# 시설 도우미는 /admin/facilities 표면에 속한다 — 스트림·영속은 아래 공유 헬퍼 재사용.
facility_router = APIRouter(prefix="/admin/facilities", tags=["facilities"])


@router.post("/ask", dependencies=[Depends(enforce_rate_limit)])
async def ask(
    body: AskRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    llm: Annotated[LlmClient, Depends(get_llm)],
    graph: Annotated[GraphClient | None, Depends(get_graph)],
    redis: Annotated[Redis, Depends(get_redis)],
    tuning: Annotated[AiTuning, Depends(get_tuning)],
) -> EventSourceResponse:
    return await _assistant_response(
        body, ctx, session, llm, graph, redis, tuning, channel="resident"
    )


@facility_router.post("/assistant", dependencies=[Depends(enforce_rate_limit)])
async def facility_assistant(
    body: AskRequest,
    ctx: Annotated[RequestContext, Depends(require_roles(*_FACILITY_ASSISTANT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    llm: Annotated[LlmClient, Depends(get_llm)],
    graph: Annotated[GraphClient | None, Depends(get_graph)],
    redis: Annotated[Redis, Depends(get_redis)],
    tuning: Annotated[AiTuning, Depends(get_tuning)],
) -> EventSourceResponse:
    """시설 AI 도우미(FR-FAC-02) — 유사 장애·이력 근거로 가능 원인 후보 제시(단정 금지).

    answer_question 재사용(시설 프롬프트만 주입) — 레지스트리·마스킹·스텝 상한·폴백·영속은
    /assistant/ask와 공유. ctx.roles(MANAGER)가 시설 도구 노출을 결정한다.
    """
    return await _assistant_response(
        body,
        ctx,
        session,
        llm,
        graph,
        redis,
        tuning,
        channel="admin",
        answer_prompt=FACILITY_ANSWER_SYSTEM_PROMPT,
    )


async def _assistant_response(
    body: AskRequest,
    ctx: RequestContext,
    session: AsyncSession,
    llm: LlmClient,
    graph: GraphClient | None,
    redis: Redis,
    tuning: AiTuning,
    *,
    channel: str,
    answer_prompt: str = ANSWER_SYSTEM_PROMPT,
) -> EventSourceResponse:
    """대화 적재 + (캐시 히트 재생 | 도구 에이전트 스트림) + 영속화 — 두 엔드포인트 공유."""
    conversation = await _load_or_create_conversation(session, ctx, body.conversation_id, channel)
    # 히스토리는 이번 질문을 적재하기 **전에** 읽는다 — 방금 넣은 user 메시지가 섞이면
    # 같은 질문이 두 번 실려 나간다.
    history = (
        await _load_history(session, ctx, conversation.id)
        if body.conversation_id is not None
        else _History()
    )
    session.add(
        Message(
            tenant_id=ctx.tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=body.question,
        )
    )
    await session.flush()
    # 검색 상한·도구 신뢰도·캐시 TTL은 관리자 설정의 해석값(H15-3, NULL=코드/env 기본값).
    deps = ToolDeps(
        session=session,
        llm=llm,
        retriever=PgVectorRetriever(session, default_top_k=tuning.retrieval_top_k),
        graph=graph,
    )
    tool_ctx = ToolContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        roles=ctx.roles,
        visibilities=ctx.visibilities,
    )
    # 캐시 키의 백엔드 세그먼트 — 런타임에 바뀐 백엔드의 답변이 섞이지 않게(H15-1).
    backend = backend_id(llm.settings)

    async def stream() -> AsyncIterator[dict[str, str]]:
        # 캐시 히트면 LLM 호출 0으로 재생, 미스면 정상 스트림(완료 후 저장).
        # 히스토리가 있으면 **캐시를 우회한다**(ADR-0025 §3) — 같은 질문도 맥락에 따라 답이
        # 달라지고, 캐시 키에 히스토리를 넣으면 적중률이 0에 수렴한다. 첫 턴만 캐시한다.
        cached = (
            None
            if history.turns
            else await answer_cache.lookup(
                redis,
                ctx=tool_ctx,
                question=body.question,
                backend=backend,
                ttl_override=tuning.answer_cache_ttl_s,
            )
        )
        if cached is not None:
            events: AsyncIterator[object] = answer_cache.replay(cached, tenant_id=ctx.tenant_id)
        else:
            events = answer_question(
                body.question,
                registry=_REGISTRY,
                deps=deps,
                ctx=tool_ctx,
                history=history.turns,
                # 직전 턴이 되묻기였으면 되묻기 도구를 감춘다 — 연속 되묻기 금지(ADR-0025 §4).
                allow_clarify=not history.last_was_clarify,
                answer_prompt=answer_prompt,
                tool_confidence=tuning.tool_confidence,
            )
        async for event in events:
            match event:
                case StatusEvent(stage=stage, tool=tool):
                    data = StatusData(stage=cast(StatusStage, stage), tool=tool).model_dump_json()
                    yield {"event": "status", "data": data}
                case TokenEvent(text=text):
                    yield {"event": "token", "data": TokenData(text=text).model_dump_json()}
                case CitationEvent(citation=c):
                    yield {
                        "event": "citation",
                        "data": CitationData(
                            ref=c.ref,
                            document_id=c.document_id,
                            document_title=c.document_title,
                            quote=c.quote,
                            page=c.page,
                            clause=c.clause,
                        ).model_dump_json(),
                    }
                case ToolCitationEvent(citation=tc):
                    # 도구 결과 인용 — document_id 없음(H2-5 완화 재사용), title로 표기.
                    # data는 도구가 확정한 값 그대로 통과(LLM 미경유, ADR-0025 §6).
                    yield {
                        "event": "citation",
                        "data": CitationData(
                            ref=tc.ref,
                            document_id=None,
                            document_title=tc.title,
                            quote=tc.quote,
                            data=tc.data,
                        ).model_dump_json(),
                    }
                case DoneEvent() as done:
                    message_id = await _persist_assistant_message(
                        session, ctx, conversation.id, done
                    )
                    # 정상 경로 + 첫 턴만 저장(재생은 재저장 금지, 맥락 의존 답변은 캐시 금지).
                    if cached is None and not history.turns:
                        await answer_cache.store(
                            redis,
                            ctx=tool_ctx,
                            question=body.question,
                            done=done,
                            backend=backend,
                            ttl_override=tuning.answer_cache_ttl_s,
                        )
                    yield {
                        "event": "done",
                        "data": DoneData(
                            message_id=message_id,
                            conversation_id=conversation.id,
                            status=cast(AnswerStatus, done.status),
                            confidence=done.confidence,
                            needs_review=done.needs_review,
                            fallback_reason=done.fallback_reason,
                            tool_path=list(done.tool_path),
                            token_input=done.usage.input_tokens if done.usage else None,
                            token_output=done.usage.output_tokens if done.usage else None,
                            token_estimated=done.usage.estimated if done.usage else False,
                            answer=done.answer or None,
                            suggestions=list(done.suggestions),
                        ).model_dump_json(),
                    }

    return EventSourceResponse(stream())


async def _load_or_create_conversation(
    session: AsyncSession,
    ctx: RequestContext,
    conversation_id: uuid.UUID | None,
    channel: str,
) -> Conversation:
    if conversation_id is not None:
        conversation = await session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == ctx.tenant_id,
                Conversation.user_id == ctx.user_id,  # 소유권 검증(규칙 4)
            )
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="대화 없음")
        return conversation
    conversation = Conversation(tenant_id=ctx.tenant_id, user_id=ctx.user_id, channel=channel)
    session.add(conversation)
    await session.flush()
    return conversation


@dataclass(frozen=True)
class _History:
    """대화 히스토리 + 되묻기 연속 여부 — 조회 1회로 둘 다 얻는다."""

    turns: tuple[tuple[str, str], ...] = ()
    last_was_clarify: bool = False


async def _load_history(
    session: AsyncSession, ctx: RequestContext, conversation_id: uuid.UUID
) -> _History:
    """직전 메시지를 최신순으로 상한만큼 읽어 (오래된 것 → 최신) 순서로 돌려준다.

    소유권은 호출 전 `_load_or_create_conversation`이 검증했고(규칙 4), tenant 조건은
    RLS와 함께 이중 방어(규칙 3). 자르기·마스킹은 ai-core가 한다 — 여기서는 원문만 나른다.
    """
    rows = (
        await session.scalars(
            select(Message)
            .where(
                Message.tenant_id == ctx.tenant_id,
                Message.conversation_id == conversation_id,
            )
            # created_at은 트랜잭션 시각이라 같은 요청의 user/assistant가 동타임스탬프다 —
            # role을 보조 정렬로 넣지 않으면 질문/답변 순서가 뒤집힌다. 최신순 조회에서
            # role 오름차순(assistant < user)이면 뒤집었을 때 user가 앞선다.
            .order_by(Message.created_at.desc(), Message.role.asc())
            .limit(_HISTORY_MESSAGE_LIMIT)
        )
    ).all()
    last_assistant = next((m for m in rows if m.role == "assistant"), None)
    return _History(
        turns=tuple((m.role, m.content) for m in reversed(rows) if m.content),
        last_was_clarify=last_assistant is not None and last_assistant.status == "clarify",
    )


async def _persist_assistant_message(
    session: AsyncSession, ctx: RequestContext, conversation_id: uuid.UUID, done: DoneEvent
) -> uuid.UUID:
    """assistant 메시지 + 검증된 인용 기록. 비용은 usage(추정 포함) 그대로(docs/08 §9).

    token_input/output은 질의 1건의 **전 turn 합계**다(도구 결정 turn 포함 — H15-2 정정).
    이전에는 최종 답변 turn만 기록해 실사용의 3분의 1 수준이었다 → 일일 예산 대조
    (dashboard `_budget_stats`)가 같은 값을 쓰므로 사용량이 커 보이는 것은 의도된 정정이다.
    """
    message = Message(
        tenant_id=ctx.tenant_id,
        conversation_id=conversation_id,
        role="assistant",
        content=done.answer or "",
        intent="ai",
        confidence=done.confidence,
        status=done.status,
        review_status="needs_review" if done.needs_review else None,
        token_input=done.usage.input_tokens if done.usage else None,
        token_output=done.usage.output_tokens if done.usage else None,
    )
    session.add(message)
    await session.flush()
    for c in done.citations:
        session.add(
            Citation(
                tenant_id=ctx.tenant_id,
                message_id=message.id,
                source_kind="document_chunk",
                document_id=c.document_id,
                chunk_id=c.chunk_id,
                quote=c.quote,
                page=c.page,
                clause=c.clause,
            )
        )
    # 도구 결과 인용 영속(source_kind=tool:*, document_id/chunk_id 없음 — source_ref=title).
    for tc in done.tool_citations:
        session.add(
            Citation(
                tenant_id=ctx.tenant_id,
                message_id=message.id,
                source_kind=tc.source_kind,
                source_ref=tc.title,
                quote=tc.quote,
            )
        )
    await session.flush()
    return message.id
