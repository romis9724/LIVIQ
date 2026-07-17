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
    *, content: str = "", tool_calls: list[dict[str, object]] | None = None
) -> dict[str, Any]:
    message: dict[str, object] = {"content": content or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def _agent_llm(
    settings: AiCoreSettings,
    decide: Callable[[list[dict[str, Any]]], dict[str, Any] | str],
    *,
    answer: str | None = "[1] 답변입니다.",
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
            sse = "\n\n".join(
                [
                    f"data: {json.dumps({'choices': [{'delta': {'content': answer}}]})}",
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
    llm: LlmClient, retriever: FakeRetriever, *, ctx: ToolContext = CTX
) -> list[AssistantEvent]:
    return [
        event
        async for event in answer_question(
            "주차장 언제 열어요?", registry=default_registry(), deps=_deps(retriever, llm), ctx=ctx
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


async def test_no_tool_calls_falls_back_no_evidence(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    # LLM이 도구 없이 즉답 → 근거 0 → 폴백(지어내기 금지).
    llm = _agent_llm(settings, lambda messages: _decision(content="안녕하세요"))
    events = await _run(llm, retriever)
    done = _done(events)
    assert done.fallback_reason == FALLBACK_NO_EVIDENCE
    assert not any(isinstance(e, TokenEvent) for e in events)


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
