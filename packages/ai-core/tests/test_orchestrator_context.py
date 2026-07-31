"""멀티턴 컨텍스트 + 되묻기 (H18-1, ADR-0025 §3·4).

도구 루프 자체의 회귀는 test_orchestrator.py가 담당한다 — 여기서는 LLM에 **무엇이
실려 나갔는지**(히스토리 주입·스펙 필터)와 되묻기 종료 경로만 본다.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import httpx
import pytest
from test_orchestrator import CTX, FakeRetriever, _chunk, _decision, _deps, _done, _tc

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from ai_core.masking import MaskingFailedError, ensure_masked
from ai_core.orchestrator import (
    FALLBACK_MASKING,
    HISTORY_MAX_CHARS,
    HISTORY_MAX_TURNS,
    AssistantEvent,
    CitationEvent,
    DoneEvent,
    TokenEvent,
    answer_question,
)
from ai_core.tools import ToolDeps, default_registry
from ai_core.tools.clarify import ClarificationArgs, ask_clarification_tool

CLARIFY = "ask_clarification"


@dataclass
class Recorded:
    """LLM에 실제로 나간 것 — 도구 결정 turn·최종 답변 turn을 따로 모은다."""

    decisions: list[list[dict[str, Any]]] = field(default_factory=list)
    streams: list[list[dict[str, Any]]] = field(default_factory=list)
    tool_names: list[list[str]] = field(default_factory=list)


def _recording_llm(
    settings: AiCoreSettings,
    decide: Callable[[list[dict[str, Any]]], dict[str, Any]],
    rec: Recorded,
    *,
    answer: str = "24시간 개방 [1].",
) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            dims = settings.embedding_dimensions
            data = [{"index": i, "embedding": [0.05] * dims} for i in range(len(body["input"]))]
            return httpx.Response(200, json={"data": data})
        if body.get("stream"):
            rec.streams.append(body["messages"])
            chunk = {"choices": [{"delta": {"content": answer}}]}
            sse = "\n\n".join([f"data: {json.dumps(chunk)}", "data: [DONE]", ""])
            return httpx.Response(200, content=sse.encode())
        rec.decisions.append(body["messages"])
        rec.tool_names.append([t["function"]["name"] for t in body.get("tools", [])])
        return httpx.Response(200, json=decide(body["messages"]))

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


def _doc_then_stop(messages: list[dict[str, Any]]) -> dict[str, Any]:
    if any(m.get("role") == "tool" for m in messages):
        return _decision(content="")
    return _decision(tool_calls=[_tc("search_documents", {"query": "주차"})])


async def _run(
    llm: LlmClient,
    retriever: FakeRetriever,
    *,
    question: str = "그럼 언제까지야?",
    history: Sequence[tuple[str, str]] = (),
    allow_clarify: bool = True,
) -> list[AssistantEvent]:
    return [
        event
        async for event in answer_question(
            question,
            registry=default_registry(),
            deps=_deps(retriever, llm),
            ctx=CTX,
            history=history,
            allow_clarify=allow_clarify,
        )
    ]


# ── 멀티턴 컨텍스트 ────────────────────────────────────────────────────


async def test_history_reaches_both_decision_and_final_turn(settings: AiCoreSettings) -> None:
    """히스토리는 도구 결정 turn과 최종 답변 turn **양쪽**에 실린다(ADR-0025 §3)."""
    rec = Recorded()
    llm = _recording_llm(settings, _doc_then_stop, rec)
    history = (("user", "지하주차장 개방 시간 알려줘"), ("assistant", "24시간 개방합니다."))
    _done(await _run(llm, FakeRetriever([_chunk()]), history=history))

    # 결정 turn: OpenAI 규약의 개별 메시지로(역할 보존).
    first = rec.decisions[0]
    assert [m["role"] for m in first] == ["system", "user", "assistant", "user"]
    assert first[1]["content"] == "지하주차장 개방 시간 알려줘"
    assert first[2]["content"] == "24시간 개방합니다."
    assert first[-1]["content"] == "그럼 언제까지야?"

    # 최종 답변 turn: 단일 user 메시지 안의 [이전 대화] 블록으로.
    final_user = rec.streams[0][-1]["content"]
    assert "[이전 대화]" in final_user
    assert "24시간 개방합니다." in final_user
    assert "[질문]\n그럼 언제까지야?" in final_user


async def test_history_is_capped_by_turns_and_chars(settings: AiCoreSettings) -> None:
    """직전 3턴(=6메시지)·턴당 400자 상한 — 초과분은 잘린다(토큰=비용)."""
    rec = Recorded()
    llm = _recording_llm(settings, _doc_then_stop, rec)
    history = tuple(
        (role, f"{i}번째{'가' * 500}")
        for i, role in enumerate(["user", "assistant"] * 5)  # 10메시지 = 5턴
    )
    _done(await _run(llm, FakeRetriever([_chunk()]), history=history))

    injected = rec.decisions[0][1:-1]  # system·현재 질문 제외 = 주입된 히스토리
    assert len(injected) == HISTORY_MAX_TURNS * 2
    assert str(injected[0]["content"]).startswith("4번째")  # 앞선 4메시지는 버려짐
    assert all(len(str(m["content"])) == HISTORY_MAX_CHARS for m in injected)


async def test_empty_history_entries_are_dropped(settings: AiCoreSettings) -> None:
    """본문 없는 턴(폴백 메시지 등)은 싣지 않는다 — 맥락 0, 토큰만 소비."""
    rec = Recorded()
    llm = _recording_llm(settings, _doc_then_stop, rec)
    _done(await _run(llm, FakeRetriever([_chunk()]), history=(("assistant", "   "),)))
    assert [m["role"] for m in rec.decisions[0]] == ["system", "user"]


async def test_history_masking_failure_blocks_llm_call(
    settings: AiCoreSettings, monkeypatch: Any
) -> None:
    """히스토리 마스킹 실패도 fail-closed(규칙 2) — 히스토리만 버리고 진행하지 않는다."""

    def picky(text: str, *, extra_names: Sequence[str] = ()) -> Any:
        if "잔존PII" in text:
            raise MaskingFailedError("히스토리 잔존")
        return ensure_masked(text, extra_names=extra_names)

    monkeypatch.setattr("ai_core.orchestrator.ensure_masked", picky)
    rec = Recorded()
    llm = _recording_llm(settings, _doc_then_stop, rec)
    events = await _run(llm, FakeRetriever([_chunk()]), history=(("assistant", "잔존PII 포함"),))
    done = _done(events)
    assert done.fallback_reason == FALLBACK_MASKING
    assert done.needs_review
    assert rec.decisions == []  # LLM 호출 자체가 없어야 한다


async def test_no_history_keeps_previous_shape(settings: AiCoreSettings) -> None:
    """히스토리가 없으면 기존 동작 그대로(회귀) — 메시지 구성도 [이전 대화]도 변화 없음."""
    rec = Recorded()
    llm = _recording_llm(settings, _doc_then_stop, rec)
    done = _done(await _run(llm, FakeRetriever([_chunk()])))
    assert done.status == "answered"
    assert [m["role"] for m in rec.decisions[0]] == ["system", "user"]
    assert "[이전 대화]" not in str(rec.streams[0][-1]["content"])


# ── 되묻기 ─────────────────────────────────────────────────────────────


async def test_clarify_tool_ends_turn_immediately(settings: AiCoreSettings) -> None:
    """되묻기는 실행·인용검증 없이 즉시 종료하고, 같은 turn의 다른 도구보다 우선한다."""
    rec = Recorded()
    retriever = FakeRetriever([_chunk()])
    llm = _recording_llm(
        settings,
        lambda messages: _decision(
            tool_calls=[
                _tc("search_documents", {"query": "관리비"}),
                _tc(CLARIFY, {"missing": "기간", "context": "관리비"}),
            ],
            usage=(120, 8),
        ),
        rec,
    )
    events = await _run(llm, retriever, question="관리비 얼마야?")
    done = _done(events)

    assert done.status == "clarify"
    # 문장은 모델이 아니라 코드 템플릿이 만든다(H18-3: 8B가 원 질문을 복사했다).
    assert done.answer == "관리비에 대해 어느 기간을 말씀하시나요? (예: 이번 달, 지난달)"
    assert done.confidence == 0.0 and done.needs_review is False
    assert done.tool_path == (CLARIFY,)
    assert not done.citations and not done.tool_citations
    # 인용 검증·답변 생성 경로를 타지 않는다(스트림 없음) + 다른 도구도 실행되지 않는다.
    assert not any(isinstance(e, TokenEvent | CitationEvent) for e in events)
    assert rec.streams == [] and retriever.calls == []
    # 여기까지 쓴 결정 turn 토큰은 실려야 한다(원가 누락 방지).
    assert done.usage is not None
    assert (done.usage.input_tokens, done.usage.output_tokens) == (120, 8)


async def test_clarify_spec_hidden_after_clarify_turn(settings: AiCoreSettings) -> None:
    """직전 턴이 되묻기였으면 도구 스펙에서 제외 — 연속 되묻기 금지(ADR-0025 §4)."""
    rec = Recorded()
    llm = _recording_llm(settings, _doc_then_stop, rec)
    await _run(llm, FakeRetriever([_chunk()]), allow_clarify=False)
    assert CLARIFY not in rec.tool_names[0]
    assert "search_documents" in rec.tool_names[0]  # 나머지 도구는 그대로


async def test_clarify_call_ignored_when_not_allowed(settings: AiCoreSettings) -> None:
    """스펙에서 빠졌는데도 모델이 되묻기를 부르면 무시한다(연속 되묻기 차단은 서버가 강제)."""
    rec = Recorded()
    llm = _recording_llm(
        settings,
        lambda messages: (
            _decision(content="")
            if any(m.get("role") == "tool" for m in messages)
            else _decision(
                tool_calls=[
                    _tc(CLARIFY, {"missing": "기간"}),
                    _tc("search_documents", {"query": "주차"}),
                ]
            )
        ),
        rec,
    )
    done = _done(await _run(llm, FakeRetriever([_chunk()]), allow_clarify=False))
    assert done.status == "answered"
    assert CLARIFY in done.tool_path  # 실행은 됐으나(근거 없음 note) 되묻기로 끝나지 않음


@pytest.mark.parametrize("args", [{}, {"missing": "   "}, {"missing": "가" * 41}])
async def test_clarify_with_invalid_args_does_not_clarify(
    settings: AiCoreSettings, args: dict[str, str]
) -> None:
    """인자 검증 실패(미지정·빈 값·문장 통째)면 되묻지 않는다 — 일반 도구 경로로 계속."""
    rec = Recorded()
    llm = _recording_llm(
        settings,
        lambda messages: (
            _decision(content="")
            if any(m.get("role") == "tool" for m in messages)
            else _decision(
                tool_calls=[_tc(CLARIFY, args), _tc("search_documents", {"query": "주차"})]
            )
        ),
        rec,
    )
    done = _done(await _run(llm, FakeRetriever([_chunk()])))
    assert done.status == "answered"


def test_clarify_tool_is_visible_to_every_role() -> None:
    """되묻기는 역할 제한이 없다 — 관리자·입주민 모두 되물을 수 있어야 한다."""
    registry = default_registry()
    for roles in (("RESIDENT",), ("MANAGER",), ("SYS_ADMIN",)):
        names = [t.name for t in registry.visible_tools(roles, graph_available=False)]
        assert CLARIFY in names


async def test_clarify_tool_run_has_no_side_effect() -> None:
    """직접 실행 경로에 걸려도 조회 없이 되물을 문장만 돌려준다(읽기 전용, 규칙 8)."""
    tool = ask_clarification_tool()
    # deps는 쓰지 않는다(DB·LLM 접근 없음) — 그 사실 자체를 None 주입으로 고정한다.
    deps = cast(ToolDeps, None)
    result = await tool.run(CTX, deps, ClarificationArgs(missing="동/호수"))
    assert result.note == "어느 동·호수를 말씀하시나요? (예: 401동 201호)"
    assert result.card is None and result.doc_chunks == ()


def test_clarify_done_event_is_not_a_fallback() -> None:
    """status 리터럴 확장이 폴백과 섞이지 않는지 — 소비자(api·web)가 분기하는 값."""
    done = DoneEvent(status="clarify", confidence=0.0, needs_review=False, usage=None)
    assert done.status != "fallback"
    assert done.fallback_reason is None
