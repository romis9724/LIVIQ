"""주차 도구 2종 — 빈자리 찾기(H15-4, ADR-0023 개정)와 내 차 위치(H19-2).

- `find_nearest_available_parking`: 세대→동(PG authz)로 앵커 코어를 정하고, `parking_layouts`
  (면·코어)와 `parking_vehicles`(spot_no가 있는 행 = 점유 중, SoR — H16)를 읽어
  `geometry.nearest_available_spots`로 최근접 빈 면을 계산한다.
- `find_my_vehicle`: 본인 세대 등록 차량의 면 번호·입차 경과·본인 동 승강기까지 거리.

거리·경과는 도구가 확정한다 — LLM은 면·거리·시각을 지어내지 않는다(규칙 8). 두 도구 모두
타 입주민 PII를 반환하지 않는다(빈 면은 애초에 소유자가 없고, 내 차는 본인 세대만). 읽기 전용.

세대·tenant는 ToolContext에서 오며 LLM 인자로 받지 않는다(규칙 3·4 — get_fees와 동일).
점유는 데모 데이터이므로 답변에 그 사실을 명시한다(규칙 1 — 출처=parking_vehicles).

관리자용 장기주차 조회(`find_longterm_parking`, H19-3)는 같은 테이블을 읽지만 FACILITY_ROLES
도구라 library.py에 있다(FACILITY_ROLES가 library에 있어 여기서 import하면 순환).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import text

from ai_core.parking import (
    PX_TO_M,
    core_center,
    cores_from_layout,
    distance_px,
    nearest_available_spots,
    spots_from_layout,
)
from ai_core.tools.floor_plan import RESIDENT_ROLES
from ai_core.tools.registry import Tool, ToolCard, ToolContext, ToolDeps, ToolResult

_SOURCE_KIND = "tool:find_nearest_available_parking"
_CARD_TITLE = "가까운 빈 주차자리"
_TOP_K = 3
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"

_NO_HOUSEHOLD_NOTE = "세대 정보를 찾을 수 없습니다."
_NO_LAYOUT_NOTE = "주차장 배치도가 없습니다."
_NO_SPOT_NOTE = "가까운 빈 주차자리가 없습니다."

# 세대 → 동 이름("401"). find_in_floor_plan의 _HOUSEHOLD_SQL 패턴을 buildings 조인으로 확장.
_HOUSEHOLD_DONG_SQL = text(
    "SELECT b.name AS building_name FROM users u "
    "JOIN households h ON h.id = u.household_id "
    "JOIN buildings b ON b.id = h.building_id "
    "WHERE u.id = :uid AND u.tenant_id = :tid"
)
_LAYOUT_SQL = text("SELECT layout FROM parking_layouts WHERE tenant_id = :tid")
_OCCUPANCY_SQL = text(
    "SELECT spot_no FROM parking_vehicles WHERE tenant_id = :tid AND spot_no IS NOT NULL"
)
# 세대 EV 보유 여부 — 2026-08-03 사용자 신고(317면 전기차가 더 먼 일반 면보다 가까운데 누락).
# 8B는 "충전" 언급 없이는 ev_preferred를 안 채우므로, 세대 차량 데이터로 전기차 면 포함을 판정한다.
_HAS_EV_SQL = text(
    "SELECT bool_or(v.is_ev) AS has_ev FROM parking_vehicles v "
    "WHERE v.tenant_id = :tid AND v.household_id = "
    "(SELECT u.household_id FROM users u WHERE u.id = :uid AND u.tenant_id = :tid)"
)


class NearestParkingArgs(BaseModel):
    ev_preferred: bool = Field(
        False, description="전기차 충전 자리를 원하면 true (사용자가 전기차·충전 언급 시)"
    )


def _data(nearest: list[Any]) -> dict[str, Any]:
    """화면용 자리 목록(ADR-0025 §6) — 도구가 계산한 면·종류·거리를 값 그대로.

    LLM은 이 dict를 보지 않는다. 거리·면번호를 모델이 재작성하면 실제 자리와 어긋난다(규칙 8).
    """
    return {
        "kind": "parking_spots",
        "spots": [{"no": n.no, "kind": n.kind, "distance_m": n.distance_m} for n in nearest],
    }


def _quote(nearest: list[Any]) -> str:
    lines = [
        f"{_CIRCLED[i]} {n.no}면 ({n.kind}, 약 {n.distance_m}m)" for i, n in enumerate(nearest)
    ]
    body = "\n".join(lines)
    return f"{body}\n(데모 데이터 · 출처: parking_vehicles 점유 현황)"


async def _find_nearest_parking(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(NearestParkingArgs, args)

    hh = (
        await deps.session.execute(_HOUSEHOLD_DONG_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})
    ).first()
    if hh is None or not hh.building_name:
        return ToolResult(note=_NO_HOUSEHOLD_NOTE)
    core_name = f"{hh.building_name}동"

    layout_row = (await deps.session.execute(_LAYOUT_SQL, {"tid": ctx.tenant_id})).first()
    if layout_row is None or not layout_row.layout:
        return ToolResult(note=_NO_LAYOUT_NOTE)
    layout = cast(dict[str, Any], layout_row.layout)

    occupied = {
        r.spot_no
        for r in (await deps.session.execute(_OCCUPANCY_SQL, {"tid": ctx.tenant_id})).all()
    }

    ev_row = (
        await deps.session.execute(_HAS_EV_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})
    ).first()
    household_has_ev = bool(ev_row.has_ev) if ev_row is not None else False

    nearest = nearest_available_spots(
        spots_from_layout(layout),
        cores_from_layout(layout),
        occupied,
        core_name,
        ev_preferred=a.ev_preferred or household_has_ev,
        top_k=_TOP_K,
    )
    # 빈자리 없음도 확정 근거 → note가 아니라 카드로 승격(⓪ 계약, trace_home_device 관례).
    quote = _quote(nearest) if nearest else _NO_SPOT_NOTE
    return ToolResult(
        card=ToolCard(title=_CARD_TITLE, quote=quote, source_kind=_SOURCE_KIND, data=_data(nearest))
    )


def find_nearest_available_parking_tool() -> Tool:
    return Tool(
        name="find_nearest_available_parking",
        description=(
            "본인 동에서 가까운 빈 주차자리(면 번호·종류·거리)를 조회한다. 주차할 곳을 "
            "찾을 때 쓴다 — 전기차 충전 자리를 원하면 ev_preferred를 true로 준다. "
            "차량 등록·정산 등 다른 주차 질문에는 쓰지 않는다."
        ),
        args_model=NearestParkingArgs,
        run=_find_nearest_parking,
        allowed_roles=RESIDENT_ROLES,
    )


# ── find_my_vehicle (H19-2) ──────────────────────────────────────────────────

_MY_SOURCE_KIND = "tool:find_my_vehicle"
_MY_CARD_TITLE = "내 차량 위치"
_NO_VEHICLE_NOTE = "등록된 차량이 없습니다."
_NOT_PARKED = "주차장에 없음(등록만 됨)"
_PARK_HINT = "지금 주차할 곳이 필요하면 가까운 빈자리를 물어보세요."
_UNKNOWN_MODEL = "차량"
_UNKNOWN_ENTRY = "입차 시각 미상"

_MINUTES_PER_HOUR = 60
_HOURS_PER_DAY = 24

# 본인 세대 차량만 — household_id는 LLM 인자가 아니라 로그인 사용자에서 유도한다(규칙 3·4).
# **plate_enc(차량번호 암호문)는 SELECT하지 않는다**: 답변에 번호판이 필요 없고, 도구 결과는
# 그대로 LLM 프롬프트에 들어가므로 애초에 꺼내오지 않는 것이 유일한 안전장치다(규칙 2).
_MY_VEHICLES_SQL = text(
    "SELECT v.model, v.spot_no, v.entry_at FROM parking_vehicles v "
    "WHERE v.tenant_id = :tid AND v.household_id = "
    "(SELECT u.household_id FROM users u WHERE u.id = :uid AND u.tenant_id = :tid) "
    "ORDER BY v.spot_no NULLS LAST, v.created_at"
)


class MyVehicleArgs(BaseModel):
    """인자 없음 — 대상은 로그인 세대로 고정이고, 8B는 인자가 늘수록 라우팅이 무너진다(R22)."""


def _elapsed(entry_at: datetime | None) -> str:
    """입차 경과 표기 — 시각 계산은 도구가 한다(LLM에 raw timestamp를 주면 오독한다)."""
    if entry_at is None:
        return _UNKNOWN_ENTRY
    minutes = int((datetime.now(UTC) - entry_at).total_seconds() // 60)
    if minutes < 1:
        return "방금 전 입차"
    if minutes < _MINUTES_PER_HOUR:
        return f"{minutes}분 전 입차"
    hours, mins = divmod(minutes, _MINUTES_PER_HOUR)
    if hours < _HOURS_PER_DAY:
        return f"{hours}시간 전 입차" if mins == 0 else f"{hours}시간 {mins}분 전 입차"
    return f"{hours // _HOURS_PER_DAY}일 전 입차"


def _core_distances(layout: dict[str, Any], core_name: str) -> dict[str, int]:
    """면 번호 → 내 동 코어까지 거리(m). 코어·배치도가 없으면 빈 dict(거리 없이 답한다)."""
    core = next((c for c in cores_from_layout(layout) if c.name == core_name), None)
    if core is None:
        return {}
    anchor = core_center(core)
    return {s.no: round(distance_px(s, *anchor) * PX_TO_M) for s in spots_from_layout(layout)}


def _vehicle_line(r: Any, core_name: str, distances: dict[str, int]) -> str:
    model = r.model or _UNKNOWN_MODEL
    if not r.spot_no:
        return f"- {model}: {_NOT_PARKED}"
    distance_m = distances.get(r.spot_no)
    detail = _elapsed(r.entry_at)
    if distance_m is not None:
        detail += f" · {core_name} 승강기까지 약 {distance_m}m"
    return f"- {model}: {r.spot_no}면 ({detail})"


def _my_vehicle_data(rows: list[Any], core_name: str, distances: dict[str, int]) -> dict[str, Any]:
    """화면용 차량 목록(ADR-0025 §6) — quote와 같은 값을 필드로 쪼갠 것뿐. LLM 미노출."""
    return {
        "kind": "my_vehicles",
        "core": core_name,
        "vehicles": [
            {
                "model": r.model or _UNKNOWN_MODEL,
                "spotNo": r.spot_no,
                "parkedSince": _elapsed(r.entry_at) if r.spot_no else None,
                "distanceM": distances.get(r.spot_no) if r.spot_no else None,
            }
            for r in rows
        ],
    }


async def _find_my_vehicle(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    hh = (
        await deps.session.execute(_HOUSEHOLD_DONG_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})
    ).first()
    if hh is None or not hh.building_name:
        return ToolResult(note=_NO_HOUSEHOLD_NOTE)
    core_name = f"{hh.building_name}동"

    rows = (
        await deps.session.execute(_MY_VEHICLES_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})
    ).all()
    # 차량 0대는 도구가 답할 게 없는 상태 — 등록 안내는 폴백(담당자 연결)이 맡는다.
    if not rows:
        return ToolResult(note=_NO_VEHICLE_NOTE)

    layout_row = (await deps.session.execute(_LAYOUT_SQL, {"tid": ctx.tenant_id})).first()
    layout = cast(dict[str, Any], layout_row.layout) if layout_row and layout_row.layout else {}
    distances = _core_distances(layout, core_name)

    lines = [f"내 차량 {len(rows)}대:"] + [_vehicle_line(r, core_name, distances) for r in rows]
    # 전부 미주차도 DB가 확인한 확정 근거 → note가 아니라 카드(⓪ 계약).
    if not any(r.spot_no for r in rows):
        lines.append(_PARK_HINT)
    lines.append("(데모 데이터 · 출처: parking_vehicles 등록·점유 현황)")

    return ToolResult(
        card=ToolCard(
            title=_MY_CARD_TITLE,
            quote="\n".join(lines),
            source_kind=_MY_SOURCE_KIND,
            data=_my_vehicle_data(list(rows), core_name, distances),
        )
    )


def find_my_vehicle_tool() -> Tool:
    """내 차 위치(H19-2, 시나리오 RES-1).

    번호판은 반환하지 않는다 — `plate_enc`는 SELECT조차 하지 않는다(규칙 2: 개인정보 LLM
    미전송). 시나리오 답변 예시엔 번호판이 있었지만 차종+면 번호면 본인 차 식별에 충분하고,
    도구 결과는 그대로 프롬프트에 실리므로 의도적으로 뺐다.
    """
    return Tool(
        name="find_my_vehicle",
        # find_nearest_available_parking과의 경계가 이 도구의 전부다(R22 — 의미 경합이
        # 라우팅을 무너뜨린다). 가르는 축은 **이미 댄 차냐 댈 자리냐**다.
        description=(
            "내 차가 지금 어디에 주차돼 있는지 조회한다(본인 세대 등록 차량의 면 번호·"
            "입차 경과 시간·우리 동 승강기까지 거리). '내 차 어디 있어', '차 어디 댔지', "
            "'내 차 위치'처럼 이미 세워 둔 차를 찾을 때 쓴다. "
            "주차할 빈자리를 찾는 질문에는 쓰지 않는다."
        ),
        args_model=MyVehicleArgs,
        run=_find_my_vehicle,
        allowed_roles=RESIDENT_ROLES,
    )
