"""assistant — 질의 SSE 스트리밍 + 대화·인용 영속화 (docs/01 §5.2, 09 §1.1).

SSE 이벤트 4종: token(증분) · citation(근거 카드) · status(단계) · done(종료·신뢰도).
스트림 종료 전에 messages·citations를 기록하고 done에 message_id를 실어 보낸다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient
from ai_core.orchestrator import (
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
from app.deps import (
    RequestContext,
    get_context,
    get_graph,
    get_llm,
    get_tenant_session,
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
# 시설 AI 도우미 접근 역할(docs/01 §13 시설 표) — 시설 도구도 이 역할에만 노출된다.
_FACILITY_ASSISTANT_ROLES = ("MANAGER", "FACILITY")

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
) -> EventSourceResponse:
    return await _assistant_response(body, ctx, session, llm, graph, redis, channel="resident")


@facility_router.post("/assistant", dependencies=[Depends(enforce_rate_limit)])
async def facility_assistant(
    body: AskRequest,
    ctx: Annotated[RequestContext, Depends(require_roles(*_FACILITY_ASSISTANT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    llm: Annotated[LlmClient, Depends(get_llm)],
    graph: Annotated[GraphClient | None, Depends(get_graph)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> EventSourceResponse:
    """시설 AI 도우미(FR-FAC-02) — 유사 장애·이력 근거로 가능 원인 후보 제시(단정 금지).

    answer_question 재사용(시설 프롬프트만 주입) — 레지스트리·마스킹·스텝 상한·폴백·영속은
    /assistant/ask와 공유. ctx.roles(MANAGER/FACILITY)가 시설 도구 노출을 결정한다.
    """
    return await _assistant_response(
        body,
        ctx,
        session,
        llm,
        graph,
        redis,
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
    *,
    channel: str,
    answer_prompt: str = ANSWER_SYSTEM_PROMPT,
) -> EventSourceResponse:
    """대화 적재 + (캐시 히트 재생 | 도구 에이전트 스트림) + 영속화 — 두 엔드포인트 공유."""
    conversation = await _load_or_create_conversation(session, ctx, body.conversation_id, channel)
    session.add(
        Message(
            tenant_id=ctx.tenant_id,
            conversation_id=conversation.id,
            role="user",
            content=body.question,
        )
    )
    await session.flush()
    deps = ToolDeps(session=session, llm=llm, retriever=PgVectorRetriever(session), graph=graph)
    tool_ctx = ToolContext(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        roles=ctx.roles,
        visibilities=ctx.visibilities,
    )

    async def stream() -> AsyncIterator[dict[str, str]]:
        # 캐시 히트면 LLM 호출 0으로 재생, 미스면 정상 스트림(완료 후 저장).
        cached = await answer_cache.lookup(redis, ctx=tool_ctx, question=body.question)
        if cached is not None:
            events: AsyncIterator[object] = answer_cache.replay(cached, tenant_id=ctx.tenant_id)
        else:
            events = answer_question(
                body.question,
                registry=_REGISTRY,
                deps=deps,
                ctx=tool_ctx,
                answer_prompt=answer_prompt,
            )
        async for event in events:
            match event:
                case StatusEvent(stage=stage):
                    data = StatusData(stage=cast(StatusStage, stage)).model_dump_json()
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
                    yield {
                        "event": "citation",
                        "data": CitationData(
                            ref=tc.ref,
                            document_id=None,
                            document_title=tc.title,
                            quote=tc.quote,
                        ).model_dump_json(),
                    }
                case DoneEvent() as done:
                    message_id = await _persist_assistant_message(
                        session, ctx, conversation.id, done
                    )
                    if cached is None:  # 정상 경로만 저장(재생은 재저장 금지)
                        await answer_cache.store(
                            redis, ctx=tool_ctx, question=body.question, done=done
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


async def _persist_assistant_message(
    session: AsyncSession, ctx: RequestContext, conversation_id: uuid.UUID, done: DoneEvent
) -> uuid.UUID:
    """assistant 메시지 + 검증된 인용 기록. 비용은 usage(추정 포함) 그대로(docs/08 §9)."""
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
