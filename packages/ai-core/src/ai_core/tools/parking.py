"""find_nearest_available_parking — 본인 동에서 가까운 빈 주차자리 top_k (H15-4, ADR-0023 개정).

세대→동(PG authz)로 앵커 코어를 정하고, `parking_layouts`(면·코어)와 `parking_vehicles`
(spot_no가 있는 행 = 점유 중, SoR — H16)를 읽어 `geometry.nearest_available_spots`로
최근접 빈 면을 계산한다.
거리 계산은 도구가 확정한다 — LLM은 면·거리를 지어내지 않는다(규칙 8). 반환은 빈 면의
번호·종류·거리(m)뿐이라 타 입주민 PII가 없다. 읽기 전용(SELECT만).

세대·tenant는 ToolContext에서 오며 LLM 인자로 받지 않는다(규칙 3·4 — get_fees와 동일).
점유는 데모 데이터이므로 답변에 그 사실을 명시한다(규칙 1 — 출처=parking_vehicles.spot_no).
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import text

from ai_core.parking import Core, Spot, nearest_available_spots
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


class NearestParkingArgs(BaseModel):
    ev_preferred: bool = Field(
        False, description="전기차 충전 자리를 원하면 true (사용자가 전기차·충전 언급 시)"
    )


def _spots(layout: dict[str, Any]) -> list[Spot]:
    return [
        Spot(no=str(s["no"]), kind=str(s["kind"]), x=float(s["x"]), y=float(s["y"]))
        for s in layout.get("spots", [])
    ]


def _cores(layout: dict[str, Any]) -> list[Core]:
    return [
        Core(
            name=str(c["name"]),
            x=float(c["x"]),
            y=float(c["y"]),
            w=float(c["w"]),
            h=float(c["h"]),
        )
        for c in layout.get("cores", [])
    ]


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

    nearest = nearest_available_spots(
        _spots(layout),
        _cores(layout),
        occupied,
        core_name,
        ev_preferred=a.ev_preferred,
        top_k=_TOP_K,
    )
    # 빈자리 없음도 확정 근거 → note가 아니라 카드로 승격(⓪ 계약, trace_home_device 관례).
    quote = _quote(nearest) if nearest else _NO_SPOT_NOTE
    return ToolResult(card=ToolCard(title=_CARD_TITLE, quote=quote, source_kind=_SOURCE_KIND))


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
