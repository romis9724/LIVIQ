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
# 관리사무소(소장·직원) — 세대 평면도 도구의 관리자 변형이 쓰는 집합. 민원 도구
# (inquiries.OFFICE_ROLES)와 같은 집합이라 여기(역할 상수의 정본)에 한 번만 둔다.
OFFICE_ROLES = frozenset({"MANAGER", "STAFF"})
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

# 관리자 변형(H20-17) — 동·호수로 세대를 찾는다. tenant_id를 조인·조건 양쪽에 두는 것은
# RLS와 별개의 2층 방어(규칙 3). `b.name`은 "402"·"402동" 둘 다 실재해 양쪽을 받는다.
# 층은 호수에 이미 담기지만(201=2층 1호) 동명이호가 있어도 결정적이도록 정렬해 1건만 쓴다.
HOUSEHOLD_DEVICES_TOOL = "find_household_devices"
_HOUSEHOLD_CARD_TITLE = "세대 평면도 위치"
_NO_UNIT_NOTE = "어느 동 몇 호인지 확인되지 않아 세대 평면도를 조회하지 못했습니다."
_HOUSEHOLD_BY_UNIT_SQL = text(
    "SELECT h.unit_type_id, hg.unit_type_label "
    "FROM households h "
    "JOIN buildings b ON b.tenant_id = h.tenant_id AND b.id = h.building_id "
    "LEFT JOIN household_geometries hg "
    "ON hg.tenant_id = h.tenant_id AND hg.household_id = h.id "
    "WHERE h.tenant_id = :tid AND h.unit_no = :ho "
    "AND (b.name = :dong OR b.name = :dong || '동') "
    "ORDER BY h.floor LIMIT 1"
)


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


