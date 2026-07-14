"""OpenAI-호환 LLM·임베딩 클라이언트 (ADR-0005).

- 프로바이더는 env(base_url·model)로 교체 — 코드 변경 없음.
- 재시도는 네트워크·5xx만 지수 백오프 최대 RETRY_MAX회(무한 금지, docs/08 §8). 4xx 즉시 실패.
- 이 클라이언트는 마스킹을 모른다 — 호출자는 반드시 masking.gate를 먼저 통과할 것(규칙 2).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass

import httpx

from ai_core.config import AiCoreSettings, get_settings
from ai_core.llm.tokens import estimate_tokens

RETRY_MAX = 2  # 최초 시도 외 재시도 횟수 상한
DEFAULT_TEMPERATURE = 0.2

ChatMessage = Mapping[str, str]  # {"role": ..., "content": ...}


class LlmError(Exception):
    """LLM 호출 실패(4xx·프로토콜 오류 등, 재시도 무의미)."""


class LlmUnavailableError(LlmError):
    """엔드포인트 미가용(연결·타임아웃·5xx 소진) — 상위에서 발췌 폴백 판단(docs/01 §10)."""


@dataclass(frozen=True)
class ChatUsage:
    input_tokens: int
    output_tokens: int
    estimated: bool = False  # usage 미제공 프로바이더 → 추정치


@dataclass(frozen=True)
class ChatResponse:
    text: str
    usage: ChatUsage


class LlmClient:
    """생성·임베딩 공용 클라이언트. transport 주입으로 테스트(네트워크 금지)."""

    def __init__(
        self,
        settings: AiCoreSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        retry_backoff_s: float = 0.5,
    ) -> None:
        self._settings = settings or get_settings()
        self._transport = transport
        self._retry_backoff_s = retry_backoff_s

    # ── 내부 공통 ───────────────────────────────────────────────────────

    def _client(self, base_url: str, api_key: str | None) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        return httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=self._settings.llm_timeout_s,
            transport=self._transport,
        )

    async def _post_with_retry(
        self, client: httpx.AsyncClient, path: str, payload: dict[str, object]
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(RETRY_MAX + 1):
            try:
                response = await client.post(path, json=payload)
            except httpx.TransportError as exc:
                last_error = exc
            else:
                if response.status_code < 400:
                    return response
                if response.status_code < 500:
                    raise LlmError(f"LLM 4xx 응답: {response.status_code} {response.text[:200]}")
                last_error = LlmUnavailableError(f"LLM 5xx 응답: {response.status_code}")
            if attempt < RETRY_MAX:
                await asyncio.sleep(self._retry_backoff_s * (2**attempt))
        raise LlmUnavailableError(f"LLM 엔드포인트 미가용(재시도 {RETRY_MAX}회 소진): {last_error}")

    def _clamp_max_tokens(self, max_tokens: int | None) -> int:
        limit = self._settings.llm_max_output_tokens
        return min(max_tokens, limit) if max_tokens is not None else limit

    # ── 생성 ────────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> ChatResponse:
        payload: dict[str, object] = {
            "model": self._settings.llm_model,
            "messages": list(messages),
            "max_tokens": self._clamp_max_tokens(max_tokens),
            "temperature": temperature,
            "stream": False,
        }
        async with self._client(self._settings.llm_base_url, self._settings.llm_api_key) as c:
            response = await self._post_with_retry(c, "/chat/completions", payload)
        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"LLM 응답 형식 오류: {exc}") from exc
        return ChatResponse(text=text, usage=self._usage_from(body, messages, text))

    async def chat_stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> AsyncIterator[str]:
        """증분 텍스트 스트림. 연결 실패는 LlmUnavailableError로 승격."""
        payload: dict[str, object] = {
            "model": self._settings.llm_model,
            "messages": list(messages),
            "max_tokens": self._clamp_max_tokens(max_tokens),
            "temperature": temperature,
            "stream": True,
        }
        async with self._client(self._settings.llm_base_url, self._settings.llm_api_key) as c:
            try:
                async with c.stream("POST", "/chat/completions", json=payload) as response:
                    if response.status_code >= 500:
                        raise LlmUnavailableError(f"LLM 5xx 응답: {response.status_code}")
                    if response.status_code >= 400:
                        raise LlmError(f"LLM 4xx 응답: {response.status_code}")
                    async for line in response.aiter_lines():
                        delta = _parse_sse_line(line)
                        if delta:
                            yield delta
            except httpx.TransportError as exc:
                raise LlmUnavailableError(f"LLM 스트리밍 연결 실패: {exc}") from exc

    def _usage_from(
        self, body: Mapping[str, object], messages: Sequence[ChatMessage], text: str
    ) -> ChatUsage:
        usage = body.get("usage")
        if isinstance(usage, Mapping):
            prompt = usage.get("prompt_tokens")
            completion = usage.get("completion_tokens")
            if isinstance(prompt, int) and isinstance(completion, int):
                return ChatUsage(input_tokens=prompt, output_tokens=completion)
        # usage 미제공 프로바이더 → 추정치로 대체(비용 기록 공백 방지, docs/08 §9)
        input_est = sum(estimate_tokens(m.get("content", "")) for m in messages)
        return ChatUsage(
            input_tokens=input_est, output_tokens=estimate_tokens(text), estimated=True
        )

    # ── 임베딩 ──────────────────────────────────────────────────────────

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """배치 임베딩. 차원 불일치는 즉시 에러(색인 오염 방지, docs/03 §4.2)."""
        if not texts:
            return []
        payload: dict[str, object] = {
            "model": self._settings.embedding_model,
            "input": list(texts),
        }
        async with self._client(
            self._settings.embedding_base_url, self._settings.embedding_api_key
        ) as c:
            response = await self._post_with_retry(c, "/embeddings", payload)
        body = response.json()
        try:
            items = sorted(body["data"], key=lambda d: d["index"])
            vectors: list[list[float]] = [item["embedding"] for item in items]
        except (KeyError, TypeError) as exc:
            raise LlmError(f"임베딩 응답 형식 오류: {exc}") from exc
        expected = self._settings.embedding_dimensions
        for vector in vectors:
            if len(vector) != expected:
                raise LlmError(f"임베딩 차원 불일치: expected={expected} got={len(vector)}")
        return vectors


def _parse_sse_line(line: str) -> str | None:
    """OpenAI SSE 라인(`data: {...}`·`data: [DONE]`)에서 증분 텍스트 추출."""
    if not line.startswith("data:"):
        return None
    data = line[len("data:") :].strip()
    if not data or data == "[DONE]":
        return None
    try:
        chunk = json.loads(data)
        delta = chunk["choices"][0]["delta"].get("content")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return None
    return delta if isinstance(delta, str) else None
