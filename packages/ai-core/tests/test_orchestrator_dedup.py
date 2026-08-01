"""도구 카드 중복 제거 — 같은 결과가 출처로 여러 번 뜨지 않는다.

8B는 같은 도구를 2~3회 반복 호출한다(측정 로그의 search_similar_inquiries 3연속).
문서 청크는 이미 chunk_id로 걸렀지만 카드는 무조건 쌓여 출처가 중복됐다.
여기서 보는 것은 ①출처 카드 수 ②LLM 컨텍스트 재적재 여부(토큰=비용, 규칙 7)다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel, Field
from test_orchestrator import CTX, FakeRetriever, _agent_llm, _decision, _deps, _done

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from ai_core.orchestrator import AssistantEvent, answer_question
from ai_core.tools.registry import (
    Tool,
    ToolCard,
    ToolContext,
    ToolDeps,
    ToolRegistry,
    ToolResult,
)

ECHO = "echo_status"


class _EchoArgs(BaseModel):
    topic: str = Field(..., min_length=1)


async def _echo(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    """인자로 결정되는 카드 1건 — 같은 인자면 같은 카드, 다른 인자면 다른 카드."""
    a = cast(_EchoArgs, args)
    return ToolResult(
        card=ToolCard(
            title=f"{a.topic} 현황",
            quote=f"{a.topic} 처리 완료 3건",
            source_kind=f"tool:{ECHO}",
        )
    )


LATEST = "echo_latest"


class _LatestArgs(BaseModel):
    period: str | None = None


async def _latest(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    """인자가 달라도 같은 결과가 나오는 도구(예: period 생략 vs 최신월 명시)."""
    return ToolResult(
        card=ToolCard(
            title="최근 관리비",
            quote="2026-07 합계 100,000원",
            source_kind=f"tool:{LATEST}",
        )
    )


def _registry() -> ToolRegistry:
    return ToolRegistry(
        [
            Tool(name=ECHO, description="테스트용 조회", args_model=_EchoArgs, run=_echo),
            Tool(
                name=LATEST, description="테스트용 최신 조회", args_model=_LatestArgs, run=_latest
            ),
        ]
    )


def _call(index: int, topic: str) -> dict[str, object]:
    # tool_call_id는 호출마다 달라야 한다(OpenAI 규약) — 같은 도구 반복 호출을 흉내낸다.
    return {
        "id": f"c-{index}",
        "type": "function",
        "function": {"name": ECHO, "arguments": f'{{"topic": "{topic}"}}'},
    }


async def _run(
    settings: AiCoreSettings, topics: Sequence[str]
) -> tuple[list[AssistantEvent], list[list[dict[str, Any]]]]:
    """topics 수만큼 echo를 한 turn에 호출시키고, LLM에 실제로 나간 메시지를 함께 돌려준다."""
    seen: list[list[dict[str, Any]]] = []

    def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
        seen.append(messages)
        if any(m.get("role") == "tool" for m in messages):
            return _decision(content="")
        return _decision(tool_calls=[_call(i, t) for i, t in enumerate(topics)])

    llm: LlmClient = _agent_llm(settings, decide, answer="확인된 내용을 안내드립니다.")
    events = [
        event
        async for event in answer_question(
            "온수 민원 어떻게 됐어요?",
            registry=_registry(),
            deps=_deps(FakeRetriever([]), llm),
            ctx=CTX,
        )
    ]
    return events, seen


def _tool_messages(messages: list[dict[str, Any]]) -> list[str]:
    return [str(m["content"]) for m in messages if m.get("role") == "tool"]


async def test_same_tool_called_three_times_runs_once(settings: AiCoreSettings) -> None:
    """같은 도구·같은 인자 3연속 → **실행 1회**, 출처 카드 1개.

    카드 중복 제거만 있던 시절에는 3번 다 실행됐다(DB 왕복·지연 낭비). 지금은 실행 자체를
    막으므로 tool_path에도 1회만 남는다(2026-08-01 dev 실측 대응).
    """
    events, seen = await _run(settings, ["온수", "온수", "온수"])
    done = _done(events)

    assert done.status == "answered"
    assert done.tool_path == (ECHO,)
    assert len(done.tool_citations) == 1
    assert done.tool_citations[0].quote == "온수 처리 완료 3건"

    # LLM에는 첫 결과만 실리고 나머지 tool_call에는 안내만 돌아간다(규약상 응답은 필수).
    tool_messages = _tool_messages(seen[-1])
    assert tool_messages == [
        "온수 현황: 온수 처리 완료 3건",
        "이미 같은 조건으로 조회했습니다. 조회한 결과로 답변하십시오.",
        "이미 같은 조건으로 조회했습니다. 조회한 결과로 답변하십시오.",
    ]


async def test_different_args_with_same_result_keep_one_card(settings: AiCoreSettings) -> None:
    """인자가 달라 실행은 두 번 되지만 결과가 같으면 출처 카드는 하나다(카드 중복 제거 층).

    호출 차단은 (도구, 인자) 키라 여기서는 걸리지 않는다 — 두 층이 각자 다른 것을 막는다.
    """
    seen: list[list[dict[str, Any]]] = []

    def decide(messages: list[dict[str, Any]]) -> dict[str, Any]:
        seen.append(messages)
        if any(m.get("role") == "tool" for m in messages):
            return _decision(content="")
        return _decision(
            tool_calls=[
                {"id": "c-0", "type": "function", "function": {"name": LATEST, "arguments": "{}"}},
                {
                    "id": "c-1",
                    "type": "function",
                    "function": {"name": LATEST, "arguments": '{"period": "2026-07"}'},
                },
            ]
        )

    llm: LlmClient = _agent_llm(settings, decide, answer="확인된 내용을 안내드립니다.")
    events = [
        event
        async for event in answer_question(
            "이번 달 관리비 얼마예요?",
            registry=_registry(),
            deps=_deps(FakeRetriever([]), llm),
            ctx=CTX,
        )
    ]
    done = _done(events)
    assert done.tool_path == (LATEST, LATEST)  # 인자가 다르니 실행은 막지 않는다
    assert len(done.tool_citations) == 1
    assert _tool_messages(seen[-1])[1] == "이미 조회한 결과입니다."


async def test_different_args_keep_separate_cards(settings: AiCoreSettings) -> None:
    """인자가 달라 결과가 다르면 별개 출처 — 과도한 병합 금지."""
    events, seen = await _run(settings, ["온수", "누수"])
    done = _done(events)

    assert [c.quote for c in done.tool_citations] == ["온수 처리 완료 3건", "누수 처리 완료 3건"]
    assert [c.ref for c in done.tool_citations] == [1, 2]
    assert "이미 조회한 결과입니다." not in _tool_messages(seen[-1])
