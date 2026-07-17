"""관리비 설명 단위 — 마스킹 fail-closed·확정 수치 프롬프트·인용 카드(규칙 5)."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

import httpx
import pytest

from ai_core.config import AiCoreSettings
from ai_core.fee_explain import (
    ExplainCitation,
    ExplainDone,
    ExplainEvent,
    ExplainToken,
    build_fee_context,
    explain_fee,
)
from ai_core.llm.client import LlmClient
from ai_core.masking import MaskingFailedError

_BREAKDOWN = {"일반관리비": 100000, "청소비": 20000}
_TOTAL = 120000


def _stream_llm(settings: AiCoreSettings, *, captured: list[str] | None = None) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        if captured is not None:
            captured.append(request.content.decode())
        delta = json.dumps({"choices": [{"delta": {"content": "설명입니다."}}]})
        sse = "\n\n".join([f"data: {delta}", "data: [DONE]", ""])
        return httpx.Response(200, content=sse.encode())

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


async def _collect(gen: AsyncIterator[ExplainEvent]) -> list[ExplainEvent]:
    return [event async for event in gen]


def test_build_context_includes_confirmed_amounts() -> None:
    context = build_fee_context("2026-06", _BREAKDOWN, _TOTAL, prev_total=100000, avg_total=110000)
    assert "2026-06" in context
    assert "100,000" in context  # 일반관리비 확정 수치
    assert "120,000" in context  # 서버 계산 합계
    assert "110,000" in context  # 단지 평균


async def test_explain_emits_citation_and_answered(settings: AiCoreSettings) -> None:
    captured: list[str] = []
    events = await _collect(
        explain_fee(
            llm=_stream_llm(settings, captured=captured),
            period="2026-06",
            breakdown=_BREAKDOWN,
            total=_TOTAL,
            prev_total=100000,
            avg_total=110000,
        )
    )
    tokens = [e for e in events if isinstance(e, ExplainToken)]
    citations = [e for e in events if isinstance(e, ExplainCitation)]
    assert tokens
    assert citations and "2026-06" in citations[0].document_title
    done = events[-1]
    assert isinstance(done, ExplainDone)
    assert done.status == "answered"
    assert done.needs_review is False
    # 확정 수치가 프롬프트에 실려 나간다(계산 아닌 인용 근거).
    assert "120,000" in captured[0]


async def test_masking_failure_falls_back(
    settings: AiCoreSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(text: str, *, extra_names: Sequence[str] = ()) -> None:
        raise MaskingFailedError("잔존")

    monkeypatch.setattr("ai_core.fee_explain.ensure_masked", _boom)
    events = await _collect(
        explain_fee(
            llm=_stream_llm(settings),
            period="2026-06",
            breakdown=_BREAKDOWN,
            total=_TOTAL,
            prev_total=None,
            avg_total=None,
        )
    )
    done = events[-1]
    assert isinstance(done, ExplainDone)
    assert done.status == "fallback"
    assert done.fallback_reason == "masking_failed"
    # fail-closed: 마스킹 실패 시 token 방출 없음(LLM 미호출).
    assert not any(isinstance(e, ExplainToken) for e in events)
