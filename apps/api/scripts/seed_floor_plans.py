"""seed_floor_plans.py — 세대타입 평면도 시드 (H13-3, apt-facility-finder 프로토타입 포팅).

TYPE_A(84M) 어노테이션(scripts/data/floor_plan_annotations.py — annotations.js 이식본)을
그대로 적재하고, TYPE_B(59C)는 원본의 mirrorType 로직(좌우반전: x→W-x, dir left↔right
반전)을 이식해 파생한다. unit_types 행이 없으면 생성하고, floor_plans(scope=unit_type)·
plan_devices(action=base)는 delete-then-insert로 전량 교체한다(재실행해도 개수가 늘지
않음 — 트윈 geometry 업로드와 동일한 전체 교체 관례). 이미지 파일 2장은 S3(MinIO)에 put.

도면+마커 스냅샷을 `outbox_events(aggregate_type='floor_plan')`에 도메인 행과 같은
트랜잭션으로 기록한다(H13-6, `app.routers.floor_plans._floor_plan_snapshot` 재사용 —
이중 쓰기 금지). floor_plan 행 자체를 delete-then-insert하므로 재실행마다 새 pg_id로
`created` 이벤트가 나가고, 이전 실행의 Neo4j FloorPlan 노드는 자동 정리되지 않는다
(ponytail: 재시딩이 잦아지면 tombstone 이벤트도 함께 내보내는 정리가 필요).

입력(원본 프로토타입, LIVIQ 밖):
    ../apt-facility-finder/아파트 도면_clean.jpg   (TYPE_A, 923x676)
    ../apt-facility-finder/아파트 도면_B타입.jpg   (TYPE_B, 923x676)
    ../apt-facility-finder/annotations.js          (→ scripts/data/floor_plan_annotations.py 이식본)

실행(DATABASE_URL·S3_*는 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync python scripts/seed_floor_plans.py [--tenant-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import decimal
import sys
import uuid
from pathlib import Path
from typing import Any

from app.outbox import record_outbox
from app.routers.floor_plans import _floor_plan_snapshot
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import FloorPlan, PlanDevice, Tenant, UnitType

# scripts/data는 패키지가 아니라 폴더(namespace package) — 이 파일 자신의 디렉터리를
# sys.path에 넣어 invocation 방식(uv run/직접 실행)과 무관하게 임포트되게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.floor_plan_annotations import (  # noqa: E402
    ELEMENTS,
    IMAGE_FILE,
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    ROOMS,
)

# 파일럿 단지(첫마을 4단지 푸르지오) — 다른 시드 스크립트와 동일 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

# LIVIQ와 형제 디렉터리(같은 워크스페이스 루트) — 원본 프로토타입 산출물 위치.
SOURCE_DIR = Path(__file__).resolve().parents[3].parent / "apt-facility-finder"

_FLIP_DIR = {"left": "right", "right": "left"}

# unit_types 매핑(브리프 결정) — A타입은 원본 그대로, B타입은 좌우반전 미러.
UNIT_TYPE_SPECS: tuple[dict[str, Any], ...] = (
    {"name": "84M", "image_file": IMAGE_FILE, "mirror": False},
    {"name": "59C", "image_file": "아파트 도면_B타입.jpg", "mirror": True},
)


def _dec(value: float) -> decimal.Decimal:
    """float → Decimal(asyncpg는 Numeric 컬럼에 Decimal만 허용, twin.py와 동일 관례)."""
    return decimal.Decimal(str(value))


def _mirrored(rooms: list[dict[str, Any]], elements: list[dict[str, Any]], width: int) -> tuple[
    list[dict[str, Any]], list[dict[str, Any]]
]:
    """원본 mirrorType 이식 — x→width-x, 화살표 방향 좌우 반전(annotations.js와 동일 규칙)."""
    mirrored_rooms = [{**r, "x": width - r["x"]} for r in rooms]
    mirrored_elements = []
    for e in elements:
        m = {**e, "x": width - e["x"]}
        if m.get("dir"):
            m["dir"] = _FLIP_DIR.get(m["dir"], m["dir"])
        mirrored_elements.append(m)
    return mirrored_rooms, mirrored_elements


def _rooms_and_elements_for(
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not spec["mirror"]:
        return ROOMS, ELEMENTS
    return _mirrored(ROOMS, ELEMENTS, IMAGE_WIDTH)


async def _get_or_create_unit_type(
    session: AsyncSession, tenant_id: uuid.UUID, name: str
) -> UnitType:
    unit_type = await session.scalar(
        select(UnitType).where(UnitType.tenant_id == tenant_id, UnitType.name == name)
    )
    if unit_type is None:
        unit_type = UnitType(tenant_id=tenant_id, name=name)
        session.add(unit_type)
        await session.flush()
    return unit_type


async def _replace_floor_plan(
    session: AsyncSession,
    storage: Any,
    tenant_id: uuid.UUID,
    unit_type: UnitType,
    image_file: str,
    rooms: list[dict[str, Any]],
    elements: list[dict[str, Any]],
    complex_name: str | None,
) -> tuple[int, int]:
    """해당 unit_type의 기존 floor_plan+devices 전체 교체 후 신규 적재.

    (room 수, device 총 수) 반환.
    """
    existing = await session.scalar(
        select(FloorPlan).where(
            FloorPlan.tenant_id == tenant_id,
            FloorPlan.scope == "unit_type",
            FloorPlan.unit_type_id == unit_type.id,
        )
    )
    if existing is not None:
        await session.execute(
            delete(PlanDevice).where(
                PlanDevice.tenant_id == tenant_id, PlanDevice.floor_plan_id == existing.id
            )
        )
        await session.execute(delete(FloorPlan).where(FloorPlan.id == existing.id))
        await session.flush()

    image_key = f"{tenant_id}/floor-plans/{unit_type.name}/v1.jpg"
    image_path = SOURCE_DIR / image_file
    if not image_path.exists():
        raise SystemExit(f"원본 이미지를 찾을 수 없습니다: {image_path}")
    await storage.put(image_key, image_path.read_bytes())

    plan = FloorPlan(
        tenant_id=tenant_id,
        scope="unit_type",
        unit_type_id=unit_type.id,
        image_key=image_key,
        image_width=IMAGE_WIDTH,
        image_height=IMAGE_HEIGHT,
        version=1,
    )
    session.add(plan)
    await session.flush()

    devices = [
        PlanDevice(
            tenant_id=tenant_id,
            floor_plan_id=plan.id,
            action="base",
            device_type="room",
            x=_dec(r["x"]),
            y=_dec(r["y"]),
            room=r["name"],
        )
        for r in rooms
    ] + [
        PlanDevice(
            tenant_id=tenant_id,
            floor_plan_id=plan.id,
            action="base",
            device_type=e["type"],
            x=_dec(e["x"]),
            y=_dec(e["y"]),
            room=e["room"],
            dir=e.get("dir"),
        )
        for e in elements
    ]
    session.add_all(devices)
    await session.flush()
    await record_outbox(
        session,
        tenant_id=tenant_id,
        aggregate_type="floor_plan",
        aggregate_id=plan.id,
        event_type="created",
        payload=_floor_plan_snapshot(unit_type.name, plan, devices, complex_name),
    )
    return len(rooms), len(devices)


def _report(rows: list[tuple[str, int, int]]) -> None:
    for name, room_count, device_count in rows:
        print(f"{name}: rooms {room_count} · devices(전체) {device_count} · 이미지 업로드 완료")


async def _run(tenant_id: uuid.UUID) -> None:
    from app.deps import get_storage

    engine = create_engine()
    factory = create_session_factory(engine)
    storage = get_storage()
    try:
        async with factory() as session, session.begin():
            complex_name = await session.scalar(
                select(Tenant.name).where(Tenant.id == tenant_id)
            )
            if complex_name is None:
                raise SystemExit(f"단지를 찾을 수 없습니다: {tenant_id}")
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            rows: list[tuple[str, int, int]] = []
            for spec in UNIT_TYPE_SPECS:
                unit_type = await _get_or_create_unit_type(session, tenant_id, spec["name"])
                rooms, elements = _rooms_and_elements_for(spec)
                room_count, device_count = await _replace_floor_plan(
                    session,
                    storage,
                    tenant_id,
                    unit_type,
                    spec["image_file"],
                    rooms,
                    elements,
                    complex_name,
                )
                rows.append((spec["name"], room_count, device_count))
        _report(rows)
        print(f"단지: {tenant_id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="세대타입 평면도 시드(H13-3)")
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ID,
        help=f"대상 단지 UUID (기본: 첫마을 4단지 {DEFAULT_TENANT_ID})",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id))


if __name__ == "__main__":
    main()
