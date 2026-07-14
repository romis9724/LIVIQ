"""LlmClient 단위 테스트 — httpx.MockTransport 주입, 네트워크 금지."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient, LlmError, LlmUnavailableError

Handler = Callable[[httpx.Request], httpx.Response]


def _client(settings: AiCoreSettings, handler: Handler) -> LlmClient:
    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


def _chat_body(text: str, *, usage: dict[str, int] | None = None) -> dict[str, object]:
    body: dict[str, object] = {"choices": [{"message": {"content": text}}]}
    if usage is not None:
        body["usage"] = usage
    return body


async def test_chat_returns_text_and_usage(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(
            200, json=_chat_body("안녕", usage={"prompt_tokens": 7, "completion_tokens": 3})
        )

    response = await _client(settings, handler).chat([{"role": "user", "content": "hi"}])
    assert response.text == "안녕"
    assert (response.usage.input_tokens, response.usage.output_tokens) == (7, 3)
    assert response.usage.estimated is False


async def test_chat_estimates_usage_when_provider_omits_it(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_chat_body("답변"))

    response = await _client(settings, handler).chat([{"role": "user", "content": "질문"}])
    assert response.usage.estimated is True
    assert response.usage.input_tokens > 0
    assert response.usage.output_tokens > 0


async def test_chat_clamps_max_tokens_to_settings_limit(settings: AiCoreSettings) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_chat_body("ok"))

    await _client(settings, handler).chat([{"role": "user", "content": "q"}], max_tokens=999999)
    assert captured["max_tokens"] == settings.llm_max_output_tokens


async def test_chat_retries_5xx_then_succeeds(settings: AiCoreSettings) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json=_chat_body("ok"))

    response = await _client(settings, handler).chat([{"role": "user", "content": "q"}])
    assert response.text == "ok"
    assert calls["n"] == 2


async def test_chat_raises_unavailable_after_retry_exhaustion(settings: AiCoreSettings) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    with pytest.raises(LlmUnavailableError):
        await _client(settings, handler).chat([{"role": "user", "content": "q"}])
    assert calls["n"] == 3  # 최초 1 + 재시도 2


async def test_chat_4xx_fails_immediately_without_retry(settings: AiCoreSettings) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad request")

    with pytest.raises(LlmError):
        await _client(settings, handler).chat([{"role": "user", "content": "q"}])
    assert calls["n"] == 1


async def test_chat_network_error_raises_unavailable(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(LlmUnavailableError):
        await _client(settings, handler).chat([{"role": "user", "content": "q"}])


async def test_chat_stream_parses_sse_deltas(settings: AiCoreSettings) -> None:
    sse = (
        'data: {"choices":[{"delta":{"content":"관리"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"비"}}]}\n\n'
        'data: {"choices":[{"delta":{}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content=sse.encode())

    chunks = [
        delta
        async for delta in _client(settings, handler).chat_stream(
            [{"role": "user", "content": "q"}]
        )
    ]
    assert chunks == ["관리", "비"]


async def test_embed_returns_vectors_in_index_order(settings: AiCoreSettings) -> None:
    vec = [0.1] * settings.embedding_dimensions

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(
            200,
            json={"data": [{"index": 1, "embedding": vec}, {"index": 0, "embedding": vec}]},
        )

    vectors = await _client(settings, handler).embed(["a", "b"])
    assert len(vectors) == 2


async def test_embed_rejects_dimension_mismatch(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    with pytest.raises(LlmError, match="차원 불일치"):
        await _client(settings, handler).embed(["a"])


async def test_embed_empty_input_short_circuits(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("호출되면 안 됨")

    assert await _client(settings, handler).embed([]) == []
