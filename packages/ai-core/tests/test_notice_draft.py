"""공지 초안 생성 테스트 — fake retriever + MockTransport LLM(논스트리밍 chat)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import httpx
import pytest

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from ai_core.masking import MaskingFailedError
from ai_core.notice_draft import NoEvidenceError, NoticeDraftResult, draft_notice
from ai_core.rag.retrieval import RetrievedChunk

TENANT = uuid.uuid4()


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


def _llm(settings: AiCoreSettings, answer: str) -> LlmClient:
    dims = settings.embedding_dimensions

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * dims}]})
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": answer}}]}
        )

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


async def _run(llm: LlmClient, retriever: FakeRetriever) -> NoticeDraftResult:
    return await draft_notice(
        ["주차장", "개방"],
        llm=llm,
        retriever=retriever,
        tenant_id=TENANT,
    )


async def test_drafts_notice_with_citation(settings: AiCoreSettings) -> None:
    answer = "지하주차장 개방 안내\n\n지하주차장은 24시간 개방합니다 [1]."
    result = await _run(_llm(settings, answer), FakeRetriever([_chunk()]))
    assert result.title == "지하주차장 개방 안내"
    assert "[1]" in result.body
    assert result.citations and result.citations[0].ref == 1
    assert result.confidence > 0.0


async def test_strips_title_prefix(settings: AiCoreSettings) -> None:
    answer = "제목: 개방 안내\n\n24시간 개방합니다 [1]."
    result = await _run(_llm(settings, answer), FakeRetriever([_chunk()]))
    assert result.title == "개방 안내"


async def test_no_evidence_raises(settings: AiCoreSettings) -> None:
    with pytest.raises(NoEvidenceError):
        await _run(_llm(settings, "무근거 초안 [1]."), FakeRetriever([]))


async def test_low_score_chunks_are_not_evidence(settings: AiCoreSettings) -> None:
    with pytest.raises(NoEvidenceError):
        await _run(_llm(settings, "초안 [1]."), FakeRetriever([_chunk(score=0.1)]))


async def test_uncited_draft_rejected(settings: AiCoreSettings) -> None:
    # 인용이 하나도 없으면 근거 미검증 → 거절(규칙 1).
    with pytest.raises(NoEvidenceError):
        await _run(_llm(settings, "인용 없는 공지 초안입니다."), FakeRetriever([_chunk()]))


async def test_no_evidence_marker_rejected(settings: AiCoreSettings) -> None:
    with pytest.raises(NoEvidenceError):
        await _run(_llm(settings, "NO_EVIDENCE"), FakeRetriever([_chunk()]))


async def test_masking_failure_propagates(
    settings: AiCoreSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(text: str, *, extra_names: Sequence[str] = ()) -> None:
        raise MaskingFailedError("잔존")

    monkeypatch.setattr("ai_core.notice_draft.ensure_masked", _boom)
    with pytest.raises(MaskingFailedError):
        await _run(_llm(settings, "초안 [1]."), FakeRetriever([_chunk()]))
