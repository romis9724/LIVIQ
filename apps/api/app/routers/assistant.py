"""assistant — 질의 SSE 스트리밍 + 대화·인용 영속화 (docs/01 §5.2, 09 §1.1).

SSE 이벤트 4종: token(증분) · citation(근거 카드) · status(단계) · done(종료·신뢰도).
스트림 종료 전에 messages·citations를 기록하고 done에 message_id를 실어 보낸다.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ai_core.backend_config import AiTuning
from ai_core.graph import GraphClient
from ai_core.history import HISTORY_CANDIDATE_TURNS
from ai_core.llm.client import LlmClient
from ai_core.masking import detect_pii
from ai_core.orchestrator import (
    KST,
    CitationEvent,
    DoneEvent,
    StatusEvent,
    TokenEvent,
    ToolCitationEvent,
    answer_question,
)
from ai_core.rag.prompt import (
    ADMIN_AGENT_ASK_UNIT_PROMPT,
    ADMIN_AGENT_SYSTEM_PROMPT,
    ADMIN_ANSWER_SYSTEM_PROMPT,
    AGENT_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
    FACILITY_ANSWER_SYSTEM_PROMPT,
)
from ai_core.rag.retrieval import PgVectorRetriever
from ai_core.tools import ToolContext, ToolDeps, default_registry
from ai_core.tools.floor_plan import RESIDENT_ROLES
from ai_core.tools.floor_plan_parser import parse_query
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
    LatestConversationResponse,
    RestoredMessage,
    StatusData,
    StatusStage,
    TokenData,
)
from app.session import get_redis
from liviq_db.models import Citation, Conversation, Household, Message, User

_REGISTRY = default_registry()
# 한 턴 = user+assistant 두 메시지. 여기는 **후보 풀**만 나른다 — 어느 턴을 실제로 주입할지
# 고르는 것도, 자르기·마스킹 상한도 ai-core가 단일 출처(H18-1, ADR-0027 결정 2).
_HISTORY_MESSAGE_LIMIT = HISTORY_CANDIDATE_TURNS * 2
# 복원 상한 — 프론트 `MAX_STORED_MESSAGES`(session-store.ts)와 같은 값이어야 두 복원 경로의
# 대화 길이가 갈라지지 않는다(ADR-0027 결정 1).
RESTORE_MESSAGE_LIMIT = 40
# 시설 AI 도우미 접근 역할(docs/04 §4) — 시설은 소장 전용(H7-2에서 FACILITY 제거).
_FACILITY_ASSISTANT_ROLES = ("MANAGER",)
# 관리자 홈 AI 비서 접근 역할(ADR-0028) — 소장 전용(STAFF 첫 진입은 /inquiries 그대로).
_ADMIN_ASSISTANT_ROLES = ("MANAGER",)

router = APIRouter(prefix="/assistant", tags=["assistant"])
# 관리자 홈 AI 비서(ADR-0028) — 입주민 ask와 같은 헬퍼, 채널만 admin.
admin_assistant_router = APIRouter(prefix="/admin/assistant", tags=["assistant"])
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


@router.get("/conversations/latest")
async def latest_conversation(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> LatestConversationResponse:
    """본인의 가장 최근 입주민 대화 1건 복원(ADR-0027 결정 1).

    탭 저장소가 비었을 때(새 탭·브라우저 재시작)의 2차 복원 경로다. 대화가 없으면
    빈 응답 — 첫 방문은 오류가 아니다. 소유권(규칙 4) + tenant 이중 방어(규칙 3).
    입주민은 **날짜 제한이 없다** — 어제 하던 문의를 오늘 이어 보는 편이 자연스럽다.
    """
    return await _latest_conversation(session, ctx, channel="resident")


@admin_assistant_router.post("/ask", dependencies=[Depends(enforce_rate_limit)])
async def admin_ask(
    body: AskRequest,
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ASSISTANT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    llm: Annotated[LlmClient, Depends(get_llm)],
    graph: Annotated[GraphClient | None, Depends(get_graph)],
    redis: Annotated[Redis, Depends(get_redis)],
    tuning: Annotated[AiTuning, Depends(get_tuning)],
) -> EventSourceResponse:
    """관리자 홈 AI 비서(ADR-0028 결정 2) — 입주민 ask와 같은 에이전트 경로, channel="admin".

    도구 가시성은 기존 역할 체계 그대로다(MANAGER = summarize_inquiries·get_facilities 등).
    서버 복원은 **당일 한정**으로 제공한다(아래 admin_latest_conversation, ADR-0028 결정 2 개정).
    세대 평면도 설비 위치 질의만 프롬프트·도구 가시성을 갈아끼운다(H20-16, `_admin_overrides`).
    """
    answer_prompt, agent_prompt, exclude_tools = _admin_overrides(body.question)
    return await _assistant_response(
        body,
        ctx,
        session,
        llm,
        graph,
        redis,
        tuning,
        channel="admin",
        answer_prompt=answer_prompt,
        agent_prompt=agent_prompt,
        exclude_tools=exclude_tools,
    )


# 위치를 묻는 말(H20-16 게이트의 두 번째 조건). 어휘를 좁게 잡는다 — "있나요"까지 넣으면
# "어떤 설비가 있는지"(설비 현황 질의, 골든셋 시설 클래스)가 전부 걸린다.
_LOCATION_WORDS: tuple[str, ...] = ("어디", "위치", "찾아", "찾을", "찾고")


def _is_home_device_location_query(question: str) -> bool:
    """세대 평면도 설비의 **위치**를 묻는 질문인가 — 요소 어휘(parse_query) ∧ 위치 어휘.

    두 조건을 함께 요구하는 이유: 요소 어휘만 보면 "소방 설비 현황"이 그룹 동의어(소화기·
    화재감지기)에 걸려 시설 현황 질의까지 삼킨다(골든셋 V2-QA-0193 계열). 위치 어휘만
    보면 "승강기는 어디에 있나요?" 같은 공용 설비 질의가 걸린다(사용자 지시상 제외).
    """
    return bool(parse_query(question).elements) and any(w in question for w in _LOCATION_WORDS)


def _admin_overrides(question: str) -> tuple[str, str, tuple[str, ...]]:
    """관리자 질의별 (답변 프롬프트, 결정 프롬프트, 감출 도구) — H20-16.

    갈림목 판정은 **코드가 한다**. 8B는 프롬프트 조건문으로 이 분기를 지키지 못했다
    (로컬 실측: 동·호수가 명시된 "402동 201호 두꺼비집"에도 3/3 되물었고, 공용 설비 위치
    질문 "승강기는 어디에 있나요?"에도 되물었다). 신호는 전부 기존 순수 함수 재사용이다:
    평면도 요소 어휘는 `parse_query`(콘센트·분전함·두꺼비집…), 동·호수는 마스킹 패턴.
    질문은 이 판정 때문에 어디로도 나가지 않는다(로컬 정규식, 규칙 2와 무관).

    - 평면도 설비 **위치** 질의가 아니면: 기본 프롬프트 그대로(다른 관리자 질의는 무영향).
    - 위치 질의 + 동·호수 없음: 되묻기 예외를 줘서 동/호수를 되묻는다(사용자 지시).
    - 위치 질의 + 동·호수 있음: 되묻지 않고, **단지 공용 설비 목록 도구를 감춘다** —
      특정 세대 질문에 단지 37개 설비 현황 카드가 뜨는 것이 사용자 신고 내용이다.
      세대 안 설비를 실제로 조회하는 관리자 도구는 H20-17이 만든다. 그때까지는 답변
      프롬프트 규칙 7의 평면도 안내나 폴백으로 끝난다(지어내지 않는다).
    """
    if not _is_home_device_location_query(question):
        return ANSWER_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT, ()
    if "UNIT" in detect_pii(question):
        return ADMIN_ANSWER_SYSTEM_PROMPT, ADMIN_AGENT_SYSTEM_PROMPT, ("get_facilities",)
    return ADMIN_ANSWER_SYSTEM_PROMPT, ADMIN_AGENT_ASK_UNIT_PROMPT, ()


@admin_assistant_router.get("/conversations/latest")
async def admin_latest_conversation(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ASSISTANT_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> LatestConversationResponse:
    """본인의 **당일(KST)** 관리자 대화 1건 복원(ADR-0028 결정 2 개정, H20-3).

    "이전 대화를 기억하되 일자가 달라지면 새 대화"가 요구다. 마지막 메시지가 어제 것이면
    빈 응답을 주고, 그러면 프론트는 새 대화 + 진입 브리핑으로 시작한다(같은 날 재로그인·새
    탭은 대화가 이어져 브리핑이 뜨지 않는다). 소유권(규칙 4) + tenant 이중 방어(규칙 3).
    시설 도우미(`/admin/facilities/assistant`)도 channel="admin"이라 그 대화가 복원될 수
    있다 — 같은 사용자의 같은 채널이라 격리 문제는 없고, 채널을 쪼개는 값은 아직 없다.
    """
    return await _latest_conversation(session, ctx, channel="admin", today_only=True)


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
    agent_prompt: str = AGENT_SYSTEM_PROMPT,
    exclude_tools: Sequence[str] = (),
) -> EventSourceResponse:
    """대화 적재 + (캐시 히트 재생 | 도구 에이전트 스트림) + 영속화 — 세 엔드포인트 공유."""
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
        building_id=await _building_id(session, ctx),
    )
    # 캐시 키의 백엔드 세그먼트 — 런타임에 바뀐 백엔드의 답변이 섞이지 않게(H15-1).
    backend = backend_id(llm.settings)
    # 답변 캐시는 입주민 채널만 참여한다(읽기·쓰기 모두 — ADR-0028 결정 2).
    # ① 관리자 답변의 근거는 민원 현황·시설 이력 같은 운영 데이터라 수시로 변한다 — 재생은
    #    아침 답을 저녁까지 내보내는 것이다. ② 캐시 키에 채널 세그먼트가 없어서, 도구 가시성이
    #    다른 채널의 답변이 서로 재생될 수 있다(H19-1 동 세그먼트 함정과 같은 계열).
    # 키를 늘리는 대신 우회를 택한다 — 관리자는 소수라 캐시 이득이 없다.
    is_cacheable_channel = channel == "resident"

    async def stream() -> AsyncIterator[dict[str, str]]:
        # 캐시 히트면 LLM 호출 0으로 재생, 미스면 정상 스트림(완료 후 저장).
        # 히스토리가 있으면 **캐시를 우회한다**(ADR-0025 §3) — 같은 질문도 맥락에 따라 답이
        # 달라지고, 캐시 키에 히스토리를 넣으면 적중률이 0에 수렴한다. 첫 턴만 캐시한다.
        cached = (
            None
            if history.turns or not is_cacheable_channel
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
                # 요청이 끄고 들어온 경우(자동 발화 — 관리자 진입 브리핑)도 같이 감춘다.
                allow_clarify=body.allow_clarify and not history.last_was_clarify,
                answer_prompt=answer_prompt,
                agent_prompt=agent_prompt,
                exclude_tools=exclude_tools,
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
                    if is_cacheable_channel and cached is None and not history.turns:
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


async def _latest_conversation(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    channel: str,
    today_only: bool = False,
) -> LatestConversationResponse:
    """본인의 최근 대화 1건 복원 — 채널·당일 필터만 다른 두 엔드포인트의 공유 본체.

    `today_only`면 **마지막 메시지의 KST 날짜가 오늘일 때만** 대화를 준다(H20-3). 판정을
    파이썬에서 하는 이유는 어차피 메시지를 읽어야 해서다 — 쿼리를 하나 더 만들 이유가 없다.
    """
    conversation = await session.scalar(
        select(Conversation)
        .where(
            Conversation.tenant_id == ctx.tenant_id,
            Conversation.user_id == ctx.user_id,
            Conversation.channel == channel,
        )
        .order_by(Conversation.updated_at.desc())
        .limit(1)
    )
    if conversation is None:
        return LatestConversationResponse(conversation_id=None, messages=[])
    rows = (
        await session.scalars(
            select(Message)
            .where(
                Message.tenant_id == ctx.tenant_id,
                Message.conversation_id == conversation.id,
            )
            # _load_history와 같은 이유로 role 보조 정렬 — 같은 요청의 user/assistant는
            # created_at이 동일해서, 이게 없으면 복원 화면에서 답변이 질문보다 위로 온다.
            .order_by(Message.created_at.desc(), Message.role.asc())
            .limit(RESTORE_MESSAGE_LIMIT)
        )
    ).all()
    # rows[0]이 최신 메시지(created_at 내림차순). 메시지가 없는 대화도 어제 것과 같이 취급한다.
    if today_only and not (rows and _is_today_kst(rows[0].created_at)):
        return LatestConversationResponse(conversation_id=None, messages=[])
    return LatestConversationResponse(
        conversation_id=conversation.id,
        messages=[
            RestoredMessage(id=m.id, role=m.role, content=m.content, status=m.status)
            for m in reversed(rows)
            # system 롤·빈 본문은 화면에 그릴 것이 없다(폴백 미저장 답변 등).
            if m.content and m.role in ("user", "assistant")
        ],
    )


def _is_today_kst(moment: datetime.datetime) -> bool:
    """단지 시간대(KST) 기준 오늘인가 — 서버가 UTC로 돌아도 날짜 경계가 어긋나지 않게."""
    return moment.astimezone(KST).date() == datetime.datetime.now(KST).date()


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


async def _building_id(session: AsyncSession, ctx: RequestContext) -> uuid.UUID | None:
    """로그인 사용자의 세대 동(H19-1) — None이면 공지 동 필터 미적용(전 동 검색).

    면제는 **역할로 판정한다 — 세대 배정 여부와 독립**이다(docs/09 §8.22 ③). 관리자·직원은
    업무로 전 동을 묻기 때문이다: 입주민을 겸해 세대가 있는 관리자가 "402동 점검 언제야"에
    자기 동(401동) 답을 받으면 조용히 틀린다. 지금 관리자 계정에 세대가 없는 것은 시더의
    우연일 뿐이라 그 성질에 기대지 않는다.
    RESIDENT 외 역할이 하나라도 있으면 쿼리 없이 면제(요청당 DB 왕복도 1회 준다).
    """
    if set(ctx.roles) - RESIDENT_ROLES:
        return None
    # 여기부터 순수 입주민 — 세대 미배정이면 scalar가 None(역시 필터 미적용).
    # tenant 조건은 RLS와 함께 이중 방어(규칙 3). 요청당 1회.
    return await session.scalar(
        select(Household.building_id)
        .join(User, User.household_id == Household.id)
        .where(
            User.id == ctx.user_id,
            User.tenant_id == ctx.tenant_id,
            Household.tenant_id == ctx.tenant_id,
        )
    )


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
