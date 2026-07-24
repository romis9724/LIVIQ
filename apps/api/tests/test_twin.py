"""단지 트윈 통합 — 실 PG (H9-1, ADR-0019).

units.json 업로드 매칭 리포트·전체 교체 멱등·occupancy 오버레이 집계·/me has_twin +
인가 매트릭스(STAFF·RESIDENT 403)·tenant 격리(타 단지 미노출)를 본다. geometry만 신규 —
세대·세대원은 기존 명부 재사용.
"""

from __future__ import annotations

import base64
import decimal
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from app.deps import (
    RequestContext,
    get_auth_lookup_session,
    get_context,
    get_session_raw,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from app.pii import PiiCrypto, get_pii_crypto
from app.session import SessionData
from conftest import MANAGER_USER_ID, TENANT_ID, seed_tenant
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import (
    Building,
    Facility,
    Fee,
    Household,
    HouseholdGeometry,
    Inquiry,
    PiiVault,
    User,
)

TENANT_B_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
_KEK = base64.b64encode(b"0" * 32).decode()

_POLY_2D = [[127.25, 36.48], [127.26, 36.49]]
_POLY_3D = [[127.25, 36.48, 3.0], [127.26, 36.49, 3.0]]


def _unit(dong: str, floor: int, ho: int, *, malformed: bool = False) -> dict[str, Any]:
    """units.json unit 1건. 무시돼야 할 필드(unit_id·line·resident)를 섞어 extra=ignore를 증명."""
    unit: dict[str, Any] = {
        "unit_id": f"{dong}-{ho}",
        "dong": dong,
        "floor": floor,
        "line": 1,
        "ho": ho,
        "ho_str": f"{ho}호",
        "unit_type": "84A",
        "area_m2": 84.7,
        "polygon_3d": _POLY_3D,
        "base_z": 3.0,
        "floor_height": 2.8,
        "resident": {"name": "무시돼야-함"},
    }
    if not malformed:  # malformed = 필수 polygon_2d 누락 → 검증 실패(unmatched 취급)
        unit["polygon_2d"] = _POLY_2D
    return unit


def _units_body() -> bytes:
    """단지A(동 101) 기준: (3,301)·(3,302) 매칭 · (9,999) 세대 없음 · (5,555) 검증 실패."""
    payload = {
        "metadata": {"crs": "EPSG:4326"},
        "units": [
            _unit("101동", 3, 301),
            _unit("101동", 3, 302),
            _unit("101동", 9, 999),
            _unit("101동", 5, 555, malformed=True),
        ],
    }
    return json.dumps(payload).encode()


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


def _me_client(
    db_session: AsyncSession,
    *,
    tenant_id: uuid.UUID = TENANT_ID,
) -> httpx.AsyncClient:
    """/me 전용 — 세션·auth_lookup·crypto만 오버라이드(redis·로그인 우회)."""
    app = create_app()
    fake = SessionData(
        tenant_id=str(tenant_id), user_id=str(MANAGER_USER_ID), roles=("MANAGER",), status="active"
    )
    app.dependency_overrides[get_session_raw] = lambda: fake
    app.dependency_overrides[get_auth_lookup_session] = lambda: db_session
    app.dependency_overrides[get_pii_crypto] = lambda: PiiCrypto(_KEK)
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[tuple[AsyncSession, dict]]:
    mapping = await seed_tenant(db_session)
    yield db_session, mapping


async def _upload(client: httpx.AsyncClient) -> httpx.Response:
    return await client.post(
        "/admin/twin/geometry",
        files={"file": ("units.json", _units_body(), "application/json")},
    )


# ── 업로드 매칭 리포트 ────────────────────────────────────────────────────────


async def test_upload_reports_matched_and_unmatched(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        r = await _upload(c)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_units"] == 4
    assert body["matched"] == 2
    assert body["unmatched"] == 2  # 세대 없음(9,999) + 검증 실패(5,555)
    assert body["unmatched_samples"] == ["101동-9-999", "101동-5-555"]
    assert body["replaced"] is False


async def test_upload_rejects_non_json_400(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        r = await c.post(
            "/admin/twin/geometry",
            files={"file": ("x.json", b"not json at all", "application/json")},
        )
    assert r.status_code == 400


async def test_upload_rejects_missing_units_key_400(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        r = await c.post(
            "/admin/twin/geometry",
            files={"file": ("x.json", json.dumps({"metadata": {}}).encode(), "application/json")},
        )
    assert r.status_code == 400


# ── 조회 + 전체 교체 멱등 ─────────────────────────────────────────────────────


async def test_list_geometry_joins_household_coords(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        await _upload(c)
        listed = await c.get("/admin/twin/geometry")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] == 2
    items = body["items"]
    assert [(i["floor"], i["unit_no"]) for i in items] == [(3, 301), (3, 302)]
    first = items[0]
    assert first["building_name"] == "101"
    assert first["polygon_2d"] == _POLY_2D
    assert first["polygon_3d"] == _POLY_3D
    assert first["base_z"] == 3.0
    assert first["floor_height"] == 2.8
    assert first["area_m2"] == 84.7
    assert first["unit_type_label"] == "84A"


async def test_reupload_replaces_and_is_idempotent(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        first = await _upload(c)
        assert first.json()["replaced"] is False
        second = await _upload(c)
        assert second.json()["replaced"] is True  # 기존분 교체됨
        listed = await c.get("/admin/twin/geometry")
    # 세대당 1건 — 재업로드해도 중복 누적 없음.
    assert listed.json()["total"] == 2


# ── occupancy 오버레이 ────────────────────────────────────────────────────────


async def test_overlay_occupancy_counts_household_members(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:
        await _upload(c)
        # geometry 있는 세대(3,301)에 세대원 배정 — 집계 대상 상태 2 + 제외 상태 1.
        session.add(User(tenant_id=TENANT_ID, household_id=hid, status="active"))
        session.add(User(tenant_id=TENANT_ID, household_id=hid, status="pre_registered"))
        session.add(User(tenant_id=TENANT_ID, household_id=hid, status="inactive"))
        await session.flush()
        ov = await c.get("/admin/twin/overlay", params={"kind": "occupancy"})
    assert ov.status_code == 200
    body = ov.json()
    assert body["kind"] == "occupancy"
    # (3,301)=2명 · (3,302)는 세대원 0 → 키 생략(0으로 채우지 않음).
    assert body["values"] == {str(hid): 2.0}


async def test_overlay_unsupported_kind_400(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:
        await _upload(c)
        r = await c.get("/admin/twin/overlay", params={"kind": "bogus"})
    assert r.status_code == 400


# ── inquiries·fees·facilities 오버레이 (H9-2) ─────────────────────────────────


def _add_inquiry(session: AsyncSession, household_id: uuid.UUID, *, status: str) -> None:
    session.add(
        Inquiry(
            tenant_id=TENANT_ID,
            household_id=household_id,
            author_user_id=MANAGER_USER_ID,
            title="누수 신고",
            body="본문",
            status=status,
            priority="normal",
        )
    )


def _add_fee(session: AsyncSession, household_id: uuid.UUID, period: str, total: int) -> None:
    session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=household_id,
            period=period,
            breakdown=[{"name": "합계", "level": 0, "amount": total}],
            total_amount=total,
            source="excel",
        )
    )


async def test_overlay_inquiries_counts_open(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session) as c:
        await _upload(c)  # geometry: (3,301)·(3,302)
        # (3,301): 미종결 2건 + 완료 1건(제외). (3,302): 0건 → 키 생략.
        _add_inquiry(session, hid, status="received")
        _add_inquiry(session, hid, status="in_progress")
        _add_inquiry(session, hid, status="done")
        await session.flush()
        ov = await c.get("/admin/twin/overlay", params={"kind": "inquiries"})
    assert ov.status_code == 200
    body = ov.json()
    assert body["kind"] == "inquiries"
    assert body["values"] == {str(hid): 2.0}


async def test_overlay_fees_uses_latest_period(seeded: tuple) -> None:
    session, mapping = seeded
    h1, h2 = mapping[(3, 301)], mapping[(3, 302)]
    async with _client(session) as c:
        await _upload(c)  # geometry: (3,301)·(3,302)
        _add_fee(session, h1, "2026-05", 100000)  # 과거 월 — 제외
        _add_fee(session, h1, "2026-06", 120000)  # 당월(최신)
        _add_fee(session, h2, "2026-06", 130000)
        await session.flush()
        ov = await c.get("/admin/twin/overlay", params={"kind": "fees"})
    assert ov.status_code == 200
    assert ov.json()["values"] == {str(h1): 120000.0, str(h2): 130000.0}


async def test_overlay_facilities_dong_worst_severity(seeded: tuple) -> None:
    session, mapping = seeded
    # 101동 세대 1곳 + 202동 세대 1곳에 geometry 직접 적재(동 매칭 스코프 확인).
    b202 = uuid.uuid4()
    session.add(Building(id=b202, tenant_id=TENANT_ID, name="202", floors=10))
    await session.flush()
    h202 = uuid.uuid4()
    session.add(
        Household(
            id=h202, tenant_id=TENANT_ID, building_id=b202, floor=3, unit_no=301, status="active"
        )
    )
    await session.flush()
    h101 = mapping[(3, 301)]
    for hid in (h101, h202):
        session.add(
            HouseholdGeometry(
                tenant_id=TENANT_ID,
                household_id=hid,
                polygon_2d=_POLY_2D,
                polygon_3d=_POLY_3D,
                base_z=decimal.Decimal("3.0"),
                floor_height=decimal.Decimal("2.8"),
            )
        )
    # 101동 설비: fault(2) + check(1) → 최악 2. 미매칭 location은 세대 오버레이 제외.
    session.add(Facility(tenant_id=TENANT_ID, name="EV", location="101동", status="fault"))
    session.add(Facility(tenant_id=TENANT_ID, name="복도등", location="101동", status="check"))
    session.add(Facility(tenant_id=TENANT_ID, name="정문", location="관리사무소", status="risk"))
    await session.flush()
    async with _client(session) as c:
        ov = await c.get("/admin/twin/overlay", params={"kind": "facilities"})
    assert ov.status_code == 200
    # 101동 세대만 최악 2.0 · 202동(매칭 설비 없음)·미매칭 location(관리사무소) 생략.
    assert ov.json()["values"] == {str(h101): 2.0}


# ── 세대 상세 (H9-2) ──────────────────────────────────────────────────────────


async def _add_member(
    session: AsyncSession,
    crypto: PiiCrypto,
    household_id: uuid.UUID,
    *,
    name: str,
    role: str = "RESIDENT",
    status: str = "active",
) -> None:
    dek = await crypto.get_dek(session, TENANT_ID)
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id, tenant_id=TENANT_ID, name_enc=crypto.encrypt(dek, name), key_version=1
        )
    )
    session.add(
        User(
            id=uuid.uuid4(),
            tenant_id=TENANT_ID,
            household_id=household_id,
            status=status,
            pii_ref=vault_id,
        )
    )
    await session.flush()


async def test_household_detail_masks_members_and_aggregates(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    crypto = PiiCrypto(_KEK)
    await _add_member(session, crypto, hid, name="홍길동")
    _add_inquiry(session, hid, status="received")
    _add_inquiry(session, hid, status="done")  # 종결 — 제외
    _add_fee(session, hid, "2026-05", 100000)
    _add_fee(session, hid, "2026-06", 120000)  # 최신 → current_fee
    await session.flush()
    async with _client(session) as c:
        r = await c.get(f"/admin/twin/households/{hid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["building_name"] == "101"
    assert (body["floor"], body["unit_no"]) == (3, 301)
    # 실명 마스킹만 — 원문 부재(규칙 2·6).
    assert body["members"] == [{"name_masked": "홍*동", "role": "RESIDENT", "status": "active"}]
    assert "홍길동" not in r.text
    # 미종결 민원만.
    assert len(body["open_inquiries"]) == 1
    assert body["open_inquiries"][0]["status"] == "received"
    # 당월(최신 period) 관리비.
    assert body["current_fee"] == {"period": "2026-06", "total": 120000}


async def test_household_detail_no_data_defaults(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 302)]
    async with _client(session) as c:
        r = await c.get(f"/admin/twin/households/{hid}")
    assert r.status_code == 200
    body = r.json()
    assert body["members"] == []
    assert body["open_inquiries"] == []
    assert body["current_fee"] is None
    assert body["unit_type_label"] is None


async def test_household_detail_cross_tenant_404(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]  # 단지A 세대
    async with _client(session, tenant_id=TENANT_B_ID) as c:  # 다른 단지 컨텍스트
        r = await c.get(f"/admin/twin/households/{hid}")
    assert r.status_code == 404  # 존재 노출 금지


async def test_household_detail_staff_and_resident_denied(seeded: tuple) -> None:
    session, mapping = seeded
    hid = mapping[(3, 301)]
    async with _client(session, roles=("STAFF",)) as c:
        assert (await c.get(f"/admin/twin/households/{hid}")).status_code == 403
    async with _client(session, roles=("RESIDENT",)) as c:
        assert (await c.get(f"/admin/twin/households/{hid}")).status_code == 403


# ── /me has_twin ─────────────────────────────────────────────────────────────


async def test_me_has_twin_false_without_geometry(seeded: tuple) -> None:
    session, _ = seeded
    async with _me_client(session) as c:
        me = await c.get("/me")
    assert me.status_code == 200
    assert me.json()["has_twin"] is False


async def test_me_has_twin_true_with_geometry(seeded: tuple) -> None:
    session, mapping = seeded
    session.add(
        HouseholdGeometry(
            tenant_id=TENANT_ID,
            household_id=mapping[(3, 301)],
            polygon_2d=_POLY_2D,
            polygon_3d=_POLY_3D,
            base_z=decimal.Decimal("3.0"),
            floor_height=decimal.Decimal("2.8"),
        )
    )
    await session.flush()
    async with _me_client(session) as c:
        me = await c.get("/me")
    assert me.status_code == 200
    assert me.json()["has_twin"] is True


# ── 인가 매트릭스 ─────────────────────────────────────────────────────────────


async def test_staff_denied(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session, roles=("STAFF",)) as c:
        assert (await c.get("/admin/twin/geometry")).status_code == 403
        assert (await _upload(c)).status_code == 403
        assert (await c.get("/admin/twin/overlay", params={"kind": "occupancy"})).status_code == 403


async def test_resident_denied(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session, roles=("RESIDENT",)) as c:
        assert (await c.get("/admin/twin/geometry")).status_code == 403


# ── tenant 격리 ──────────────────────────────────────────────────────────────


async def test_cross_tenant_geometry_not_visible(seeded: tuple) -> None:
    session, _ = seeded
    async with _client(session) as c:  # 단지A geometry 적재
        await _upload(c)

    async with _client(session, tenant_id=TENANT_B_ID) as c:  # 다른 단지 컨텍스트
        listed = await c.get("/admin/twin/geometry")
        assert listed.json() == {"items": [], "total": 0}
        ov = await c.get("/admin/twin/overlay", params={"kind": "occupancy"})
        assert ov.json()["values"] == {}
