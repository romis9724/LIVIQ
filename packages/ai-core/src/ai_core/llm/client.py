"""OpenAI-호환 LLM·임베딩 클라이언트 (ADR-0005).

- 프로바이더는 env(base_url·model)로 교체 — 코드 변경 없음.
- 재시도는 네트워크·5xx만 지수 백오프 최대 RETRY_MAX회(무한 금지, docs/08 §8). 4xx 즉시 실패.
- 이 클라이언트는 마스킹을 모른다 — 호출자는 반드시 masking.gate를 먼저 통과할 것(규칙 2).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from ai_core.config import AiCoreSettings, get_settings
from ai_core.llm.tokens import estimate_tokens
from ai_core.rag.prompt import NO_EVIDENCE_MARKER

RETRY_MAX = 2  # 최초 시도 외 재시도 횟수 상한
DEFAULT_TEMPERATURE = 0.2

# 인용 문법 강제(R36-A 실험 노브, `LLM_GUIDED_CITATION`). 최종 답변 turn에만 건다 —
# 결정 turn(chat)에 걸면 tool_calls JSON을 문법이 깨뜨린다.
# 두 갈래를 모두 허용해야 폴백 경로가 죽지 않는다: 근거로 답할 수 없으면 NO_EVIDENCE
# 마커로 시작할 수 있고, 그게 아니면 본문에 [n]이 최소 1개 있어야 한다.
# `.` 대신 `[\s\S]`인 이유: vLLM guided decoding 백엔드(outlines·xgrammar)의 정규식 파서는
# 인라인 플래그 `(?s)`를 못 받는데, 목록 답변은 줄바꿈을 반드시 포함한다.
# Ollama는 이 키를 무시하므로 켜져 있어도 vLLM에서만 효력. DB 노브 승격은 실측 후.
GUIDED_CITATION_REGEX = rf"({re.escape(NO_EVIDENCE_MARKER)}[\s\S]*|[\s\S]*\[[0-9]{{1,2}}\][\s\S]*)"

# tool-calling 메시지(assistant tool_calls·role=tool)는 content 외 필드를 담는다 → Any 값 허용.
ChatMessage = Mapping[str, Any]  # {"role": ..., "content": ..., "tool_calls"?: ...}


class LlmError(Exception):
    """LLM 호출 실패(4xx·프로토콜 오류 등, 재시도 무의미)."""


class LlmUnavailableError(LlmError):
    """엔드포인트 미가용(연결·타임아웃·5xx 소진) — 상위에서 발췌 폴백 판단(docs/01 §10)."""


class EmbeddingDimensionError(LlmError):
    """임베딩 차원이 스키마와 다름 — 실측 차원을 담아 올린다(H15-3 저장 거부·연결 테스트용)."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"임베딩 차원 불일치: expected={expected} got={actual}")
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class ChatUsage:
    input_tokens: int
    output_tokens: int
    estimated: bool = False  # usage 미제공 프로바이더 → 추정치


@dataclass(frozen=True)
class ToolCallRequest:
    """LLM이 요청한 도구 호출 1건. arguments는 미검증 JSON 문자열(호출자가 Pydantic 검증)."""

    id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ChatResponse:
    text: str
    usage: ChatUsage
    tool_calls: tuple[ToolCallRequest, ...] | None = None


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

    @property
    def settings(self) -> AiCoreSettings:
        """이 클라이언트가 실제로 쓰는 설정 — 호출자가 활성 백엔드를 식별할 때만 사용.

        런타임 전환(H15-1)에서 주입된 설정이 무엇인지 알아야 캐시 키를 백엔드별로 분리할
        수 있다. 시크릿이 들어 있으니 프로세스 밖으로 내보내지 말 것(응답·로그 금지).
        """
        return self._settings

    def with_settings(self, settings: AiCoreSettings) -> LlmClient:
        """설정만 바꾼 새 클라이언트(전송·재시도 정책 유지, 불변).

        요청·잡 단위 백엔드 전환(H15-3 ai-worker 인제스트)에서 주입된 transport를 잃지 않는다.
        """
        return LlmClient(settings, transport=self._transport, retry_backoff_s=self._retry_backoff_s)

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
        tools: Sequence[Mapping[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> ChatResponse:
        payload: dict[str, object] = {
            "model": self._settings.llm_model,
            "messages": list(messages),
            "max_tokens": self._clamp_max_tokens(max_tokens),
            "temperature": temperature,
            "stream": False,
        }
        if self._settings.llm_reasoning_effort is not None:
            payload["reasoning_effort"] = self._settings.llm_reasoning_effort
        if tools is not None:
            payload["tools"] = list(tools)
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        async with self._client(self._settings.llm_base_url, self._settings.llm_api_key) as c:
            response = await self._post_with_retry(c, "/chat/completions", payload)
        body = response.json()
        try:
            message = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(f"LLM 응답 형식 오류: {exc}") from exc
        if not isinstance(message, Mapping):
            raise LlmError("LLM 응답 형식 오류: message 없음")
        # tool_calls만 있고 content가 null인 경우가 정상(function calling) → text는 빈 문자열.
        text = message.get("content") or ""
        tool_calls = _parse_tool_calls(message.get("tool_calls"))
        return ChatResponse(
            text=text, usage=self._usage_from(body, messages, text), tool_calls=tool_calls
        )

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
        if self._settings.llm_reasoning_effort is not None:
            payload["reasoning_effort"] = self._settings.llm_reasoning_effort
        if self._settings.llm_guided_citation:
            payload["guided_regex"] = GUIDED_CITATION_REGEX
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
        # content가 None인 tool_calls 메시지도 안전하게 처리(빈 문자열로 추정).
        input_est = sum(estimate_tokens(m.get("content") or "") for m in messages)
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
                raise EmbeddingDimensionError(expected, len(vector))
        return vectors


def _parse_tool_calls(raw: object) -> tuple[ToolCallRequest, ...] | None:
    """응답 message.tool_calls를 파싱. arguments는 JSON 문자열 그대로(검증은 호출자)."""
    if not isinstance(raw, list):
        return None
    calls: list[ToolCallRequest] = []
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        if not isinstance(function, Mapping):
            continue
        name = function.get("name")
        if not isinstance(name, str):
            continue
        arguments = function.get("arguments")
        calls.append(
            ToolCallRequest(
                id=str(item.get("id") or ""),
                name=name,
                # 일부 프로바이더는 arguments를 dict로 준다 → 문자열로 정규화.
                arguments=arguments if isinstance(arguments, str) else json.dumps(arguments or {}),
            )
        )
    return tuple(calls) or None


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
