"""오케스트레이터 파이프라인 테스트 — fake retriever + MockTransport LLM."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import httpx
import pytest

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from ai_core.masking import MaskingFailedError
from ai_core.orchestrator import (
    FALLBACK_LLM_UNAVAILABLE,
    FALLBACK_LOW_CONFIDENCE,
    FALLBACK_MASKING,
    FALLBACK_NO_EVIDENCE,
    AssistantEvent,
    CitationEvent,
    DoneEvent,
    TokenEvent,
    answer_question,
)
from ai_core.rag.retrieval import RetrievedChunk

TENANT = uuid.uuid4()
VISIBILITIES = ["ALL", "RESIDENT"]


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
        self.calls.append({"tenant_id": tenant_id, "visibilities": list(visibilities)})
        return self._chunks


def _chunk(score: float = 0.85, content: str = "지하주차장은 24시간 개방한다.") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_title="관리규약",
        content=content,
        heading=None,
        page=1,
        clause="제3조",
        score=score,
    )


def _llm(settings: AiCoreSettings, answer_sse: str | None, *, embed_ok: bool = True) -> LlmClient:
    dims = settings.embedding_dimensions

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            if not embed_ok:
                return httpx.Response(503)
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * dims}]})
        if answer_sse is None:
            return httpx.Response(503)
        return httpx.Response(200, content=answer_sse.encode())

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


def _sse(*texts: str) -> str:
    lines = ["data: " + json.dumps({"choices": [{"delta": {"content": t}}]}) for t in texts]
    return "\n\n".join([*lines, "data: [DONE]", ""])


async def _run(
    llm: LlmClient, retriever: FakeRetriever, question: str = "주차장 언제 열어요?"
) -> list[AssistantEvent]:
    return [
        event
        async for event in answer_question(
            question,
            llm=llm,
            retriever=retriever,
            tenant_id=TENANT,
            visibilities=VISIBILITIES,
        )
    ]


def _done(events: list[AssistantEvent]) -> DoneEvent:
    assert isinstance(events[-1], DoneEvent)
    return events[-1]


async def test_answered_with_citation(settings: AiCoreSettings) -> None:
    retriever = FakeRetriever([_chunk()])
    events = await _run(_llm(settings, _sse("24시간 개방합니다 ", "[1].")), retriever)
    done = _done(events)
    assert done.status == "answered"
    assert done.citations and done.citations[0].ref == 1
    assert any(isinstance(e, TokenEvent) for e in events)
    assert any(isinstance(e, CitationEvent) for e in events)
    assert done.usage is not None and done.usage.estimated
    assert retriever.calls[0]["tenant_id"] == TENANT


async def test_no_evidence_falls_back_without_llm_generation(settings: AiCoreSettings) -> None:
    events = await _run(_llm(settings, _sse("불려선 안 됨")), FakeRetriever([]))
    done = _done(events)
    assert done.status == "fallback"
    assert done.fallback_reason == FALLBACK_NO_EVIDENCE
    assert not any(isinstance(e, TokenEvent) for e in events)


async def test_low_score_chunks_are_not_evidence(settings: AiCoreSettings) -> None:
    events = await _run(_llm(settings, _sse("무근거 답")), FakeRetriever([_chunk(score=0.1)]))
    assert _done(events).fallback_reason == FALLBACK_NO_EVIDENCE


async def test_no_evidence_marker_from_llm_falls_back(settings: AiCoreSettings) -> None:
    events = await _run(_llm(settings, _sse("NO_EVIDENCE")), FakeRetriever([_chunk()]))
    assert _done(events).fallback_reason == FALLBACK_NO_EVIDENCE


async def test_uncited_answer_falls_back_and_flags_review(settings: AiCoreSettings) -> None:
    events = await _run(_llm(settings, _sse("인용 없는 답변입니다.")), FakeRetriever([_chunk()]))
    done = _done(events)
    assert done.status == "fallback"
    assert done.fallback_reason == FALLBACK_LOW_CONFIDENCE
    assert done.needs_review


async def test_llm_down_returns_excerpt_fallback_with_citation(
    settings: AiCoreSettings,
) -> None:
    events = await _run(_llm(settings, None), FakeRetriever([_chunk()]))
    done = _done(events)
    assert done.fallback_reason == FALLBACK_LLM_UNAVAILABLE
    assert done.citations  # 발췌 폴백도 출처 유지(docs/01 §10)


async def test_embedding_down_falls_back(settings: AiCoreSettings) -> None:
    events = await _run(_llm(settings, _sse("x"), embed_ok=False), FakeRetriever([_chunk()]))
    assert _done(events).fallback_reason == FALLBACK_LLM_UNAVAILABLE


async def test_masking_failure_blocks_llm_call(
    settings: AiCoreSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(text: str, *, extra_names: Sequence[str] = ()) -> None:
        raise MaskingFailedError("잔존")

    monkeypatch.setattr("ai_core.orchestrator.ensure_masked", _boom)
    events = await _run(_llm(settings, _sse("불려선 안 됨")), FakeRetriever([_chunk()]))
    done = _done(events)
    assert done.fallback_reason == FALLBACK_MASKING
    assert done.needs_review
    assert not any(isinstance(e, TokenEvent) for e in events)
