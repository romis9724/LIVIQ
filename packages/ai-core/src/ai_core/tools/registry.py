"""읽기 전용 도구 레지스트리 — 스펙 생성·역할 가시성 필터·검증된 실행 (ADR-0007).

핵심 불변식(규칙 3·4·8):
- **tenant·user는 LLM 인자에서 절대 받지 않는다.** `ToolContext`가 코드로 주입한다.
- 도구 인자는 Pydantic으로 검증한다(실패 = 크래시 없이 오류 결과 반환).
- 역할에 노출되지 않은 도구는 스펙에서 제외 + 직접 호출도 거부한다.
- 도구는 전부 읽기 전용(SELECT만) — 부수효과 금지.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever


@dataclass(frozen=True)
class ToolContext:
    """코드가 주입하는 요청 컨텍스트 — LLM이 절대 지정할 수 없는 격리·소유권 값."""

    tenant_id: uuid.UUID
    user_id: uuid.UUID
    roles: tuple[str, ...]
    visibilities: tuple[str, ...]


@dataclass(frozen=True)
class ToolDeps:
    """도구 실행에 필요한 어댑터 — api 라우터가 요청별로 배선."""

    session: AsyncSession
    llm: LlmClient
    retriever: Retriever
    graph: GraphClient | None = None

    @property
    def graph_available(self) -> bool:
        return self.graph is not None


@dataclass(frozen=True)
class ToolCard:
    """도구 결과의 출처 카드(문서 인용과 동일 원칙). LLM 컨텍스트 + 사용자 표시용."""

    title: str
    quote: str
    source_kind: str  # tool:<이름>


@dataclass(frozen=True)
class ToolResult:
    """도구 1건 실행 결과.

    - `doc_chunks`: search_documents 경로 — 오케스트레이터가 [n] 인용 흐름으로 처리.
    - `card`: 확정 데이터·그래프 등 — 출처 카드 1건으로 표기·인용.
    - `note`: 데이터 없음/오류 등 LLM에 전할 안내(근거 아님 → 인용 생성 안 함).
    """

    card: ToolCard | None = None
    doc_chunks: tuple[RetrievedChunk, ...] = ()
    note: str = ""

    def llm_text(self) -> str:
        if self.card is not None:
            return f"{self.card.title}: {self.card.quote}"
        return self.note


ToolFn = Callable[[ToolContext, ToolDeps, BaseModel], Awaitable[ToolResult]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    run: ToolFn
    allowed_roles: frozenset[str] | None = None  # None = 전 역할
    requires_graph: bool = False

    def is_visible(self, roles: Iterable[str], *, graph_available: bool) -> bool:
        if self.requires_graph and not graph_available:
            return False
        return self.allowed_roles is None or not self.allowed_roles.isdisjoint(roles)

    def spec(self) -> dict[str, Any]:
        """OpenAI function-calling tools 스펙 1건(Pydantic model_json_schema)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_model.model_json_schema(),
            },
        }


class ToolRegistry:
    """도구 모음. 역할·그래프 가용성으로 노출 도구를 필터한다."""

    def __init__(self, tools: Sequence[Tool]) -> None:
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def visible_tools(self, roles: Iterable[str], *, graph_available: bool) -> list[Tool]:
        roles = tuple(roles)
        return [
            t for t in self._tools.values() if t.is_visible(roles, graph_available=graph_available)
        ]

    def specs_for(self, roles: Iterable[str], *, graph_available: bool) -> list[dict[str, Any]]:
        return [t.spec() for t in self.visible_tools(roles, graph_available=graph_available)]

    def get_visible(self, name: str, roles: Iterable[str], *, graph_available: bool) -> Tool | None:
        tool = self._tools.get(name)
        if tool is None or not tool.is_visible(roles, graph_available=graph_available):
            return None
        return tool


@dataclass(frozen=True)
class ToolExecution:
    """실행 결과 + 로깅용 경로 메타(어떤 도구를 왜 호출했는지 — 골든셋 회귀용)."""

    name: str
    result: ToolResult
    ok: bool  # 검증·실행 성공 여부(로깅용, note 반환도 크래시 없음)
    detail: str = ""


async def execute_tool(
    call: ToolCallRequest,
    *,
    ctx: ToolContext,
    deps: ToolDeps,
    registry: ToolRegistry,
) -> ToolExecution:
    """도구 1건: 가시성 확인 → 인자 Pydantic 검증 → 실행. 어떤 실패도 크래시 없이 결과화."""
    tool = registry.get_visible(call.name, ctx.roles, graph_available=deps.graph_available)
    if tool is None:
        return ToolExecution(
            name=call.name,
            result=ToolResult(note=f"도구 '{call.name}'을(를) 사용할 수 없습니다."),
            ok=False,
            detail="not_visible",
        )
    try:
        args = tool.args_model.model_validate_json(call.arguments or "{}")
    except ValidationError as exc:
        first = exc.errors()[:1]
        return ToolExecution(
            name=call.name,
            result=ToolResult(note=f"도구 인자 검증 실패: {first}"),
            ok=False,
            detail="invalid_args",
        )
    result = await tool.run(ctx, deps, args)
    ok = result.card is not None or bool(result.doc_chunks)
    return ToolExecution(name=call.name, result=result, ok=ok)
