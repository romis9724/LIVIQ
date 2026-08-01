"""도구호출 에이전트 오케스트레이터 테스트 — fake registry/deps + 스크립트 LLM.

도구 루프(복합 질의·스텝 상한·인자 검증·폴백)를 fake로 검증한다. 실 PG·RLS·규칙8
무변경은 apps/api 통합 테스트가 담당한다(ai-core는 apps.api·liviq_db에 의존하지 않음).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from conftest import FakeSession, row
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from ai_core.masking import MaskingFailedError
from ai_core.orchestrator import (
    FALLBACK_LLM_UNAVAILABLE,
    FALLBACK_MASKING,
    FALLBACK_NO_EVIDENCE,
    MAX_TOOL_STEPS,
    TOOL_ONLY_CONFIDENCE,
    AssistantEvent,
    CitationEvent,
    DoneEvent,
    StatusEvent,
    TokenEvent,
    ToolCitationEvent,
    answer_question,
)
from ai_core.rag.retrieval import RetrievedChunk
from ai_core.tools import ToolContext, ToolDeps, default_registry

TENANT = uuid.uuid4()
USER = uuid.uuid4()
HOUSEHOLD = uuid.uuid4()
CTX = ToolContext(
    tenant_id=TENANT, user_id=USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT")
)


# ── fakes ──────────────────────────────────────────────────────────────


class FakeRetriever:
    def __init__(self, chunks: Sequence[RetrievedChunk]) -> None:
        self._chunks = list(chunks)
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        tenant_id: uuid.UUID,
        visibilities: Sequence[str],
        top_k: int = 8,
        building_id: uuid.UUID | None = None,
    ) -> list[RetrievedChunk]:
        self.calls.append({"tenant_id": tenant_id})
        return list(self._chunks)


def _chunk(score: float = 0.85) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="관리규약",
        content="지하주차장은 24시간 개방한다.",
        heading=None,
        page=1,
        clause="제3조",
        score=score,
    )


def _fee_handler(sql: str, params: dict[str, Any]) -> list[Any]:
    s = sql.lower()
    if "from users" in s:
        return [row(household_id=HOUSEHOLD, approved_at=datetime(2020, 1, 1, tzinfo=UTC))]
    if "order by period desc" in s:
        return [row(period="2026-06")]
    if "from fees" in s:
        if params.get("period") == "2026-06":
            return [row(breakdown={"일반관리비": 50000, "청소비": 20000}, total_amount=100000)]
        return []
    return []


def _deps(retriever: FakeRetriever, llm: LlmClient) -> ToolDeps:
    return ToolDeps(
        session=cast(AsyncSession, FakeSession(_fee_handler)),
        llm=llm,
        retriever=cast(Any, retriever),
        graph=None,
    )


def _tc(name: str, args: object) -> dict[str, object]:
    arguments = args if isinstance(args, str) else json.dumps(args)
    return {
        "id": f"c-{name}",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _decision(
    *,
    content: str = "",
    tool_calls: list[dict[str, object]] | None = None,
    usage: tuple[int, int] | None = None,
) -> dict[str, Any]:
    message: dict[str, object] = {"content": content or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    if usage is not None:
        # 프로바이더 실측 usage(estimated=False 경로) — 결정 turn 합산 검증용.
        return {
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": usage[0], "completion_tokens": usage[1]},
        }
    return {"choices": [{"message": message}]}


def _agent_llm(
    settings: AiCoreSettings,
    decide: Callable[[list[dict[str, Any]]], dict[str, Any] | str],
    *,
    answer: str | None = "[1] 답변입니다.",
    answer_deltas: Sequence[str] | None = None,
    embed_ok: bool = True,
) -> LlmClient:
    dims = settings.embedding_dimensions

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            if not embed_ok:
                return httpx.Response(503)
            texts = body["input"]
            data = [{"index": i, "embedding": [0.05] * dims} for i in range(len(texts))]
            return httpx.Response(200, json={"data": data})
        if body.get("stream"):
            if answer is None:
                return httpx.Response(503)
            # answer_deltas가 있으면 여러 청크로 쪼개 보낸다(마커 판정이 청크 경계를 넘는 경우).
            deltas = list(answer_deltas) if answer_deltas is not None else [answer]
            sse = "\n\n".join(
                [
                    *(
                        f"data: {json.dumps({'choices': [{'delta': {'content': d}}]})}"
                        for d in deltas
                    ),
                    "data: [DONE]",
                    "",
                ]
            )
            return httpx.Response(200, content=sse.encode())
        result = decide(body["messages"])
        if result == "503":
            return httpx.Response(503)
        return httpx.Response(200, json=result)

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


def _calls_then_stop(*calls: dict[str, object]) -> Callable[[list[dict[str, Any]]], dict[str, Any]]:
    """첫 결정 turn엔 지정 도구 호출, 도구 결과가 대화에 들어오면 도구 호출 중단."""

    def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
        if any(m.get("role") == "tool" for m in messages):
            return _decision(content="")
        return _decision(tool_calls=list(calls))

    return decide


async def _run(
    llm: LlmClient,
    retriever: FakeRetriever,
    *,
    ctx: ToolContext = CTX,
    tool_confidence: float = TOOL_ONLY_CONFIDENCE,
) -> list[AssistantEvent]:
    return [
        event
        async for event in answer_question(
            "주차장 언제 열어요?",
            registry=default_registry(),
            deps=_deps(retriever, llm),
            ctx=ctx,
            tool_confidence=tool_confidence,
        )
    ]


def _done(events: list[AssistantEvent]) -> DoneEvent:
    assert isinstance(events[-1], DoneEvent)
    return events[-1]


# ── 테스트 ─────────────────────────────────────────────────────────────


async def test_composite_query_combines_two_tools_with_tool_citation(
    settings: AiCoreSettings,
) -> None:
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("search_documents", {"query": "주차"}), _tc("get_fees", {}))
    )
    events = await _run(llm, retriever)
    done = _done(events)
    assert done.status == "answered"
    assert done.citations and done.citations[0].ref == 1  # 문서 인용
    assert done.tool_citations and done.tool_citations[0].source_kind == "tool:get_fees"
    assert any(isinstance(e, CitationEvent) for e in events)
    assert any(isinstance(e, ToolCitationEvent) for e in events)


async def test_step_limit_forces_termination(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    # 항상 도구 호출만 반환 → 상한 도달 시 강제 종료.
    llm = _agent_llm(
        settings, lambda messages: _decision(tool_calls=[_tc("search_documents", {"query": "x"})])
    )
    events = await _run(llm, retriever)
    assert isinstance(events[-1], DoneEvent)
    # 도구 실행 횟수(=검색 호출)는 상한 이하.
    assert len(retriever.calls) <= MAX_TOOL_STEPS


async def test_invalid_tool_args_do_not_crash(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    # get_fees에 깨진 JSON, search_documents는 정상 → 크래시 없이 문서 근거로 답변.
    llm = _agent_llm(
        settings,
        _calls_then_stop(_tc("get_fees", "{not-json"), _tc("search_documents", {"query": "주차"})),
    )
    done = _done(await _run(llm, retriever))
    assert done.status == "answered"
    assert done.citations  # 문서 근거로 정상 응답


async def test_tool_only_answer_uses_fixed_confidence(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([])  # 문서 없음
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("get_fees", {})), answer="이번 달 관리비는 100,000원입니다."
    )
    done = _done(await _run(llm, retriever))
    assert done.status == "answered"
    assert not done.citations  # 문서 인용 없음
    assert done.tool_citations[0].source_kind == "tool:get_fees"
    assert done.confidence == TOOL_ONLY_CONFIDENCE
    assert done.needs_review is False


async def test_tool_only_confidence_is_configurable(settings: AiCoreSettings) -> None:
    """도구 신뢰도는 관리자 노브(H15-3) — 주입값이 done.confidence로 그대로 나온다."""
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("get_fees", {})), answer="이번 달 관리비는 100,000원입니다."
    )
    done = _done(await _run(llm, FakeRetriever([]), tool_confidence=0.42))
    assert done.confidence == 0.42


async def test_simple_doc_query_regression(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(
        settings,
        _calls_then_stop(_tc("search_documents", {"query": "주차"})),
        answer="24시간 개방 [1].",
    )
    done = _done(await _run(llm, retriever))
    assert done.status == "answered"
    assert done.citations[0].ref == 1
    assert done.usage is not None and done.usage.estimated


async def test_usage_sums_tool_decision_turns_and_final_turn(settings: AiCoreSettings) -> None:
    """done.usage = 도구 결정 turn 합 + 최종 답변 turn(H15-2).

    최종 답변 turn만 세면 원가가 하한으로 나온다(도구 결과가 다음 결정 turn에 재전송되므로
    누락분이 더 크다). 결정 turn usage만 바꾼 두 번의 실행 차이 = 결정 turn 토큰이어야 한다.
    """

    def decide_with(usage: tuple[int, int]) -> Callable[[list[dict[str, Any]]], dict[str, Any]]:
        def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
            if any(m.get("role") == "tool" for m in messages):
                return _decision(content="", usage=usage)  # 2번째 결정 turn(도구 호출 중단)
            return _decision(tool_calls=[_tc("search_documents", {"query": "주차"})], usage=usage)

        return decide

    counted = _done(
        await _run(_agent_llm(settings, decide_with((1000, 10))), FakeRetriever([_chunk()]))
    )
    baseline = _done(
        await _run(_agent_llm(settings, decide_with((0, 0))), FakeRetriever([_chunk()]))
    )
    assert counted.status == "answered" and baseline.status == "answered"
    assert counted.usage is not None and baseline.usage is not None
    # 결정 turn 2회 × (1000, 10) 만큼만 커진다 — 최종 답변 turn 추정치는 두 실행이 동일.
    assert counted.usage.input_tokens - baseline.usage.input_tokens == 2000
    assert counted.usage.output_tokens - baseline.usage.output_tokens == 20
    assert baseline.usage.input_tokens > 0  # 최종 답변 turn도 여전히 포함
    # 최종 답변 turn은 스트리밍이라 프로바이더 usage가 없다 → 합계는 추정치 표기.
    assert counted.usage.estimated is True


async def test_fallback_usage_keeps_tool_decision_tokens(settings: AiCoreSettings) -> None:
    """근거 0 폴백도 이미 쓴 결정 turn 토큰을 실어야 한다(비용 누락 방지)."""
    llm = _agent_llm(
        settings,
        lambda messages: (
            _decision(content="", usage=(700, 7))
            if any(m.get("role") == "tool" for m in messages)
            else _decision(tool_calls=[_tc("search_documents", {"query": "x"})], usage=(700, 7))
        ),
    )
    done = _done(await _run(llm, FakeRetriever([])))  # 문서 없음 → 근거 0 폴백
    assert done.status == "fallback"
    assert done.usage is not None
    assert (done.usage.input_tokens, done.usage.output_tokens) == (1400, 14)
    assert done.usage.estimated is False  # 프로바이더 실측만(최종 답변 turn 없음)


async def test_done_carries_tool_path_in_call_order(settings: AiCoreSettings) -> None:
    """DoneEvent.tool_path에 호출한 도구 이름이 순서대로 담긴다(H3-4 관측·회귀용)."""
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("search_documents", {"query": "주차"}), _tc("get_fees", {}))
    )
    done = _done(await _run(llm, retriever))
    assert done.tool_path == ("search_documents", "get_fees")


async def test_fallback_carries_tool_path(settings: AiCoreSettings) -> None:
    """근거 0 폴백에도 tool_path가 남는다(스텝 상한 관측 — readonly-02)."""
    retriever = FakeRetriever([])  # 문서 없음
    # 도구는 호출했으나 근거를 못 모아 폴백.
    llm = _agent_llm(settings, _calls_then_stop(_tc("search_documents", {"query": "x"})))
    done = _done(await _run(llm, retriever))
    assert done.status == "fallback"
    assert done.tool_path == ("search_documents",)


async def test_answer_prompt_override_reaches_final_turn(settings: AiCoreSettings) -> None:
    """answer_prompt 주입 시 최종 답변(스트림) turn의 system 메시지가 교체된다(시설 도우미 배선)."""
    retriever = FakeRetriever([_chunk()])
    stream_systems: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            data = [{"index": 0, "embedding": [0.05] * settings.embedding_dimensions}]
            return httpx.Response(200, json={"data": data})
        if body.get("stream"):
            stream_systems.extend(
                str(m["content"]) for m in body["messages"] if m.get("role") == "system"
            )
            chunk = {"choices": [{"delta": {"content": "24시간 개방 [1]."}}]}
            sse = "\n\n".join([f"data: {json.dumps(chunk)}", "data: [DONE]", ""])
            return httpx.Response(200, content=sse.encode())
        # 결정 turn: tool 결과가 있으면 중단, 아니면 문서 검색 호출.
        if any(m.get("role") == "tool" for m in body["messages"]):
            return httpx.Response(200, json=_decision(content=""))
        return httpx.Response(
            200, json=_decision(tool_calls=[_tc("search_documents", {"query": "주차"})])
        )

    llm = LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)
    events = [
        event
        async for event in answer_question(
            "주차장?",
            registry=default_registry(),
            deps=_deps(retriever, llm),
            ctx=CTX,
            answer_prompt="시설전용테스트프롬프트",
        )
    ]
    assert isinstance(events[-1], DoneEvent)
    assert any("시설전용테스트프롬프트" in s for s in stream_systems)


async def test_no_tool_calls_falls_back_no_evidence(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    # LLM이 도구 없이 즉답 → 근거 0 → 폴백(지어내기 금지).
    llm = _agent_llm(settings, lambda messages: _decision(content="안녕하세요"))
    events = await _run(llm, retriever)
    done = _done(events)
    assert done.fallback_reason == FALLBACK_NO_EVIDENCE
    assert not any(isinstance(e, TokenEvent) for e in events)


# ── 계획 turn (ADR-0025 §2) ────────────────────────────────────────────


async def test_plan_turn_is_kept_and_loop_continues_to_tool_call(
    settings: AiCoreSettings,
) -> None:
    """content만 있는 무-도구 turn = 계획. 대화에 남기고 다음 turn에서 도구를 부른다."""
    retriever = FakeRetriever([_chunk()])
    plan = "먼저 관리규약에서 주차장 개방 시간을 찾겠습니다."
    seen_plan_in_next_turn = False

    def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal seen_plan_in_next_turn
        if any(m.get("role") == "tool" for m in messages):
            return _decision(content="")  # 근거 확보 → 종료
        if any(m.get("role") == "assistant" and m.get("content") == plan for m in messages):
            seen_plan_in_next_turn = True
            return _decision(tool_calls=[_tc("search_documents", {"query": "주차"})])
        return _decision(content=plan)  # 1턴째: 계획만

    done = _done(await _run(_agent_llm(settings, decide), retriever))
    assert seen_plan_in_next_turn  # 계획이 다음 turn 컨텍스트에 실렸다
    assert done.status == "answered"
    assert done.tool_path == ("search_documents",)


async def test_second_toolless_turn_terminates_loop(settings: AiCoreSettings) -> None:
    """계획은 1회 한정 — 계속 계획만 내놓는 모델도 2번째 무-도구 turn에서 끝난다.

    무한 루프(=스텝 상한까지 빈 turn) 방지선. 상한을 올려도 결정 turn은 2회여야 한다.
    """
    retriever = FakeRetriever([_chunk()])
    turns = 0

    def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal turns
        turns += 1
        return _decision(content="계획만 반복합니다.")

    done = _done(await _run(_agent_llm(settings, decide), retriever))
    assert turns == 2  # 계획 1 + 종료 판정 1 (MAX_TOOL_STEPS까지 돌지 않는다)
    assert turns < MAX_TOOL_STEPS
    assert done.fallback_reason == FALLBACK_NO_EVIDENCE  # 근거 0 → 지어내지 않음


async def test_empty_toolless_turn_terminates_immediately(settings: AiCoreSettings) -> None:
    """content도 tool_calls도 없으면 계획이 아니다 — 기존대로 즉시 종료(회귀)."""
    retriever = FakeRetriever([_chunk()])
    turns = 0

    def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal turns
        turns += 1
        return _decision(content="")

    done = _done(await _run(_agent_llm(settings, decide), retriever))
    assert turns == 1
    assert done.fallback_reason == FALLBACK_NO_EVIDENCE


async def test_tool_loop_without_plan_is_unchanged(settings: AiCoreSettings) -> None:
    """계획 없이 바로 도구를 부르는 기존 경로는 결정 turn 2회 그대로(회귀)."""
    retriever = FakeRetriever([_chunk()])
    turns = 0

    def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
        nonlocal turns
        turns += 1
        if any(m.get("role") == "tool" for m in messages):
            return _decision(content="")
        return _decision(tool_calls=[_tc("search_documents", {"query": "주차"})])

    done = _done(await _run(_agent_llm(settings, decide), retriever))
    assert turns == 2
    assert done.status == "answered" and done.tool_path == ("search_documents",)


async def test_status_event_names_running_tool(settings: AiCoreSettings) -> None:
    """도구 실행 직전 status(stage=searching, tool=<이름>) — stage 리터럴은 확장하지 않는다."""
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("search_documents", {"query": "주차"}), _tc("get_fees", {}))
    )
    events = await _run(llm, retriever)
    statuses = [e for e in events if isinstance(e, StatusEvent)]
    assert {s.stage for s in statuses} <= {"searching", "generating", "verifying"}
    assert [s.tool for s in statuses if s.tool] == ["search_documents", "get_fees"]
    assert statuses[0].tool is None  # 첫 searching은 도구 미상 — 기존 소비자 하위호환


# ── 구조화 응답 (ADR-0025 §6) ──────────────────────────────────────────


async def test_tool_card_data_never_reaches_the_llm(settings: AiCoreSettings) -> None:
    """`data`는 화면 전용이다 — 8B가 표를 재작성하면 숫자가 틀린다(규칙 5·8).

    LLM으로 나간 요청 본문 전량에서 data 고유 키(`fee_table`·`prev_total`)를 찾지 못해야
    한다. 같은 숫자를 담은 quote는 그대로 가므로 근거는 유지된다.
    """
    sent_bodies: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent_bodies.append(request.content.decode())
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            data = [{"index": 0, "embedding": [0.05] * settings.embedding_dimensions}]
            return httpx.Response(200, json={"data": data})
        if body.get("stream"):
            chunk = {"choices": [{"delta": {"content": "이번 달 관리비는 100,000원입니다."}}]}
            sse = "\n\n".join([f"data: {json.dumps(chunk)}", "data: [DONE]", ""])
            return httpx.Response(200, content=sse.encode())
        if any(m.get("role") == "tool" for m in body["messages"]):
            return httpx.Response(200, json=_decision(content=""))
        return httpx.Response(200, json=_decision(tool_calls=[_tc("get_fees", {})]))

    llm = LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)
    done = _done(await _run(llm, FakeRetriever([])))

    card_data = done.tool_citations[0].data
    assert card_data is not None and card_data["kind"] == "fee_table"
    assert sent_bodies  # 실제로 LLM을 불렀다(공허한 단언 방지)
    for body_text in sent_bodies:
        assert "fee_table" not in body_text
        assert "prev_total" not in body_text
    # quote(=LLM이 본 근거)에는 같은 총액이 살아 있다 — 근거를 뺀 게 아니라 형식만 분리했다.
    assert f"{card_data['total']:,}원" in done.tool_citations[0].quote


async def test_tool_citation_data_is_the_tool_value_unchanged(settings: AiCoreSettings) -> None:
    """화면에 갈 값 == 도구가 낸 값. 오케스트레이터는 재가공하지 않는다."""
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("get_fees", {})), answer="이번 달 관리비는 100,000원입니다."
    )
    events = await _run(llm, FakeRetriever([]))
    done = _done(events)
    emitted = [e for e in events if isinstance(e, ToolCitationEvent)]
    assert emitted[0].citation.data == done.tool_citations[0].data
    assert done.tool_citations[0].data == {
        "kind": "fee_table",
        "period": "2026-06",
        "rows": [{"name": "일반관리비", "amount": 50000}, {"name": "청소비", "amount": 20000}],
        "total": 100000,
        "prev_total": None,  # 전월 데이터 없음(fake handler)
        "diff": None,
    }


async def test_done_carries_context_dependent_suggestions(settings: AiCoreSettings) -> None:
    """제안은 tool_path에 달린다 — 고정 칩이 아니다(ADR-0025 §7)."""
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("get_fees", {})), answer="이번 달 관리비는 100,000원입니다."
    )
    done = _done(await _run(llm, FakeRetriever([])))
    assert done.suggestions == ("지난달과 비교하기",)


async def test_fallback_suggests_the_desk(settings: AiCoreSettings) -> None:
    llm = _agent_llm(settings, lambda messages: _decision(content=""))
    done = _done(await _run(llm, FakeRetriever([])))
    assert done.status == "fallback"
    assert done.suggestions == ("관리사무소에 문의하기",)


async def test_no_evidence_marker_followed_by_answer_streams_nothing(
    settings: AiCoreSettings,
) -> None:
    """모델이 마커 뒤에 답변을 이어 써도 토큰이 새면 안 된다(H15-2 #4 실측 결함).

    스트림은 폴백 검사보다 먼저 흐르므로, 내보낸 토큰은 이미 사용자 화면에 남는다 —
    내부 마커와 미검증 답변이 규칙 1을 우회해 노출됐다.
    """
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(
        settings,
        _calls_then_stop(_tc("search_documents", {"query": "주차"})),
        answer="NO_EVIDENCE\n[1] 그래도 답을 만들어봤습니다.",
    )
    events = await _run(llm, retriever)
    done = _done(events)
    assert done.fallback_reason == FALLBACK_NO_EVIDENCE
    assert not any(isinstance(e, TokenEvent) for e in events)


async def test_marker_prefix_across_chunks_holds_then_streams(settings: AiCoreSettings) -> None:
    """청크가 'NO'처럼 마커 접두사로 시작해도, 갈라지는 순간부터 정상 스트리밍한다."""
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(
        settings,
        _calls_then_stop(_tc("search_documents", {"query": "주차"})),
        answer_deltas=["NO", "쇼음", " 답변 [1]"],
        answer="무시됨",
    )
    events = await _run(llm, retriever)
    done = _done(events)
    assert done.status == "answered"
    streamed = "".join(e.text for e in events if isinstance(e, TokenEvent))
    assert streamed == "NO쇼음 답변 [1]"  # 붙잡았던 앞부분까지 손실 없이 전달


async def test_masking_failure_blocks_llm_call(settings: AiCoreSettings, monkeypatch: Any) -> None:
    def _boom(text: str, *, extra_names: Sequence[str] = ()) -> None:
        raise MaskingFailedError("잔존")

    monkeypatch.setattr("ai_core.orchestrator.ensure_masked", _boom)
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(settings, _calls_then_stop(_tc("search_documents", {"query": "주차"})))
    events = await _run(llm, retriever)
    done = _done(events)
    assert done.fallback_reason == FALLBACK_MASKING
    assert done.needs_review
    assert not any(isinstance(e, TokenEvent) for e in events)


async def test_llm_unavailable_during_decision_falls_back(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    llm = _agent_llm(settings, lambda messages: "503")
    done = _done(await _run(llm, retriever))
    assert done.fallback_reason == FALLBACK_LLM_UNAVAILABLE


async def test_llm_unavailable_during_stream_returns_excerpt(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    # 도구로 근거는 모았으나 최종 스트림 미가용 → 발췌 폴백(출처 유지).
    llm = _agent_llm(
        settings, _calls_then_stop(_tc("search_documents", {"query": "주차"})), answer=None
    )
    done = _done(await _run(llm, retriever))
    assert done.fallback_reason == FALLBACK_LLM_UNAVAILABLE
    assert done.citations  # 발췌 폴백도 출처 유지
