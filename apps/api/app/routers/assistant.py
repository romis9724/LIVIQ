"""assistant — 질의 SSE 스트리밍 + 대화·인용 영속화 (docs/01 §5.2, 09 §1.1).

SSE 이벤트 4종: token(증분) · citation(근거 카드) · status(단계) · done(종료·신뢰도).
스트림 종료 전에 messages·citations를 기록하고 done에 message_id를 실어 보낸다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
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
from ai_core.rag.retrieval import PgVectorRetriever
from ai_core.tools import ToolContext, ToolDeps, default_registry
from app.deps import RequestContext, get_context, get_graph, get_llm, get_tenant_session
from app.schemas.assistant import (
    AnswerStatus,
    AskRequest,
    CitationData,
    DoneData,
    StatusData,
    StatusStage,
    TokenData,
)
from liviq_db.models import Citation, Conversation, Message

_REGISTRY = default_registry()

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.post("/ask")
async def ask(
    body: AskRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    llm: Annotated[LlmClient, Depends(get_llm)],
    graph: Annotated[GraphClient | None, Depends(get_graph)],
) -> EventSourceResponse:
    conversation = await _load_or_create_conversation(session, ctx, body.conversation_id)
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
        async for event in answer_question(
            body.question, registry=_REGISTRY, deps=deps, ctx=tool_ctx
        ):
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
                    yield {
                        "event": "done",
                        "data": DoneData(
                            message_id=message_id,
                            conversation_id=conversation.id,
                            status=cast(AnswerStatus, done.status),
                            confidence=done.confidence,
                            needs_review=done.needs_review,
                            fallback_reason=done.fallback_reason,
                        ).model_dump_json(),
                    }

    return EventSourceResponse(stream())


async def _load_or_create_conversation(
    session: AsyncSession, ctx: RequestContext, conversation_id: uuid.UUID | None
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
    conversation = Conversation(tenant_id=ctx.tenant_id, user_id=ctx.user_id, channel="resident")
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
