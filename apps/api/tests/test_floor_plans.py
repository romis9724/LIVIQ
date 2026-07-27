"""floor_plans 라우터 통합 — 실 PG (H13-3).

본인 세대 직행(라벨 정규화 매칭 → unit_type → floor_plan → base 장치)·소유권 격리
(CRITICAL — 타 세대·타 tenant 미노출)·인가(RESIDENT 전용)·404 분기(세대 없음·geometry
없음·라벨 매칭 실패·도면 없음)를 본다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_storage, get_tenant_session, visibilities_for
from app.main import create_app
from conftest import MANAGER_USER_ID, TENANT_ID, USER_ID, FakeStorage, seed_tenant
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import (
    Building,
    FloorPlan,
    Household,
    HouseholdGeometry,
    PlanDevice,
    Tenant,
    UnitType,
    User,
)

TENANT_B_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
_DUMMY_POLYGON_2D = [[0, 0]]
_DUMMY_POLYGON_3D = [[0, 0, 0]]


def _client(
    db_session: AsyncSession,
    storage: FakeStorage,
    *,
    roles: tuple[str, ...] = ("RESIDENT",),
    user_id: uuid.UUID = USER_ID,
    tenant_id: uuid.UUID = TENANT_ID,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        tenant_id, user_id, roles=roles, visibilities=visibilities_for(roles)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: storage
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _add_resident(
    session: AsyncSession,
    *,
    user_id: uuid.UUID = USER_ID,
    tenant_id: uuid.UUID = TENANT_ID,
    household_id: uuid.UUID | None,
) -> None:
    session.add(
        User(id=user_id, tenant_id=tenant_id, status="active", household_id=household_id)
    )
    await session.flush()


async def _add_geometry(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    household_id: uuid.UUID,
    unit_type_label: str | None,
) -> None:
    session.add(
        HouseholdGeometry(
            tenant_id=tenant_id,
            household_id=household_id,
            polygon_2d=_DUMMY_POLYGON_2D,
            polygon_3d=_DUMMY_POLYGON_3D,
            base_z=0,
            floor_height=3,
            unit_type_label=unit_type_label,
        )
    )
    await session.flush()


async def _seed_plan(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID = TENANT_ID,
    unit_type_name: str,
    room_devices: int,
) -> FloorPlan:
    """unit_type + floor_plan + room 타입 base 장치 N개(구분용 room 이름 포함)."""
    unit_type = UnitType(tenant_id=tenant_id, name=unit_type_name)
    session.add(unit_type)
    await session.flush()
    plan = FloorPlan(
        tenant_id=tenant_id,
        scope="unit_type",
        unit_type_id=unit_type.id,
        image_key=f"{tenant_id}/floor-plans/{unit_type_name}/v1.jpg",
        image_width=923,
        image_height=676,
        version=1,
    )
    session.add(plan)
    await session.flush()
    session.add_all(
        [
            PlanDevice(
                tenant_id=tenant_id,
                floor_plan_id=plan.id,
                action="base",
                device_type="room",
                x=10 + i,
                y=20 + i,
                room=f"방{i}",
                dir=None,
            )
            for i in range(room_devices)
        ]
    )
    await session.flush()
    return plan


@pytest_asyncio.fixture
async def households(db_session: AsyncSession) -> AsyncIterator[dict[tuple[int, int], uuid.UUID]]:
    hmap = await seed_tenant(db_session)
    yield hmap


# ── 정상 경로 ─────────────────────────────────────────────────────────────────


async def test_resident_gets_own_floor_plan(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    hid = households[(3, 301)]
    await _seed_plan(db_session, unit_type_name="84M", room_devices=3)
    await _add_geometry(db_session, household_id=hid, unit_type_label="84M(공공임대)")
    await _add_resident(db_session, household_id=hid)

    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan"]["unit_type_name"] == "84M"
    assert body["plan"]["image_width"] == 923
    assert body["plan"]["image_height"] == 676
    assert body["plan"]["image_url"].startswith("fake-signed://")
    assert len(body["devices"]) == 3
    assert {d["room"] for d in body["devices"]} == {"방0", "방1", "방2"}
    assert all(d["device_type"] == "room" for d in body["devices"])


async def test_room_dir_device_fields_present(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    hid = households[(3, 301)]
    plan = await _seed_plan(db_session, unit_type_name="84M", room_devices=0)
    db_session.add(
        PlanDevice(
            tenant_id=TENANT_ID,
            floor_plan_id=plan.id,
            action="base",
            device_type="콘센트",
            x=100,
            y=200,
            room="안방",
            dir="left",
            label="안방 콘센트",
        )
    )
    await db_session.flush()
    await _add_geometry(db_session, household_id=hid, unit_type_label="84M")
    await _add_resident(db_session, household_id=hid)

    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 200
    device = resp.json()["devices"][0]
    assert device["device_type"] == "콘센트"
    assert device["room"] == "안방"
    assert device["dir"] == "left"
    assert device["label"] == "안방 콘센트"


async def test_non_base_and_override_devices_excluded(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    """household_id가 채워진 오버라이드 행·action!=base 행은 H13-3 범위 밖 — 응답에서 제외."""
    hid = households[(3, 301)]
    plan = await _seed_plan(db_session, unit_type_name="84M", room_devices=1)
    db_session.add_all(
        [
            PlanDevice(
                tenant_id=TENANT_ID,
                floor_plan_id=plan.id,
                household_id=hid,  # 세대 오버라이드 — H13-3 미구현 범위
                action="add",
                device_type="콘센트",
                x=1,
                y=1,
            ),
            PlanDevice(
                tenant_id=TENANT_ID,
                floor_plan_id=plan.id,
                action="hide",
                device_type="콘센트",
                x=2,
                y=2,
            ),
        ]
    )
    await db_session.flush()
    await _add_geometry(db_session, household_id=hid, unit_type_label="84M")
    await _add_resident(db_session, household_id=hid)

    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 200
    assert len(resp.json()["devices"]) == 1  # 시드한 room 장치 1개만


# ── 404 분기 ─────────────────────────────────────────────────────────────────


async def test_no_household_404(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    await _add_resident(db_session, household_id=None)
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 404


async def test_geometry_missing_404(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    hid = households[(3, 301)]
    await _add_resident(db_session, household_id=hid)
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 404


async def test_label_mismatch_404(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    hid = households[(3, 301)]
    await _seed_plan(db_session, unit_type_name="84M", room_devices=1)
    await _add_geometry(db_session, household_id=hid, unit_type_label="미지타입(옵션)")
    await _add_resident(db_session, household_id=hid)
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 404


async def test_floor_plan_missing_404(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    hid = households[(3, 301)]
    # unit_type만 있고 floor_plan은 없는 상태.
    db_session.add(UnitType(tenant_id=TENANT_ID, name="84M"))
    await db_session.flush()
    await _add_geometry(db_session, household_id=hid, unit_type_label="84M")
    await _add_resident(db_session, household_id=hid)
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 404


# ── 라벨 정규화 ───────────────────────────────────────────────────────────────


async def test_label_normalization_strips_parenthetical(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    hid = households[(3, 301)]
    await _seed_plan(db_session, unit_type_name="84M", room_devices=1)
    await _add_geometry(db_session, household_id=hid, unit_type_label="84M(공공임대)")
    await _add_resident(db_session, household_id=hid)
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 200
    assert resp.json()["plan"]["unit_type_name"] == "84M"


# ── 인가 ─────────────────────────────────────────────────────────────────────


async def test_manager_and_staff_forbidden(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    for role in ("MANAGER", "STAFF"):
        async with _client(
            db_session, FakeStorage(), roles=(role,), user_id=MANAGER_USER_ID
        ) as c:
            resp = await c.get("/me/floor-plan")
        assert resp.status_code == 403


# ── 소유권·tenant 격리(CRITICAL) ──────────────────────────────────────────────


async def test_resident_cannot_see_other_household_via_context(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    """세션 household_id 기준 직행이라 다른 household의 도면을 볼 파라미터 경로 자체가 없다.

    (엔드포인트가 household/plan id를 전혀 받지 않음 — 우회 표면 부재를 계약으로 확인.)
    """
    hid_a = households[(3, 301)]
    hid_b = households[(3, 302)]
    await _seed_plan(db_session, unit_type_name="84M", room_devices=2)
    await _seed_plan(db_session, unit_type_name="59C", room_devices=5)
    await _add_geometry(db_session, household_id=hid_a, unit_type_label="84M")
    await _add_geometry(db_session, household_id=hid_b, unit_type_label="59C")
    await _add_resident(db_session, household_id=hid_a)

    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["plan"]["unit_type_name"] == "84M"  # 본인(hid_a) 세대만 — hid_b(59C) 아님
    assert len(body["devices"]) == 2


async def test_cross_tenant_isolation(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    """동일 user_id라도 세션 tenant가 다르면 세대 매칭 자체가 안 된다(RLS 경계 밖 앱 검증)."""
    hid = households[(3, 301)]
    await _seed_plan(db_session, unit_type_name="84M", room_devices=1)
    await _add_geometry(db_session, household_id=hid, unit_type_label="84M")
    await _add_resident(db_session, household_id=hid)

    async with _client(db_session, FakeStorage(), tenant_id=TENANT_B_ID) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 404


async def test_cross_tenant_same_unit_type_name_isolated(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    """단지A·단지B에 동명(84M) unit_type이 있어도 각자 자기 tenant의 floor_plan만 본다."""
    hid_a = households[(3, 301)]
    await _seed_plan(db_session, unit_type_name="84M", room_devices=2)
    await _add_geometry(db_session, household_id=hid_a, unit_type_label="84M")
    await _add_resident(db_session, household_id=hid_a)

    # 단지B 전용 데이터 — 다른 device 수로 구분.
    hid_b = uuid.uuid4()
    user_b = uuid.uuid4()
    building_b = uuid.uuid4()
    db_session.add(Tenant(id=TENANT_B_ID, name="단지B", status="active"))
    await db_session.flush()
    db_session.add(Building(id=building_b, tenant_id=TENANT_B_ID, name="201", floors=10))
    await db_session.flush()
    db_session.add(
        Household(
            id=hid_b, tenant_id=TENANT_B_ID, building_id=building_b, floor=1, unit_no=101,
            status="active",
        )
    )
    await db_session.flush()
    await _seed_plan(db_session, tenant_id=TENANT_B_ID, unit_type_name="84M", room_devices=7)
    await _add_geometry(
        db_session, tenant_id=TENANT_B_ID, household_id=hid_b, unit_type_label="84M"
    )
    await _add_resident(db_session, user_id=user_b, tenant_id=TENANT_B_ID, household_id=hid_b)

    async with _client(db_session, FakeStorage(), user_id=user_b, tenant_id=TENANT_B_ID) as c:
        resp = await c.get("/me/floor-plan")
    assert resp.status_code == 200
    assert len(resp.json()["devices"]) == 7  # 단지A(2개)가 아니라 단지B(7개) 것만
