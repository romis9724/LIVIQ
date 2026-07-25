"""주차장 대시보드 통합 — 실 PG (H9-5).

CRUD·현황 집계·인가 매트릭스(STAFF·RESIDENT 403)·tenant 격리(타 단지 미노출/404)·차량번호
봉투 암호화 왕복(plate_enc는 암호문, 응답은 복호 평문)을 본다. 세대·명부는 기존 시드 재사용.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_tenant_session, visibilities_for
from app.main import create_app
from app.pii import PiiCrypto, get_pii_crypto
from conftest import MANAGER_USER_ID, TENANT_ID, seed_tenant
from httpx import ASGITransport
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Household, ParkingAssignment

TENANT_B_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
_KEK = base64.b64encode(b"0" * 32).decode()
_PLATE = "12가3456"


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
    app.dependency_overrides[get_pii_crypto] = lambda: PiiCrypto(_KEK)
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncSession, dict]]:
    # 세대 (3,301)·(3,302)·(5,501) + MANAGER(세대 미부착) → total_households = 3.
    mapping = await seed_tenant(db_session)
    yield db_session, mapping


async def _create(
    client: httpx.AsyncClient,
    household_id: uuid.UUID,
    *,
    location_code: str | None = "B2-A-12",
    plate: str | None = _PLATE,
) -> httpx.Response:
    return await client.post(
        "/admin/parking",
        json={
            "household_id": str(household_id),
            "location_code": location_code,
            "plate": plate,
        },
    )


# ── CRUD happy path + 대시보드 ────────────────────────────────────────────────


async def test_create_and_dashboard(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:
        created = await _create(c, hid)
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["household_id"] == str(hid)
        assert body["location_code"] == "B2-A-12"
        assert body["plate"] == _PLATE

        dash = await c.get("/admin/parking")
    assert dash.status_code == 200
    data = dash.json()
    assert data["summary"] == {
        "total_spaces": 1,
        "total_vehicles": 1,
        "assigned_households": 1,
        "unassigned_households": 2,  # 3세대 − 배정 1세대
    }
    assert len(data["households"]) == 1
    row = data["households"][0]
    assert row["household_id"] == str(hid)
    assert (row["dong"], row["floor"], row["ho"]) == ("101", 3, 301)
    assert row["unit_label"] == "101동 301호"
    assert row["space_count"] == 1
    assert row["vehicle_count"] == 1
    assert row["assignments"][0]["location_code"] == "B2-A-12"
    assert row["assignments"][0]["plate"] == _PLATE


async def test_crud_lifecycle(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:
        aid = (await _create(c, hid)).json()["id"]
        # 수정 — 위치 교체 + 차량번호 클리어(plate=null).
        patched = await c.patch(
            f"/admin/parking/{aid}", json={"location_code": "B3-C-07", "plate": None}
        )
        assert patched.status_code == 200
        assert patched.json()["location_code"] == "B3-C-07"
        assert patched.json()["plate"] is None
        dash = (await c.get("/admin/parking")).json()
        row = dash["households"][0]
        assert row["vehicle_count"] == 0  # 차량 클리어됨
        assert row["assignments"][0]["location_code"] == "B3-C-07"
        # 삭제 — leaf.
        assert (await c.delete(f"/admin/parking/{aid}")).status_code == 204
        empty = (await c.get("/admin/parking")).json()
    assert empty["households"] == []
    assert empty["summary"]["total_spaces"] == 0
    assert empty["summary"]["assigned_households"] == 0


# ── 차량번호 암호화 (CRITICAL) ────────────────────────────────────────────────


async def test_plate_encrypted_at_rest(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:
        aid = uuid.UUID((await _create(c, hid)).json()["id"])
    # DB의 plate_enc는 bytes 암호문 — 평문 차량번호가 그대로 들어있으면 안 된다(규칙 2).
    enc = await session.scalar(
        select(ParkingAssignment.plate_enc).where(ParkingAssignment.id == aid)
    )
    assert isinstance(enc, bytes)
    assert _PLATE.encode("utf-8") not in enc
    # 응답은 복호 평문.
    async with _client(session) as c:
        dash = (await c.get("/admin/parking")).json()
    assert dash["households"][0]["assignments"][0]["plate"] == _PLATE


async def test_plate_absent_excluded_from_vehicle_count(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:
        created = await _create(c, hid, plate=None)
        assert created.json()["plate"] is None
        dash = (await c.get("/admin/parking")).json()
    # 차량번호 없는 주차면 — space는 세지만 vehicle은 제외.
    assert dash["summary"]["total_spaces"] == 1
    assert dash["summary"]["total_vehicles"] == 0
    assert dash["households"][0]["space_count"] == 1
    assert dash["households"][0]["vehicle_count"] == 0


# ── 집계 정합 ─────────────────────────────────────────────────────────────────


async def test_summary_aggregation(seeded: tuple) -> None:
    session, mapping = seeded
    h1, h2 = mapping[(3, 301)], mapping[(3, 302)]
    async with _client(session) as c:
        await _create(c, h1, location_code="B2-A-12", plate=_PLATE)  # 차량 있음
        await _create(c, h1, location_code="B2-A-13", plate=None)  # 차량 없음
        await _create(c, h2, location_code="B1-B-01", plate="34나5678")  # 차량 있음
        dash = (await c.get("/admin/parking")).json()
    assert dash["summary"] == {
        "total_spaces": 3,
        "total_vehicles": 2,
        "assigned_households": 2,
        "unassigned_households": 1,  # 3세대 − 배정 2세대
    }
    by_hid = {row["household_id"]: row for row in dash["households"]}
    assert by_hid[str(h1)]["space_count"] == 2
    assert by_hid[str(h1)]["vehicle_count"] == 1
    assert by_hid[str(h2)]["space_count"] == 1


async def test_household_delete_cascades_assignments(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:
        await _create(c, hid)
    # 세대 삭제(FK ondelete CASCADE) → 배정도 사라진다.
    await session.execute(
        delete(Household).where(Household.tenant_id == TENANT_ID, Household.id == hid)
    )
    await session.flush()
    async with _client(session) as c:
        dash = (await c.get("/admin/parking")).json()
    assert dash["households"] == []
    assert dash["summary"]["total_spaces"] == 0


# ── 검증·404 ──────────────────────────────────────────────────────────────────


async def test_create_unknown_household_404(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        r = await _create(c, uuid.uuid4())
    assert r.status_code == 404


async def test_patch_delete_unknown_404(seeded: tuple) -> None:
    session, _ = seeded
    bogus = uuid.uuid4()
    async with _client(session) as c:
        assert (
            await c.patch(f"/admin/parking/{bogus}", json={"location_code": None, "plate": None})
        ).status_code == 404
        assert (await c.delete(f"/admin/parking/{bogus}")).status_code == 404


# ── 인가 매트릭스 ─────────────────────────────────────────────────────────────


async def test_staff_and_resident_denied(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    for role in ("STAFF", "RESIDENT"):
        async with _client(session, roles=(role,)) as c:
            assert (await c.get("/admin/parking")).status_code == 403
            assert (await _create(c, hid)).status_code == 403


# ── tenant 격리 (CRITICAL) ────────────────────────────────────────────────────


async def test_cross_tenant_not_visible(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:  # 단지A 배정 생성
        aid = (await _create(c, hid)).json()["id"]

    async with _client(session, tenant_id=TENANT_B_ID) as c:  # 다른 단지 컨텍스트
        dash = (await c.get("/admin/parking")).json()
        assert dash["households"] == []
        assert dash["summary"] == {
            "total_spaces": 0,
            "total_vehicles": 0,
            "assigned_households": 0,
            "unassigned_households": 0,
        }
        # 타 단지 배정은 존재조차 노출하지 않는다 → 404.
        assert (
            await c.patch(f"/admin/parking/{aid}", json={"location_code": None, "plate": None})
        ).status_code == 404
        assert (await c.delete(f"/admin/parking/{aid}")).status_code == 404