async def _resolve_unit_floor_plan_id(
    ctx: ToolContext, deps: ToolDeps, *, dong: str, ho: int
) -> uuid.UUID | None:
    """(동, 호수) → 그 세대 타입의 평면도 id. 세대·타입·도면 중 하나라도 없으면 None."""
    row = (
        await deps.session.execute(
            _HOUSEHOLD_BY_UNIT_SQL, {"tid": ctx.tenant_id, "dong": dong, "ho": ho}
        )
    ).first()
    if row is None:
        return None

    unit_type_id = row.unit_type_id
    if unit_type_id is None:
        # 세대에 타입이 안 붙어 있으면 트윈 업로드 산물의 라벨로 되짚는다(입주민 경로와 동일).
        if not row.unit_type_label:
            return None
        unit_type_row = (
            await deps.session.execute(
                _UNIT_TYPE_ID_SQL,
                {"tid": ctx.tenant_id, "name": _normalize_label(row.unit_type_label)},
            )
        ).first()
        if unit_type_row is None:
            return None
        unit_type_id = unit_type_row.id

    plan_row = (
        await deps.session.execute(_FLOOR_PLAN_ID_SQL, {"tid": ctx.tenant_id, "utid": unit_type_id})
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


def _group_locations(matched: list[Any]) -> dict[tuple[str, str], list[str]]:
    """(방, 종류) → 방향 라벨 목록. 문장화·강조 라벨이 같은 집계를 쓰게 한 곳에 둔다."""
    groups: dict[tuple[str, str], list[str]] = {}
    for d in matched:
        key = (d.room or "위치 미상", d.device_type)
        groups.setdefault(key, []).append(_dir_label(d.dir))
    return groups


def _format_locations(matched: list[Any]) -> str:
    if matched[0].device_type == "room":
        return "; ".join(f"{d.room} 위치" for d in matched)
    return "; ".join(
        f"{room} {device_type} {len(dirs)}곳: {'·'.join(dirs)}"
        for (room, device_type), dirs in _group_locations(matched).items()
    )


def _highlight_labels(matched: list[Any]) -> list[str]:
    """평면도에서 강조할 라벨 — `FloorPlanViewer`의 `ariaLabel`("거실 콘센트")과 같은 형식.

    화면 딥링크용 확정값이라 서버가 만든다(프론트가 quote를 다시 파싱하지 않는다 — 규칙 8).
    """
    if matched[0].device_type == "room":
        return [d.room for d in matched if d.room]
    return [f"{room} {device_type}" for room, device_type in _group_locations(matched)]


# ── 도구 본체 ──────────────────────────────────────────────────────────────


async def _locate(
    ctx: ToolContext,
    deps: ToolDeps,
    *,
    query: str,
    plan_id: uuid.UUID | None,
    llm_assist: bool = True,
) -> list[Any] | ToolResult:
    """도면 장치 조회 → 스펙 추출 → 매칭. 답을 못 내면 ToolResult(note)로 돌려준다.

    입주민(본인 세대)·관리자(지정 세대) 두 도구의 공통 몸통 — 세대를 **어떻게 정하느냐**만
    다르고(plan_id 해석) 나머지는 같다. 카드 문구·source_kind는 호출자가 붙인다.

    llm_assist: 규칙 파서가 빈손일 때 LLM 보조 추출을 쓸지. **질의가 마스킹 안 된 원문일
    때는 False여야 한다**(규칙 2) — 관리자 경로의 query는 동·호수가 남아 있는 라우터 원문이다.
    """
    if plan_id is None:
        return ToolResult(note=_NOT_READY_NOTE)

    devices = (
        await deps.session.execute(_PLAN_DEVICES_SQL, {"tid": ctx.tenant_id, "pid": plan_id})
    ).all()
    if not devices:
        return ToolResult(note=_NOT_READY_NOTE)

    spec = parse_query(query)
    if spec.is_empty and llm_assist:
        known_elements = sorted({d.device_type for d in devices if d.device_type != "room"})
        known_rooms = sorted({d.room for d in devices if d.room})
        spec = await _llm_assist_spec(deps, query, known_elements, known_rooms)
    if spec.is_empty:
        # 오선택 복구 힌트 — 소형 모델이 공용 설비 질문을 이 도구로 보내는 실측 사례
        # (승강기 대수 등). 다음 스텝에서 문서 검색으로 넘어가도록 안내한다.
        return ToolResult(
            note=(
                "질의에서 평면도 위치를 특정하지 못했습니다. 이 도구는 세대 안 "
                "위치 전용입니다 — 단지 공용 설비(승강기 등)는 search_documents로 "
                "검색하십시오."
            )
        )

    matched = _match_devices(devices, spec)
    if not matched:
        return ToolResult(note="해당 위치를 평면도에서 찾지 못했습니다.")
    return matched


async def _find_in_floor_plan(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(FloorPlanQueryArgs, args)
    located = await _locate(
        ctx, deps, query=a.query, plan_id=await _resolve_floor_plan_id(ctx, deps)
    )
    if isinstance(located, ToolResult):
        return located

    return ToolResult(
        card=ToolCard(
            title="평면도 위치",
            quote=_format_locations(located),
            source_kind="tool:find_in_floor_plan",
        )
    )


async def _find_household_devices(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    """관리자 변형 — 조회 대상 세대는 `ctx.target_unit`(코드가 정한 값)만 인정한다."""
    a = cast(FloorPlanQueryArgs, args)
    # 2차 방어(규칙 4) — 레지스트리 가시성이 1차다. 세대 간 조회 경로라 여기서도 막는다.
    if OFFICE_ROLES.isdisjoint(ctx.roles):
        return ToolResult(note="이 도구를 사용할 권한이 없습니다.")
    if ctx.target_unit is None:
        return ToolResult(note=_NO_UNIT_NOTE)

    dong, ho = ctx.target_unit
    plan_id = await _resolve_unit_floor_plan_id(ctx, deps, dong=dong, ho=ho)
    # **무엇을 찾는지도 코드가 정한다**(H20-17b) — 되묻기로 쪼개진 질문에서 모델이 넘기는
    # query는 설비 어휘를 잃는다(dev 실측: 후속 턴 "401동 201호"가 그대로 인자로 왔다).
    # 라우터 원문에는 동·호수가 남아 있으므로 LLM 보조 추출 경로는 끈다(규칙 2) — 라우터가
    # 요소 어휘를 확인하고 넣은 값이라 규칙 파서만으로 반드시 스펙이 나온다.
    located = await _locate(
        ctx,
        deps,
        query=ctx.target_query or a.query,
        plan_id=plan_id,
        llm_assist=ctx.target_query is None,
    )
    if isinstance(located, ToolResult):
        return located

    return ToolResult(
        card=ToolCard(
            title=_HOUSEHOLD_CARD_TITLE,
            quote=f"{dong}동 {ho}호 · {_format_locations(located)}",
            source_kind=f"tool:{HOUSEHOLD_DEVICES_TOOL}",
            # 화면 전용(LLM 미전송) — "평면도 보기" CTA가 쓰는 확정값(ADR-0025 §6).
            data={
                "kind": "home_devices",
                "dong": dong,
                "ho": ho,
                "labels": _highlight_labels(located),
            },
        )
    )


def find_in_floor_plan_tool() -> Tool:
    return Tool(
        name="find_in_floor_plan",
        # "본인 세대 안" 한정을 명시 — 단지 공용 설비(승강기 등) 질문이 이 도구로
        # 오선택되는 실측 사례가 있었다(2026-07-28). 규약 용어와의 의미 충돌도 같은 부류다:
        # "전용부분과 공용부분의 범위"는 규약 제5조를 묻는 질문인데 '전용/공용'이 평면도
        # 어휘와 겹쳐 이 도구가 3회 호출됐다(2026-07-29 · H15-2 R20).
        description=(
            "본인 세대 평면도 안에서 콘센트·분전함 등 요소나 방의 위치를 조회한다. "
            "집 내부의 **위치를 묻는** 질문 전용 — 고장·누수·소음 같은 증상을 말하거나 "
            "신고하는 질문에는 쓰지 않고, 승강기 등 단지 공용 설비에도 쓰지 않으며, "
            "관리규약·규정이 정한 정의·범위·기준을 묻는 질문에도 쓰지 않는다"
            "(예: '전용부분과 공용부분의 범위'는 규약 조항 질문이므로 문서 검색을 쓴다)."
        ),
        args_model=FloorPlanQueryArgs,
        run=_find_in_floor_plan,
        allowed_roles=RESIDENT_ROLES,
    )


def find_household_devices_tool() -> Tool:
    """관리자용 세대 설비 위치 도구(H20-17).

    입주민 도구와 같은 몸통이지만 **대상 세대를 정하는 방식**이 다르다: 동·호수를 LLM
    인자로 받지 않고 `ToolContext.target_unit`(라우터가 질문에서 뽑은 값)만 쓴다. 이유는
    둘이다 — ①동·호수는 마스킹돼 모델 눈에 `<PII:UNIT:1>`뿐이라 인자로 받을 수가 없고
    (규칙 2), ②세대 지정을 LLM에 맡기면 모델 착오가 곧 타 세대 조회가 된다(규칙 4).
    노출도 라우터가 정한다 — 동·호수가 확정된 질의에서만 스펙에 실린다.
    """
    return Tool(
        name=HOUSEHOLD_DEVICES_TOOL,
        # 입주민 도구와 배타적 역할이라 설명이 섞일 일은 없지만, 공용 설비 배제 문장은
        # 같은 이유로 유지한다("승강기는 어디에 있나요?"가 이리로 새면 안 된다 — H20-16).
        description=(
            "질문에 적힌 동·호수 세대의 평면도에서 콘센트·분전함(두꺼비집)·스위치 등 "
            "세대 안 설비나 방의 위치를 조회한다. 특정 세대 안 설비의 **위치를 묻는** "
            "질문 전용 — 승강기·펌프 같은 단지 공용 설비에는 쓰지 않는다."
        ),
        args_model=FloorPlanQueryArgs,
        run=_find_household_devices,
        allowed_roles=OFFICE_ROLES,
    )
