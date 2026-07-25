"""주차장 대시보드 통합 — 실 PG (H9-5).

배치도 조회(미적재 시 null)·차량 목록(동·호 표시 포맷·정렬)·인가 매트릭스(STAFF·RESIDENT 403)·
tenant 격리(타 단지 미노출)·차량번호 봉투 암호화 왕복(plate_enc는 암호문, 응답은 복호 평문)을
본다. 세대·명부는 기존 시드 재사용.
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import ParkingLayout, ParkingVehicle

TENANT_B_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
_KEK = base64.b64encode(b"0" * 32).decode()
_PLATE = "205고9167"
_LAYOUT = {
    "viewBox": "0 0 3020 1082",
    "buildings": {"401동": {"outline": [[0, 0], [10, 0], [10, 10]], "cx": 5, "cy": 5}},
    "boxes": [{"label": "진입 램프 ⤵", "x": 100, "y": 1002, "w": 160, "h": 64}],
    "cores": [{"name": "401동", "x": 251, "y": 393.4, "w": 72, "h": 128}],
    "spots": [{"no": "001", "kind": "일반", "x": 100, "y": 162, "dir": "down"}],
}


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
    # 동 "101" · 세대 (3,301)·(3,302)·(5,501).
    mapping = await seed_tenant(db_session)
    yield db_session, mapping


async def _add_vehicle(
    session: AsyncSession,
    household_id: uuid.UUID,
    *,
    plate: str = _PLATE,
    model: str | None = "아이오닉5",
    is_ev: bool = True,
    tenant_id: uuid.UUID = TENANT_ID,
) -> uuid.UUID:
    """차량 직접 적재(운영 경로는 시드 스크립트 — 라우터는 읽기 전용)."""
    crypto = PiiCrypto(_KEK)
    dek = await crypto.get_dek(session, tenant_id)
    row = ParkingVehicle(
        tenant_id=tenant_id,
        household_id=household_id,
        plate_enc=crypto.encrypt(dek, plate),
        model=model,
        is_ev=is_ev,
    )
    session.add(row)
    await session.flush()
    return row.id


# ── 배치도 ────────────────────────────────────────────────────────────────────


async def test_layout_absent_returns_null(seeded: tuple) -> None:
    """미적재 단지는 404가 아니라 `{"layout": null}` — 프론트가 빈 상태를 렌더한다."""
    session, _ = seeded
    async with _client(session) as c:
        r = await c.get("/admin/parking/layout")
    assert r.status_code == 200
    assert r.json() == {"layout": None}


async def test_layout_round_trips(seeded: tuple) -> None:
    """적재된 배치도 페이로드를 그대로 반환한다(서버는 내용 해석 안 함)."""
    session, _ = seeded
    session.add(ParkingLayout(tenant_id=TENANT_ID, layout=_LAYOUT))
    await session.flush()
    async with _client(session) as c:
        r = await c.get("/admin/parking/layout")
    assert r.status_code == 200
    assert r.json()["layout"] == _LAYOUT


# ── 차량 목록 ─────────────────────────────────────────────────────────────────


async def test_vehicles_empty(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        r = await c.get("/admin/parking/vehicles")
    assert r.status_code == 200
    assert r.json() == {"vehicles": [], "total": 0}


async def test_vehicles_dong_ho_format(seeded: tuple) -> None:
    """dong·ho는 프로토타입 배치도 표시 포맷("101동"/"301호")."""
    session, mapping = seeded
    hid = mapping[(3, 301)]
    await _add_vehicle(session, hid)
    async with _client(session) as c:
        body = (await c.get("/admin/parking/vehicles")).json()
    assert body["total"] == 1
    item = body["vehicles"][0]
    assert (item["dong"], item["ho"]) == ("101동", "301호")
    assert item["household_id"] == str(hid)
    assert item["model"] == "아이오닉5"
    assert item["is_ev"] is True


async def test_vehicles_sorted_by_dong_ho(seeded: tuple) -> None:
    """동·호 오름차순 — 세대당 다건도 함께 나온다."""
    session, mapping = seeded
    await _add_vehicle(session, mapping[(5, 501)], plate="102노9973", model="G80", is_ev=False)
    await _add_vehicle(session, mapping[(3, 302)], plate="34나5678", model=None)
    await _add_vehicle(session, mapping[(3, 301)], plate=_PLATE)
    async with _client(session) as c:
        body = (await c.get("/admin/parking/vehicles")).json()
    assert [v["ho"] for v in body["vehicles"]] == ["301호", "302호", "501호"]
    assert body["total"] == 3


# ── 차량번호 암호화 (CRITICAL) ────────────────────────────────────────────────


async def test_plate_encrypted_at_rest(seeded: tuple) -> None:
    """DB의 plate_enc는 암호문(bytes) — 평문 차량번호가 들어있으면 안 된다(규칙 2)."""
    session, mapping = seeded
    vid = await _add_vehicle(session, mapping[(3, 301)])
    enc = await session.scalar(select(ParkingVehicle.plate_enc).where(ParkingVehicle.id == vid))
    assert isinstance(enc, bytes)
    assert _PLATE.encode("utf-8") not in enc
    # 응답은 복호 평문(관리자 전용).
    async with _client(session) as c:
        body = (await c.get("/admin/parking/vehicles")).json()
    assert body["vehicles"][0]["plate"] == _PLATE


# ── 인가 매트릭스 ─────────────────────────────────────────────────────────────


async def test_staff_and_resident_denied(seeded: tuple) -> None:
    session, _ = seeded
    for role in ("STAFF", "RESIDENT"):
        async with _client(session, roles=(role,)) as c:
            assert (await c.get("/admin/parking/layout")).status_code == 403
            assert (await c.get("/admin/parking/vehicles")).status_code == 403


# ── tenant 격리 (CRITICAL) ────────────────────────────────────────────────────


async def test_cross_tenant_not_visible(seeded: tuple) -> None:
    """단지A의 배치도·차량은 단지B 컨텍스트에 노출되지 않는다."""
    session, mapping = seeded
    session.add(ParkingLayout(tenant_id=TENANT_ID, layout=_LAYOUT))
    await _add_vehicle(session, mapping[(3, 301)])

    async with _client(session, tenant_id=TENANT_B_ID) as c:
        assert (await c.get("/admin/parking/layout")).json() == {"layout": None}
        assert (await c.get("/admin/parking/vehicles")).json() == {"vehicles": [], "total": 0}
