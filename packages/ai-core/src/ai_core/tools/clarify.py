"""ask_clarification — 되묻기 특수 도구 (H18-1, ADR-0025 §4).

이 도구는 **DB를 읽지 않는다.** 모델이 고르면 오케스트레이터가 실행 대신 즉시
`DoneEvent(status="clarify")`로 되묻고 종료한다 — 근거 조립·인용 검증을 타지 않는다
(되묻기는 답변이 아니라 질문이라 인용할 근거가 없다, 규칙 1 저촉 아님).

되물을 **문장은 모델이 쓰지 않는다.** 모델은 "무엇을 특정해야 하는가"(`missing`)만
지목하고 문장은 여기 템플릿이 만든다 — 8B는 원 질문을 그대로 되묻는 사례가 실측에서
반복됐고(H18-3, "그거 언제 하나요?" → 같은 문장 복사), 프롬프트 강화 2회로도 안 잡혔다.
품질을 보장해야 하는 출력은 코드가 만든다(규칙 8의 정신 — LLM 출력에 결과를 맡기지 않음).

설명 문구가 이 도구의 라우팅 신호 전부다 — 8B가 남발하면 제품이 망가지므로 조건을
"선택지가 갈려 답을 특정할 수 없을 때만"으로 좁히고, 다른 도구 설명과 어휘가 겹치지
않게 썼다(H15-2 R22: 의미 중복이 라우팅을 무너뜨린다 — '민원'·'점검' 어휘가 그랬다).
"""

from __future__ import annotations

from typing import Annotated, cast

from pydantic import BaseModel, Field, StringConstraints

from ai_core.tools.registry import Tool, ToolContext, ToolDeps, ToolResult

# 오케스트레이터가 이름 상수로 판별한다(ToolResult에 판별 필드를 더하지 않는다 — 나머지
# 도구 10종의 결과 계약을 건드리지 않는 쪽이 diff가 작다).
CLARIFY_TOOL_NAME = "ask_clarification"

# 항목명 상한 — 모델이 문장을 통째로 밀어넣는 것을 경계에서 막는다. 넘치면 검증 실패로
# 되묻기를 포기하고 일반 도구 경로로 흐른다(빈/엉터리 되묻기보다 낫다).
MISSING_MAX_LEN = 40
CONTEXT_MAX_LEN = 30

_ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_Missing = Annotated[_ShortText, StringConstraints(max_length=MISSING_MAX_LEN)]
_Context = Annotated[_ShortText, StringConstraints(max_length=CONTEXT_MAX_LEN)]

# 항목 → 되묻는 문장(입주민이 읽는 말투: 존댓말·한 문장·예시 1~2개).
# 키워드는 인자 설명이 유도하는 어휘(기간·대상 설비·동/호수·차량)를 기준으로 골랐다.
# 부분 문자열 매칭이라 '동'·'차'처럼 다른 낱말에 흔히 섞이는 한 글자는 넣지 않는다 —
# 오탐 하나가 엉뚱한 되묻기를 만든다. 예시에 연·월을 박지 않는 것도 의도다(문구가 상함).
_TEMPLATES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("기간", "시기", "날짜", "언제", "월", "연도"),
        "어느 기간을 말씀하시나요? (예: 이번 달, 지난달)",
    ),
    (("설비", "시설", "장비", "기기"), "어떤 설비를 말씀하시나요? (예: 승강기, 급수펌프)"),
    (
        ("동/호수", "동호수", "호수", "세대", "가구"),
        "어느 동·호수를 말씀하시나요? (예: 401동 201호)",
    ),
    (("차량", "차번호", "주차"), "어떤 차량을 말씀하시나요? (예: 12가3456)"),
    (("민원", "문의", "접수"), "어떤 민원을 말씀하시나요?"),
)


# 아는 항목이 아닐 때의 문구. **모델이 준 낱말을 문장에 넣지 않는다** — dev 실측에서
# 모델이 항목이 아니라 주제어를 넣어("온수") "온수에 대해 온수를 알려주시겠어요?" 같은
# 문장이 나왔다. 낱말을 끼워 넣는 템플릿은 입력이 조금만 어긋나도 무너진다.
_GENERIC_QUESTION = "어떤 것을 말씀하시는지 조금 더 알려주시겠어요? (예: 기간, 설비, 동·호수)"


def build_clarification(missing: str, context: str | None = None) -> str:
    """모델이 지목한 항목(missing)으로 되물을 문장 1개를 만든다.

    아는 항목은 전용 문구, 모르는 항목은 **낱말을 쓰지 않는 일반 문구**로 폴백한다.
    주제(context)는 조사 없이 '~에 대해'로 붙인다 — 어떤 명사 뒤에도 어색하지 않은
    유일한 접속이라 조사 선택 로직을 하나 줄인다. 단 주제가 항목과 같은 말이면
    "온수에 대해 온수를"처럼 겹치므로 붙이지 않는다.
    """
    item = missing.strip()
    question = next(
        (text for keys, text in _TEMPLATES if any(key in item for key in keys)),
        _GENERIC_QUESTION,
    )
    topic = (context or "").strip()
    if not topic or topic == item or topic in item or item in topic:
        return question
    return f"{topic}에 대해 {question}"


class ClarificationArgs(BaseModel):
    # 모델에게는 **항목 지목만** 시킨다(문장 생성 금지). 인자 설명이 어휘를 유도하므로
    # 위 템플릿 키워드와 같은 낱말을 예시로 든다.
    missing: _Missing = Field(
        ...,
        description=(
            "답하려면 사용자가 특정해야 하는 것의 짧은 항목 이름. 문장을 쓰지 말 것 "
            "— 되물을 문장은 시스템이 만든다. 예: 기간, 대상 설비, 동/호수, 차량"
        ),
    )
    context: _Context | None = Field(
        default=None,
        description="무엇에 대한 되묻기인지 짧은 주제어(선택). 예: 관리비, 정기점검",
    )


async def _ask_clarification(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    """되물을 문장을 만들어 돌려준다 — 조회·부수효과 없음(규칙 8).

    정상 경로에서는 호출되지 않는다(오케스트레이터가 앞서 종료). 직접 실행 경로에
    걸리더라도 아무것도 하지 않도록 note만 채운다.
    """
    a = cast(ClarificationArgs, args)
    return ToolResult(note=build_clarification(a.missing, a.context))


def ask_clarification_tool() -> Tool:
    return Tool(
        name=CLARIFY_TOOL_NAME,
        # 배제 어휘를 명시한 이유(H19-5 R31): 도구 15종 확장 후 규약·위치처럼 조회로 답이
        # 정해지는 질문이 이 도구로 새는 도피가 재현됐다(3회 전부 10.4%) — 실측에서 샌
        # 카테고리를 설명에 박아 경계를 되세운다(H17-1 관례).
        description=(
            "질문이 가리키는 대상이 둘 이상으로 갈려 어느 쪽인지 정하지 못할 때만 쓴다. "
            "무엇을 특정해야 하는지 항목 이름만 지정한다 — 되물을 문장은 시스템이 만든다. "
            "조회해 보면 답이 정해지는 질문에는 절대 쓰지 않는다 — 규정·규약 내용, 기기 위치, "
            "일정·요금처럼 문서나 데이터에 답이 있는 질문은 먼저 다른 도구로 찾아본다."
        ),
        args_model=ClarificationArgs,
        run=_ask_clarification,
    )
