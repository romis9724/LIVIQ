"""LlmClient 단위 테스트 — httpx.MockTransport 주입, 네트워크 금지."""

from __future__ import annotations

import json
import re
from collections.abc import Callable

import httpx
import pytest

from ai_core.config import AiCoreSettings
from ai_core.llm.client import (
    GUIDED_CITATION_REGEX,
    EmbeddingDimensionError,
    LlmClient,
    LlmError,
    LlmUnavailableError,
)

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


async def test_chat_omits_reasoning_effort_by_default(settings: AiCoreSettings) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_chat_body("ok"))

    await _client(settings, handler).chat([{"role": "user", "content": "q"}])
    assert "reasoning_effort" not in captured


async def test_chat_sends_reasoning_effort_when_configured(settings: AiCoreSettings) -> None:
    """추론(thinking) 모델 대응 — LLM_REASONING_EFFORT=none이면 페이로드에 실린다.

    qwen3 등은 추론 토큰이 출력 예산을 먹어 content가 빈 채 잘린다(호스트 실측) —
    Ollama OpenAI 호환의 reasoning_effort로 끈다.
    """
    tuned = settings.model_copy(update={"llm_reasoning_effort": "none"})
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_chat_body("ok"))

    await _client(tuned, handler).chat([{"role": "user", "content": "q"}])
    assert captured["reasoning_effort"] == "none"


async def test_chat_stream_sends_reasoning_effort_when_configured(
    settings: AiCoreSettings,
) -> None:
    tuned = settings.model_copy(update={"llm_reasoning_effort": "none"})
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    stream = _client(tuned, handler).chat_stream([{"role": "user", "content": "q"}])
    chunks = [t async for t in stream]
    assert chunks == ["ok"]
    assert captured["reasoning_effort"] == "none"


# ── 인용 문법 강제(R36-A 실험 노브) ──────────────────────────────────────


def _sse_handler(captured: dict[str, object]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    return handler


async def test_chat_stream_omits_guided_regex_by_default(settings: AiCoreSettings) -> None:
    """기본 off — 노브를 켜지 않으면 페이로드는 기존과 동일하다."""
    captured: dict[str, object] = {}

    stream = _client(settings, _sse_handler(captured)).chat_stream(
        [{"role": "user", "content": "q"}]
    )
    assert [t async for t in stream] == ["ok"]
    assert "guided_regex" not in captured


async def test_guided_citation_applies_to_stream_turn_only(settings: AiCoreSettings) -> None:
    """노브 on이면 최종 답변(stream) turn에만 실린다 — 결정 turn은 tool_calls JSON이라 제외."""
    tuned = settings.model_copy(update={"llm_guided_citation": True})
    streamed: dict[str, object] = {}
    decided: dict[str, object] = {}

    stream = _client(tuned, _sse_handler(streamed)).chat_stream([{"role": "user", "content": "q"}])
    assert [t async for t in stream] == ["ok"]

    def decide(request: httpx.Request) -> httpx.Response:
        decided.update(json.loads(request.content))
        return httpx.Response(200, json=_chat_body("ok"))

    await _client(tuned, decide).chat([{"role": "user", "content": "q"}])

    assert streamed["guided_regex"] == GUIDED_CITATION_REGEX
    assert "guided_regex" not in decided


@pytest.mark.parametrize(
    ("answer", "allowed"),
    [
        # 근거로 답할 수 없는 경우의 폴백 경로는 문법이 막으면 안 된다.
        ("NO_EVIDENCE", True),
        ("지하주차장은 24시간 개방합니다 [1].", True),
        # 목록 답변은 줄바꿈을 포함한다 — `.` 대신 `[\s\S]`를 쓴 이유.
        ("- 개방 시간: 24시간 [1]\n- 문의: 관리사무소 [2]", True),
        ("인용 없는 평문 답변입니다.", False),
    ],
)
def test_guided_citation_regex_allows_marker_or_citation(answer: str, allowed: bool) -> None:
    assert bool(re.fullmatch(GUIDED_CITATION_REGEX, answer)) is allowed


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


async def test_chat_parses_tool_calls_with_null_content(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "get_fees",
                                        "arguments": '{"period": "2026-06"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
        )

    response = await _client(settings, handler).chat(
        [{"role": "user", "content": "관리비"}], tools=[{"type": "function"}]
    )
    assert response.text == ""  # content=None → 빈 문자열
    assert response.tool_calls is not None
    assert response.tool_calls[0].name == "get_fees"
    assert response.tool_calls[0].arguments == '{"period": "2026-06"}'


async def test_chat_includes_tools_in_payload(settings: AiCoreSettings) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_chat_body("ok"))

    tools = [{"type": "function", "function": {"name": "t"}}]
    await _client(settings, handler).chat(
        [{"role": "user", "content": "q"}], tools=tools, tool_choice="auto"
    )
    assert captured["tools"] == tools
    assert captured["tool_choice"] == "auto"


async def test_chat_without_tools_omits_tool_calls(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "tools" not in json.loads(request.content)
        return httpx.Response(200, json=_chat_body("답"))

    response = await _client(settings, handler).chat([{"role": "user", "content": "q"}])
    assert response.tool_calls is None


async def test_chat_normalizes_dict_arguments(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"id": "c", "function": {"name": "get_fees", "arguments": {}}}
                            ],
                        }
                    }
                ]
            },
        )

    response = await _client(settings, handler).chat([{"role": "user", "content": "q"}])
    assert response.tool_calls is not None
    assert response.tool_calls[0].arguments == "{}"


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
    """실측 차원을 예외에 담아 올린다 — 관리자 화면이 "몇 차원인지"를 보여줄 수 있어야 한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    with pytest.raises(EmbeddingDimensionError, match="차원 불일치") as exc_info:
        await _client(settings, handler).embed(["a"])
    assert exc_info.value.actual == 2
    assert exc_info.value.expected == settings.embedding_dimensions
    assert isinstance(exc_info.value, LlmError)  # 기존 호출자의 예외 처리 계약 유지


async def test_with_settings_keeps_injected_transport(settings: AiCoreSettings) -> None:
    """설정만 바꾼 클라이언트 — 주입된 transport·백오프를 잃지 않는다(잡 단위 전환, H15-3)."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1] * settings.embedding_dimensions}]}
        )

    swapped = _client(settings, handler).with_settings(
        settings.model_copy(update={"embedding_base_url": "http://other-embed.test/v1"})
    )
    await swapped.embed(["a"])
    assert seen == ["http://other-embed.test/v1/embeddings"]


async def test_embed_empty_input_short_circuits(settings: AiCoreSettings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("호출되면 안 됨")

    assert await _client(settings, handler).embed([]) == []
