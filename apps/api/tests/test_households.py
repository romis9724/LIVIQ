"""동/호수 관리 통합 — 실 PG (H8-5).

동·세대 CRUD·층호 범위 일괄 생성(멱등)·범위 검증·인가 매트릭스(STAFF·RESIDENT 403)·tenant
격리·삭제 보호(CRITICAL: 세대에 입주민/명부·관리비 연결 시 409·동에 세대 있으면 409)를 본다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import (
    RequestContext,
    get_context,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from conftest import MANAGER_USER_ID, TENANT_ID
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Fee, Tenant, User

TENANT_B_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()


def _client(
    db_session: AsyncSession,
    *,
    roles: tuple[str, ...] = ("MANAGER",),
    tenant_id: uuid.UUID = TENANT_ID,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        tenant_id, MANAGER_USER_ID, roles=roles, visibilities=visibilities_for(roles)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed(db_session)
    yield db_session


async def _make_building(client: httpx.AsyncClient, name: str = "101", floors: int = 15) -> str:
    r = await client.post("/admin/buildings", json={"name": name, "floors": floors})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── 동 CRUD ──────────────────────────────────────────────────────────────────


async def test_create_building_and_list_with_counts(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 2, "unit_start": 1, "unit_end": 1},
        )
        listed = await c.get("/admin/buildings")
    assert listed.status_code == 200
    items = {b["name"]: b for b in listed.json()["items"]}
    assert items["101"]["floors"] == 15
    assert items["101"]["household_count"] == 2


async def test_create_building_duplicate_name_409(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        await _make_building(c, name="102")
        dup = await c.post("/admin/buildings", json={"name": "102"})
    assert dup.status_code == 409


async def test_patch_building_name_and_floors(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c, name="103", floors=10)
        r = await c.patch(f"/admin/buildings/{bid}", json={"name": "103동", "floors": 20})
    assert r.status_code == 200
    assert r.json()["name"] == "103동" and r.json()["floors"] == 20


async def test_delete_building_with_households_409(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 1, "unit_start": 1, "unit_end": 1},
        )
        r = await c.delete(f"/admin/buildings/{bid}")
    assert r.status_code == 409


async def test_delete_empty_building_204(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        r = await c.delete(f"/admin/buildings/{bid}")
    assert r.status_code == 204


# ── expand_household_grid (순수) ──────────────────────────────────────────────


def test_expand_household_grid_composes_full_unit_no() -> None:
    """호 순번(1~N) → 완전 호수(floor*100+순번). seed·온보딩과 같은 체계."""
    from app.schemas.households import expand_household_grid

    assert expand_household_grid(2, 2, 1, 3) == [(2, 201), (2, 202), (2, 203)]
    assert expand_household_grid(10, 10, 1, 3) == [(10, 1001), (10, 1002), (10, 1003)]
    # 층 오름차순, 그 안에서 호 순번 오름차순.
    assert expand_household_grid(1, 2, 1, 2) == [(1, 101), (1, 102), (2, 201), (2, 202)]


# ── 세대 일괄 생성 ────────────────────────────────────────────────────────────


async def test_bulk_create_range_grid(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        # 1~3층 × 1~2호 = 6세대.
        r = await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 3, "unit_start": 1, "unit_end": 2},
        )
        assert r.status_code == 201, r.text
        assert r.json() == {"created": 6, "skipped": 0}
        listed = await c.get(f"/admin/buildings/{bid}/households")
    body = listed.json()
    assert body["building"]["name"] == "101"
    assert len(body["items"]) == 6
    # 층·호 오름차순 + unit_no는 완전 호수(floor*100+순번): 1층 101·102, 2층 201·202, 3층 301·302.
    assert [(i["floor"], i["unit_no"]) for i in body["items"]] == [
        (1, 101),
        (1, 102),
        (2, 201),
        (2, 202),
        (3, 301),
        (3, 302),
    ]
    assert body["items"][0] == {
        "id": body["items"][0]["id"],
        "floor": 1,
        "unit_no": 101,
        "status": "active",
    }


async def test_bulk_create_is_idempotent(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        payload = {"floor_start": 1, "floor_end": 2, "unit_start": 1, "unit_end": 2}
        first = await c.post(f"/admin/buildings/{bid}/households", json=payload)
        assert first.json() == {"created": 4, "skipped": 0}
        # 겹치는 범위 재요청 — 기존은 skip, 새 층만 생성.
        second = await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 3, "unit_start": 1, "unit_end": 2},
        )
    assert second.json() == {"created": 2, "skipped": 4}


async def test_bulk_create_reversed_range_422(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        r = await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 5, "floor_end": 1, "unit_start": 1, "unit_end": 1},
        )
    assert r.status_code == 422


async def test_bulk_create_over_limit_422(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        # 200층 × 99호 = 19800 > 2000 상한.
        r = await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 200, "unit_start": 1, "unit_end": 99},
        )
    assert r.status_code == 422


# ── 세대 수정 ─────────────────────────────────────────────────────────────────


async def test_patch_household_move_and_status(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 1, "unit_start": 1, "unit_end": 1},
        )
        hid = (await c.get(f"/admin/buildings/{bid}/households")).json()["items"][0]["id"]
        r = await c.patch(f"/admin/households/{hid}", json={"floor": 9, "status": "inactive"})
    assert r.status_code == 200
    assert r.json()["floor"] == 9 and r.json()["status"] == "inactive"


async def test_patch_household_duplicate_unit_409(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        # 1층 1~2호 → (1,101)·(1,102).
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 1, "unit_start": 1, "unit_end": 2},
        )
        items = (await c.get(f"/admin/buildings/{bid}/households")).json()["items"]
        # 102호를 101호로 바꾸면 같은 동에 이미 있는 101호와 중복.
        target = next(i for i in items if i["unit_no"] == 102)
        r = await c.patch(f"/admin/households/{target['id']}", json={"unit_no": 101})
    assert r.status_code == 409


# ── 삭제 보호 (CRITICAL) ──────────────────────────────────────────────────────


async def test_delete_household_blocked_by_resident_user(seeded: AsyncSession) -> None:
    """세대에 입주민/명부(pre_registered users)가 연결돼 있으면 409 — FK 보호 핵심."""
    async with _client(seeded) as c:
        bid = await _make_building(c)
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 1, "unit_start": 1, "unit_end": 1},
        )
        hid = (await c.get(f"/admin/buildings/{bid}/households")).json()["items"][0]["id"]
        # 명부(pre_registered) 사용자 연결.
        seeded.add(User(tenant_id=TENANT_ID, household_id=uuid.UUID(hid), status="pre_registered"))
        await seeded.flush()
        r = await c.delete(f"/admin/households/{hid}")
    assert r.status_code == 409
    assert "입주민" in r.json()["detail"]


async def test_delete_household_blocked_by_fee(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 1, "unit_start": 1, "unit_end": 1},
        )
        hid = (await c.get(f"/admin/buildings/{bid}/households")).json()["items"][0]["id"]
        seeded.add(
            Fee(
                tenant_id=TENANT_ID,
                household_id=uuid.UUID(hid),
                period="2026-01",
                source="excel",
            )
        )
        await seeded.flush()
        r = await c.delete(f"/admin/households/{hid}")
    assert r.status_code == 409
    assert "관리비" in r.json()["detail"]


async def test_delete_unlinked_household_204(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        bid = await _make_building(c)
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 1, "unit_start": 1, "unit_end": 1},
        )
        hid = (await c.get(f"/admin/buildings/{bid}/households")).json()["items"][0]["id"]
        r = await c.delete(f"/admin/households/{hid}")
        assert r.status_code == 204
        remaining = (await c.get(f"/admin/buildings/{bid}/households")).json()["items"]
    assert remaining == []


# ── 인가 매트릭스 ─────────────────────────────────────────────────────────────


async def test_staff_denied(seeded: AsyncSession) -> None:
    async with _client(seeded, roles=("STAFF",)) as c:
        assert (await c.get("/admin/buildings")).status_code == 403
        assert (await c.post("/admin/buildings", json={"name": "x"})).status_code == 403


async def test_resident_denied(seeded: AsyncSession) -> None:
    async with _client(seeded, roles=("RESIDENT",)) as c:
        assert (await c.get("/admin/buildings")).status_code == 403


# ── tenant 격리 ──────────────────────────────────────────────────────────────


async def test_cross_tenant_access_404(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:  # 단지A 동·세대 생성
        bid = await _make_building(c)
        await c.post(
            f"/admin/buildings/{bid}/households",
            json={"floor_start": 1, "floor_end": 1, "unit_start": 1, "unit_end": 1},
        )
        hid = (await c.get(f"/admin/buildings/{bid}/households")).json()["items"][0]["id"]

    async with _client(seeded, tenant_id=TENANT_B_ID) as c:  # 다른 단지 컨텍스트
        assert (await c.get("/admin/buildings")).json()["items"] == []
        assert (await c.get(f"/admin/buildings/{bid}/households")).status_code == 404
        assert (await c.patch(f"/admin/households/{hid}", json={"floor": 2})).status_code == 404
        assert (await c.delete(f"/admin/households/{hid}")).status_code == 404
        assert (await c.delete(f"/admin/buildings/{bid}")).status_code == 404
