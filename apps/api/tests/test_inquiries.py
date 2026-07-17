"""inquiries 라우터 통합 — 실 PG. 접수·분류·소유권·배정·상태 머신·알림 (docs/01 §13)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_tenant_session
from app.main import create_app
from conftest import BUILDING_ID, TENANT_ID
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import (
    Building,
    Household,
    InquiryCategory,
    Notification,
    Tenant,
    User,
    UserRole,
)

AUTHOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
OTHER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
MANAGER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
STAFF_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000004")
FACILITY_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000005")
CATEGORY_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    session.add(Building(id=BUILDING_ID, tenant_id=TENANT_ID, name="101", floors=15))
    await session.flush()
    h1 = uuid.uuid4()
    h2 = uuid.uuid4()
    for hid, unit in ((h1, 301), (h2, 302)):
        session.add(
            Household(
                id=hid,
                tenant_id=TENANT_ID,
                building_id=BUILDING_ID,
                floor=3,
                unit_no=unit,
                status="active",
            )
        )
    await session.flush()
    users: tuple[tuple[uuid.UUID, uuid.UUID | None, str], ...] = (
        (AUTHOR_ID, h1, "RESIDENT"),
        (OTHER_ID, h2, "RESIDENT"),
        (MANAGER_ID, None, "MANAGER"),
        (STAFF_ID, None, "STAFF"),
        (FACILITY_ID, None, "FACILITY"),
    )
    for uid, member_hid, _role in users:
        session.add(User(id=uid, tenant_id=TENANT_ID, household_id=member_hid, status="active"))
    await session.flush()
    for uid, _hid, role in users:
        session.add(UserRole(tenant_id=TENANT_ID, user_id=uid, role=role))
    session.add(InquiryCategory(id=CATEGORY_ID, tenant_id=TENANT_ID, name="누수"))
    await session.flush()


def _make_client(
    db_session: AsyncSession, user_id: uuid.UUID, roles: tuple[str, ...]
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(TENANT_ID, user_id, roles=roles)
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed(db_session)
    yield db_session


async def _create(client: httpx.AsyncClient, *, title: str, body: str) -> dict[str, object]:
    response = await client.post("/inquiries", json={"title": title, "body": body})
    assert response.status_code == 201, response.text
    return response.json()


# ── 접수 + 분류 + 이벤트 ────────────────────────────────────────────────────


async def test_create_sets_received_classifies_and_records_events(
    seeded: AsyncSession,
) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as c:
        created = await _create(c, title="천장 누수", body="물이 샙니다")
        assert created["status"] == "received"
        assert created["ai_priority"] == "urgent"
        assert created["ai_suggested_category_id"] == str(CATEGORY_ID)

        events = (await c.get(f"/inquiries/{created['id']}/events")).json()["items"]
        assert [e["type"] for e in events] == ["created", "ai_classified"]
        assert events[1]["payload"]["priority"] == "urgent"


async def test_create_without_household_returns_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("RESIDENT",)) as c:  # MANAGER=세대 없음
        response = await c.post("/inquiries", json={"title": "t", "body": "b"})
    assert response.status_code == 422


# ── 소유권(CRITICAL) ────────────────────────────────────────────────────────


async def test_resident_lists_only_own_and_cannot_read_others(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        mine = await _create(author, title="주차 문의", body="이중주차")
    async with _make_client(seeded, OTHER_ID, ("RESIDENT",)) as other:
        listed = (await other.get("/inquiries")).json()["items"]
        assert listed == []  # 남의 민원 안 보임(§13.3)
        assert (await other.get(f"/inquiries/{mine['id']}")).status_code == 404
        assert (await other.get(f"/inquiries/{mine['id']}/events")).status_code == 404


# ── 교차 역할 ──────────────────────────────────────────────────────────────


async def test_resident_forbidden_on_admin_endpoints(seeded: AsyncSession) -> None:
    fake = uuid.uuid4()
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as c:
        assert (await c.get("/admin/inquiries")).status_code == 403
        assert (
            await c.post(f"/admin/inquiries/{fake}/assign", json={"assignee_user_id": str(fake)})
        ).status_code == 403
        assert (
            await c.post(f"/admin/inquiries/{fake}/status", json={"status": "assigned"})
        ).status_code == 403


# ── 관리자 목록 필터 ────────────────────────────────────────────────────────


async def test_admin_list_filters_by_status(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        received = await _create(author, title="대기", body="b")
        moved = await _create(author, title="진행", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await mgr.post(f"/admin/inquiries/{moved['id']}/status", json={"status": "in_progress"})
        listed = (await mgr.get("/admin/inquiries", params={"status": "received"})).json()["items"]
        assert [i["id"] for i in listed] == [received["id"]]
        progress = (await mgr.get("/admin/inquiries", params={"status": "in_progress"})).json()[
            "items"
        ]
        assert [i["id"] for i in progress] == [moved["id"]]


# ── 배정 ──────────────────────────────────────────────────────────────────


async def test_assign_transitions_records_event_and_notifies(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="누수", body="새요")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/assign",
            json={"assignee_user_id": str(FACILITY_ID)},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "assigned"
        assert response.json()["assignee_user_id"] == str(FACILITY_ID)

        events = (await mgr.get(f"/inquiries/{inquiry['id']}/events")).json()["items"]
        assert events[-1]["type"] == "assigned"

    notif = await seeded.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == AUTHOR_ID, Notification.type == "inquiry_status")
    )
    assert notif == 1


async def test_assign_to_resident_rejected_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/assign",
            json={"assignee_user_id": str(OTHER_ID)},  # RESIDENT는 배정 불가
        )
    assert response.status_code == 422


# ── 상태 머신 ──────────────────────────────────────────────────────────────


async def test_status_forward_records_payload(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/assign",
            json={"assignee_user_id": str(STAFF_ID)},
        )
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/status", json={"status": "in_progress"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "in_progress"

        events = (await mgr.get(f"/inquiries/{inquiry['id']}/events")).json()["items"]
        last = events[-1]
        assert last["type"] == "status_changed"
        assert last["payload"] == {"from": "assigned", "to": "in_progress"}


async def test_staff_cannot_move_status_backward(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await mgr.post(f"/admin/inquiries/{inquiry['id']}/status", json={"status": "in_progress"})
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        response = await staff.post(
            f"/admin/inquiries/{inquiry['id']}/status", json={"status": "received"}
        )
    assert response.status_code == 403


async def test_manager_can_move_status_backward(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await mgr.post(f"/admin/inquiries/{inquiry['id']}/status", json={"status": "in_progress"})
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/status", json={"status": "assigned"}
        )
    assert response.status_code == 200
    assert response.json()["status"] == "assigned"
