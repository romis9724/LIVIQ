"""ask_clarification — 되묻기 특수 도구 (H18-1, ADR-0025 §4).

이 도구는 **DB를 읽지 않는다.** 모델이 고르면 오케스트레이터가 실행 대신 즉시
`DoneEvent(status="clarify")`로 되묻고 종료한다 — 근거 조립·인용 검증을 타지 않는다
(되묻기는 답변이 아니라 질문이라 인용할 근거가 없다, 규칙 1 저촉 아님).
여기서 제공하는 것은 라우팅에 필요한 스펙(이름·설명·인자 검증)뿐이다.

설명 문구가 이 도구의 전부다 — 8B가 남발하면 제품이 망가지므로 조건을 "선택지가 갈려
답을 특정할 수 없을 때만"으로 좁히고, 다른 도구 설명과 어휘가 겹치지 않게 썼다
(H15-2 R22: 의미 중복이 라우팅을 무너뜨린다 — '민원'·'점검' 어휘가 그랬다).
"""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, Field

from ai_core.tools.registry import Tool, ToolContext, ToolDeps, ToolResult

# 오케스트레이터가 이름 상수로 판별한다(ToolResult에 판별 필드를 더하지 않는다 — 나머지
# 도구 10종의 결과 계약을 건드리지 않는 쪽이 diff가 작다).
CLARIFY_TOOL_NAME = "ask_clarification"


class ClarificationArgs(BaseModel):
    question: str = Field(..., min_length=1, description="사용자에게 되물을 한 문장")


async def _ask_clarification(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    """되물을 문장을 그대로 돌려준다 — 조회·부수효과 없음(규칙 8).

    정상 경로에서는 호출되지 않는다(오케스트레이터가 앞서 종료). 직접 실행 경로에
    걸리더라도 아무것도 하지 않도록 note만 채운다.
    """
    a = cast(ClarificationArgs, args)
    return ToolResult(note=a.question)


def ask_clarification_tool() -> Tool:
    return Tool(
        name=CLARIFY_TOOL_NAME,
        description=(
            "질문이 가리키는 대상이 둘 이상으로 갈려 어느 쪽인지 정하지 못할 때만 쓴다. "
            "사용자에게 한 문장으로 어느 쪽인지 물어 좁힌다. "
            "조회해 보면 답이 정해지는 질문에는 쓰지 않는다 — 먼저 다른 도구로 찾아본다."
        ),
        args_model=ClarificationArgs,
        run=_ask_clarification,
    )
