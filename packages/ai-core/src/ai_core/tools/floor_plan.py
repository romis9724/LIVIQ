"""find_in_floor_plan — 평면도 위치 자연어 질의 도구 (FR-PLAN-03, ADR-0007 규칙 8).

규칙 파서 1차(floor_plan_parser.py, LLM 미호출) → 실패 시만 LLM 보조로 spec 구조화
추출(해당 도면의 실제 device_type·room만 enum 제약) → 같은 SQL 경로로 위치 문장화.
본인 세대 한정(household는 ToolContext.user_id로 해석 — get_fees와 동일 패턴, LLM 인자로
세대·타입을 받지 않는다). 도면 없음은 오류가 아니라 note(규칙 1 — 지어내지 않고 안내).

라벨 정규화(`_normalize_label`)는 apps/api/app/routers/floor_plans.py와 동일 로직이나
ai-core는 apps.api에 의존 불가라 재정의한다(library.py의 `_prev_period`와 동일 관례).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import text

from ai_core.llm.client import LlmError
from ai_core.tools.floor_plan_parser import ParsedSpec, parse_query
from ai_core.tools.registry import Tool, ToolCard, ToolContext, ToolDeps, ToolResult

RESIDENT_ROLES = frozenset({"RESIDENT"})
# docs/08 도구 결과 상한(library.py의 MAX_TOOL_ROWS와 동일 값 — 순환 임포트 회피 재정의).
MAX_TOOL_ROWS = 20

_DIR_LABELS: dict[str, str] = {"up": "위쪽", "down": "아래쪽", "left": "왼쪽", "right": "오른쪽"}


class FloorPlanQueryArgs(BaseModel):
    query: str = Field(..., min_length=1, description="평면도 위치를 묻는 자연어 질의")


# ── SQL (household → unit_type 도면 → devices, floor_plans.py §접근통제와 동일 흐름) ──

_HOUSEHOLD_SQL = text("SELECT household_id FROM users WHERE id = :uid AND tenant_id = :tid")
_UNIT_TYPE_LABEL_SQL = text(
    "SELECT unit_type_label FROM household_geometries "
    "WHERE tenant_id = :tid AND household_id = :hid"
)
_UNIT_TYPE_ID_SQL = text("SELECT id FROM unit_types WHERE tenant_id = :tid AND name = :name")
_FLOOR_PLAN_ID_SQL = text(
    "SELECT id FROM floor_plans "
    "WHERE tenant_id = :tid AND scope = 'unit_type' AND unit_type_id = :utid"
)
_PLAN_DEVICES_SQL = text(
    "SELECT device_type, room, dir FROM plan_devices "
    "WHERE tenant_id = :tid AND floor_plan_id = :pid "
    "AND household_id IS NULL AND action = 'base' ORDER BY created_at"
)

_NOT_READY_NOTE = "평면도가 아직 준비되지 않았습니다."


def _normalize_label(label: str) -> str:
    """floor_plans.py `_normalize_label`과 동일("84M(공공임대)" → "84M")."""
    return label.split("(", 1)[0].strip()


async def _resolve_floor_plan_id(ctx: ToolContext, deps: ToolDeps) -> uuid.UUID | None:
    user_row = (
        await deps.session.execute(_HOUSEHOLD_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})
    ).first()
    if user_row is None or user_row.household_id is None:
        return None
    hid = user_row.household_id

    label_row = (
        await deps.session.execute(_UNIT_TYPE_LABEL_SQL, {"tid": ctx.tenant_id, "hid": hid})
    ).first()
    if label_row is None or not label_row.unit_type_label:
        return None

    unit_type_row = (
        await deps.session.execute(
            _UNIT_TYPE_ID_SQL,
            {"tid": ctx.tenant_id, "name": _normalize_label(label_row.unit_type_label)},
        )
    ).first()
    if unit_type_row is None:
        return None

    plan_row = (
        await deps.session.execute(
            _FLOOR_PLAN_ID_SQL, {"tid": ctx.tenant_id, "utid": unit_type_row.id}
        )
    ).first()
    return plan_row.id if plan_row is not None else None


# ── LLM 보조(파서 실패 시만) ──────────────────────────────────────────────────


def _extract_spec_tool_spec(known_elements: list[str], known_rooms: list[str]) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "extract_floor_plan_spec",
            "description": "질의에서 평면도의 실제 요소·방 이름만 추출한다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "array",
                        "items": {"type": "string", "enum": known_elements},
                    },
                    "rooms": {"type": "array", "items": {"type": "string", "enum": known_rooms}},
                },
                "required": ["elements", "rooms"],
            },
        },
    }


async def _llm_assist_spec(
    deps: ToolDeps, query: str, known_elements: list[str], known_rooms: list[str]
) -> ParsedSpec:
    """파서가 못 뽑았을 때만 호출 — enum 밖 값은 폐기(사전 미등록 값 버림, 브리프)."""
    try:
        response = await deps.llm.chat(
            [{"role": "user", "content": query}],
            tools=[_extract_spec_tool_spec(known_elements, known_rooms)],
            tool_choice="required",
        )
    except LlmError:
        return ParsedSpec()
    calls = response.tool_calls or ()
    if not calls:
        return ParsedSpec()
    try:
        raw = json.loads(calls[0].arguments or "{}")
    except json.JSONDecodeError:
        return ParsedSpec()
    elements = tuple(e for e in raw.get("elements") or [] if e in known_elements)
    rooms = tuple(r for r in raw.get("rooms") or [] if r in known_rooms)
    return ParsedSpec(elements=elements, rooms=rooms)


# ── 매칭·문장화 ────────────────────────────────────────────────────────────


def _dir_label(dir_value: str | None) -> str:
    if dir_value is None:
        return "중앙"
    return _DIR_LABELS.get(dir_value, dir_value)


def _match_devices(devices: Sequence[Any], spec: ParsedSpec) -> list[Any]:
    if spec.elements:
        matched = [d for d in devices if d.device_type != "room" and d.device_type in spec.elements]
        if spec.rooms:
            matched = [d for d in matched if d.room in spec.rooms]
    elif spec.rooms:
        matched = [d for d in devices if d.device_type == "room" and d.room in spec.rooms]
    else:
        matched = []
    return matched[:MAX_TOOL_ROWS]


def _format_locations(matched: list[Any]) -> str:
    if matched[0].device_type == "room":
        return "; ".join(f"{d.room} 위치" for d in matched)
    groups: dict[tuple[str, str], list[str]] = {}
    for d in matched:
        key = (d.room or "위치 미상", d.device_type)
        groups.setdefault(key, []).append(_dir_label(d.dir))
    return "; ".join(
        f"{room} {device_type} {len(dirs)}곳: {'·'.join(dirs)}"
        for (room, device_type), dirs in groups.items()
    )


# ── 도구 본체 ──────────────────────────────────────────────────────────────


async def _find_in_floor_plan(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(FloorPlanQueryArgs, args)
    plan_id = await _resolve_floor_plan_id(ctx, deps)
    if plan_id is None:
        return ToolResult(note=_NOT_READY_NOTE)

    devices = (
        await deps.session.execute(_PLAN_DEVICES_SQL, {"tid": ctx.tenant_id, "pid": plan_id})
    ).all()
    if not devices:
        return ToolResult(note=_NOT_READY_NOTE)

    spec = parse_query(a.query)
    if spec.is_empty:
        known_elements = sorted({d.device_type for d in devices if d.device_type != "room"})
        known_rooms = sorted({d.room for d in devices if d.room})
        spec = await _llm_assist_spec(deps, a.query, known_elements, known_rooms)
    if spec.is_empty:
        return ToolResult(note="질의에서 평면도 위치를 특정하지 못했습니다.")

    matched = _match_devices(devices, spec)
    if not matched:
        return ToolResult(note="해당 위치를 평면도에서 찾지 못했습니다.")

    return ToolResult(
        card=ToolCard(
            title="평면도 위치",
            quote=_format_locations(matched),
            source_kind="tool:find_in_floor_plan",
        )
    )


def find_in_floor_plan_tool() -> Tool:
    return Tool(
        name="find_in_floor_plan",
        description="본인 세대 평면도에서 콘센트·분전함 등 요소나 방의 위치를 조회한다.",
        args_model=FloorPlanQueryArgs,
        run=_find_in_floor_plan,
        allowed_roles=RESIDENT_ROLES,
    )
