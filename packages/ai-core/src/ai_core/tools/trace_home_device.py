"""trace_home_device_issue — 세대 기기 고장·이상 → 연결 공용 설비 계통의 장애·조치 이력 추적.

입주민 질의("우리 집 XX가 고장/이상")를 본인 세대 평면도 기기로 좁히고, 그 기기가
`plan_devices.facility_id`로 연결된 공용 설비 계통을 Neo4j에서 조회해 과거 장애·원인·조치
이력을 인과 연쇄까지 카드로 반환한다(GraphRAG 클래스 분담 축, GRAPHRAG-COMPARISON-PLAN §4).

**역할 분담**: PG가 세대 스코프(authz)를 강제하고(find_in_floor_plan과 동일 해석 재사용 —
LLM은 세대·설비를 인자로 못 정한다, 규칙 4), Neo4j가 다단계 인과 추적(CAUSED_BY)을 한다.
읽기 전용(규칙 8). 설비 이력은 PII 아님. 빈 결과(이력 없음)도 카드로 승격한다(⓪ 계약).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import text

from ai_core.graph import IncidentContext
from ai_core.tools.floor_plan import RESIDENT_ROLES, _resolve_floor_plan_id
from ai_core.tools.floor_plan_parser import parse_query
from ai_core.tools.registry import Tool, ToolCard, ToolContext, ToolDeps, ToolResult

# docs/08 도구 결과 상한(library.py의 MAX_TOOL_ROWS와 동일 값 — floor_plan.py 관례로 재정의).
MAX_TOOL_ROWS = 20
_SOURCE_KIND = "tool:trace_home_device_issue"
_CARD_TITLE = "세대 기기 장애 이력"

_NOT_READY_NOTE = "평면도가 준비되지 않아 세대 기기 정보를 확인할 수 없습니다."
_NO_FACILITY_NOTE = "해당 기기는 연결된 공용 설비 계통 정보가 없습니다."
_NO_GRAPH_NOTE = "시설 그래프를 사용할 수 없습니다."
_NO_HISTORY_QUOTE = "연결된 공용 설비 계통에 과거 장애 이력이 없습니다."

# 세대 기기(base 스냅샷)의 device_type·연결 설비. household_id IS NULL = unit_type 도면 기본.
_PLAN_DEVICES_SQL = text(
    "SELECT device_type, facility_id FROM plan_devices "
    "WHERE tenant_id = :tid AND floor_plan_id = :pid "
    "AND household_id IS NULL AND action = 'base'"
)


class TraceHomeDeviceArgs(BaseModel):
    query: str = Field(
        ..., min_length=1, description="세대 기기의 고장·이상 증상을 묻는 자연어 질의"
    )


def _distinct_facility_ids(devices: Sequence[Any]) -> list[str]:
    """선별된 기기의 facility_id 중 NULL 아닌 값을 입력 순서 보존 중복 제거한 문자열 목록."""
    seen: dict[str, None] = {}
    for d in devices:
        if d.facility_id is not None:
            seen.setdefault(str(d.facility_id), None)
    return list(seen)


def _trace_quote(contexts: Sequence[IncidentContext]) -> str:
    """장애 이력 문장화 — 설비명(상태) 증상·원인·조치 + 선행원인 연쇄 + 최근정비."""
    lines: list[str] = []
    for c in contexts[:MAX_TOOL_ROWS]:
        facility = f"{c.facility_name}({c.facility_status})" if c.facility_name else "설비미상"
        parts = [f"{facility} 증상: {c.symptom}"]
        if c.root_cause:
            parts.append(f"원인: {c.root_cause}")
        if c.resolution:
            parts.append(f"조치: {c.resolution}")
        if c.causal_chain:
            parts.append(f"선행원인: {' ← '.join(c.causal_chain)}")
        if c.recent_work:
            parts.append(f"최근정비: {', '.join(c.recent_work)}")
        lines.append(" · ".join(parts))
    return " / ".join(lines)


async def _trace_home_device(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(TraceHomeDeviceArgs, args)
    plan_id = await _resolve_floor_plan_id(ctx, deps)
    if plan_id is None:
        return ToolResult(note=_NOT_READY_NOTE)

    devices = (
        await deps.session.execute(_PLAN_DEVICES_SQL, {"tid": ctx.tenant_id, "pid": plan_id})
    ).all()

    # 증상 파서가 device_type을 뽑았으면 그 종류만, 아니면 세대 기기 전체를 대상으로 한다.
    spec = parse_query(a.query)
    selected = [d for d in devices if not spec.elements or d.device_type in spec.elements]
    facility_ids = _distinct_facility_ids(selected)

    # 미모델링(연결 설비 정보 없음) vs 이력 없음(⑦)을 구분한다(§4.2·SEED-PLAN §4). 선별 기기가
    # 없거나 전부 facility_id NULL이면 계통 자체가 그래프에 없다 — note.
    if not facility_ids:
        return ToolResult(note=_NO_FACILITY_NOTE)

    if deps.graph is None:
        return ToolResult(note=_NO_GRAPH_NOTE)

    contexts = await deps.graph.incidents_for_facilities(
        tenant_id=str(ctx.tenant_id), facility_ids=facility_ids
    )
    # 이력 없음도 확정 근거 — note가 아니라 카드로 승격한다(⓪ 계약, get_my_inquiries 관례).
    quote = _trace_quote(contexts) if contexts else _NO_HISTORY_QUOTE
    return ToolResult(card=ToolCard(title=_CARD_TITLE, quote=quote, source_kind=_SOURCE_KIND))


def trace_home_device_issue_tool() -> Tool:
    return Tool(
        name="trace_home_device_issue",
        # 신고형 배제는 R36 실측 — "온수가 미지근해요"·"도어록 경고음"(IQ-03·IQ-06·GR-0027)이
        # 이력 추적으로 새서 접수 CTA가 달린 유사 민원 답변을 못 받았다. 이 도구가 답하는 건
        # "왜 그런가(과거 이력)"이지 "접수해 달라"가 아니다(ADR-0024 분담).
        description=(
            "본인 세대 기기(월패드·화재감지기·수도밸브 등)의 고장·이상 증상에 대해, 그 기기가 "
            "연결된 공용 설비 계통의 과거 장애·원인·조치 이력을 추적한다. 집 안 위치를 묻는 "
            "질문(find_in_floor_plan)이나 관리규약 조항 질문에는 쓰지 않는다. "
            "'~가 안 돼요', '~가 이상해요'처럼 고장을 신고·접수하려는 질문에도 쓰지 않는다 — "
            "유사 민원 검색을 쓴다."
        ),
        args_model=TraceHomeDeviceArgs,
        run=_trace_home_device,
        allowed_roles=RESIDENT_ROLES,
        requires_graph=True,
    )
