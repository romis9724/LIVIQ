"""inquiries 라우터 통합 — 실 PG. 접수·분류코드·소유권·배정·답변/피드백·상태 게이트 (ADR-0018)."""

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
    Code,
    CodeGroup,
    Household,
    Notification,
    Tenant,
    User,
    UserRole,
)

AUTHOR_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
OTHER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000002")
MANAGER_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000003")
STAFF_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000004")
STAFF2_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000005")  # 배정 대상(H7-2: STAFF)
# INQUIRY_CATEGORY 코드
CATEGORY_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")  # "설비" active
CATEGORY2_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")  # "하자" active
INACTIVE_CATEGORY_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000003")  # 비활성
# 다른 그룹(NOTICE_CATEGORY) 코드 — 그룹 불일치 422 검증용
NOTICE_CODE_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")


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
        (STAFF2_ID, None, "STAFF"),
    )
    for uid, member_hid, _role in users:
        session.add(User(id=uid, tenant_id=TENANT_ID, household_id=member_hid, status="active"))
    await session.flush()
    for uid, _hid, role in users:
        session.add(UserRole(tenant_id=TENANT_ID, user_id=uid, role=role))

    inquiry_group = CodeGroup(
        tenant_id=TENANT_ID, group_key="INQUIRY_CATEGORY", name="민원 카테고리", is_system=True
    )
    notice_group = CodeGroup(
        tenant_id=TENANT_ID, group_key="NOTICE_CATEGORY", name="공지 분류", is_system=True
    )
    session.add_all([inquiry_group, notice_group])
    await session.flush()
    session.add_all(
        [
            Code(
                id=CATEGORY_ID,
                tenant_id=TENANT_ID,
                group_id=inquiry_group.id,
                code="설비",
                label="설비",
                sort_order=0,
            ),
            Code(
                id=CATEGORY2_ID,
                tenant_id=TENANT_ID,
                group_id=inquiry_group.id,
                code="하자",
                label="하자",
                sort_order=1,
            ),
            Code(
                id=INACTIVE_CATEGORY_ID,
                tenant_id=TENANT_ID,
                group_id=inquiry_group.id,
                code="폐기",
                label="폐기",
                sort_order=2,
                active=False,
            ),
            Code(
                id=NOTICE_CODE_ID,
                tenant_id=TENANT_ID,
                group_id=notice_group.id,
                code="일반",
                label="일반",
                sort_order=0,
            ),
        ]
    )
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


async def _create(
    client: httpx.AsyncClient,
    *,
    title: str,
    body: str,
    category_code_id: uuid.UUID | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {"title": title, "body": body}
    if category_code_id is not None:
        payload["category_code_id"] = str(category_code_id)
    response = await client.post("/inquiries", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def _assign(
    client: httpx.AsyncClient, inquiry_id: object, assignee: uuid.UUID
) -> dict[str, object]:
    response = await client.post(
        f"/admin/inquiries/{inquiry_id}/assign", json={"assignee_user_id": str(assignee)}
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── 접수 + 이벤트(AI 제거) ──────────────────────────────────────────────────


async def test_create_sets_received_no_priority_and_records_created_event(
    seeded: AsyncSession,
) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as c:
        created = await _create(c, title="천장 누수", body="물이 샙니다")
        assert created["status"] == "received"
        assert created["priority"] is None
        assert created["category_code_id"] is None

        events = (await c.get(f"/inquiries/{created['id']}/events")).json()["items"]
        assert [e["type"] for e in events] == ["created"]  # ai_classified 없음(ADR-0018)


async def test_create_with_valid_category_code(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as c:
        created = await _create(c, title="설비 문의", body="b", category_code_id=CATEGORY_ID)
        assert created["category_code_id"] == str(CATEGORY_ID)


async def test_create_rejects_foreign_group_code_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as c:
        response = await c.post(
            "/inquiries",
            json={"title": "t", "body": "b", "category_code_id": str(NOTICE_CODE_ID)},
        )
    assert response.status_code == 422  # NOTICE_CATEGORY 코드는 민원 분류 아님


async def test_create_rejects_unknown_category_code_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as c:
        response = await c.post(
            "/inquiries",
            json={"title": "t", "body": "b", "category_code_id": str(uuid.uuid4())},
        )
    assert response.status_code == 422  # 미존재/타 tenant 코드


async def test_create_without_household_returns_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("RESIDENT",)) as c:  # MANAGER=세대 없음
        response = await c.post("/inquiries", json={"title": "t", "body": "b"})
    assert response.status_code == 422


# ── 카테고리 조회 ────────────────────────────────────────────────────────────


async def test_list_categories_returns_active_sorted(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as c:
        items = (await c.get("/inquiries/categories")).json()["items"]
    assert [i["label"] for i in items] == ["설비", "하자"]  # 비활성 제외·sort_order 순
    assert items[0]["id"] == str(CATEGORY_ID)


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
        assert (await c.post(f"/admin/inquiries/{fake}/ack")).status_code == 403
        assert (await c.post(f"/admin/inquiries/{fake}/complete")).status_code == 403


# ── 관리자 목록 필터 ────────────────────────────────────────────────────────


async def test_admin_list_filters_by_status(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        received = await _create(author, title="대기", body="b")
    moved_id = await _create_assign_progress(seeded)  # in_progress
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        listed = (await mgr.get("/admin/inquiries", params={"status": "received"})).json()["items"]
        assert [i["id"] for i in listed] == [received["id"]]
        progress = (await mgr.get("/admin/inquiries", params={"status": "in_progress"})).json()[
            "items"
        ]
        assert [i["id"] for i in progress] == [moved_id]


# ── 배정 ──────────────────────────────────────────────────────────────────


async def test_assign_transitions_records_event_and_notifies(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="누수", body="새요")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        result = await _assign(mgr, inquiry["id"], STAFF2_ID)
        assert result["status"] == "assigned"
        assert result["assignee_user_id"] == str(STAFF2_ID)

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


# ── 우선순위(수동) ──────────────────────────────────────────────────────────


async def test_priority_set_manually(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/priority", json={"priority": "urgent"}
        )
    assert response.status_code == 200
    assert response.json()["priority"] == "urgent"


# ── 답변(담당자→입주민) ─────────────────────────────────────────────────────


async def test_assignee_can_reply_and_notifies_author(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        response = await staff.post(
            f"/admin/inquiries/{inquiry['id']}/comments", json={"body": "확인 후 조치했습니다"}
        )
        assert response.status_code == 200
        events = (await staff.get(f"/inquiries/{inquiry['id']}/events")).json()["items"]
        reply = events[-1]
        assert reply["type"] == "comment"
        assert reply["payload"] == {"kind": "reply", "body": "확인 후 조치했습니다"}

    notif = await seeded.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == AUTHOR_ID, Notification.type == "inquiry_status")
    )
    assert notif == 2  # 배정 알림 1 + 답변 알림 1


async def test_non_assignee_staff_cannot_reply_403(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)
    async with _make_client(seeded, STAFF2_ID, ("STAFF",)) as other_staff:
        response = await other_staff.post(
            f"/admin/inquiries/{inquiry['id']}/comments", json={"body": "끼어들기"}
        )
    assert response.status_code == 403


async def test_manager_can_reply_override(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)  # 소장은 담당자 아님
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/comments", json={"body": "소장 답변"}
        )
    assert response.status_code == 200


# ── 피드백(입주민→담당자) ───────────────────────────────────────────────────


async def _create_assign_progress(seeded: AsyncSession) -> str:
    """접수→배정→담당자 ack(=처리중)까지 진행한 민원 id."""
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        acked = await staff.post(f"/admin/inquiries/{inquiry['id']}/ack")
        assert acked.status_code == 200 and acked.json()["status"] == "in_progress", acked.text
    return str(inquiry["id"])


async def _create_done(seeded: AsyncSession) -> str:
    """처리중 민원에 답변 1건 남기고 완료 처리한 민원 id."""
    inquiry_id = await _create_assign_progress(seeded)
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        replied = await staff.post(
            f"/admin/inquiries/{inquiry_id}/comments", json={"body": "처리 완료"}
        )
        assert replied.status_code == 200, replied.text
        done = await staff.post(f"/admin/inquiries/{inquiry_id}/complete")
        assert done.status_code == 200 and done.json()["status"] == "done", done.text
    return inquiry_id


async def test_author_feedback_in_progress_notifies_assignee(seeded: AsyncSession) -> None:
    inquiry_id = await _create_assign_progress(seeded)
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        response = await author.post(
            f"/inquiries/{inquiry_id}/comments", json={"body": "아직 물이 새요"}
        )
        assert response.status_code == 200
        events = (await author.get(f"/inquiries/{inquiry_id}/events")).json()["items"]
        assert events[-1]["payload"] == {"kind": "feedback", "body": "아직 물이 새요"}

    notif = await seeded.scalar(
        select(func.count())
        .select_from(Notification)
        .where(Notification.user_id == STAFF_ID, Notification.type == "inquiry_status")
    )
    assert notif == 1  # 담당자에게 피드백 알림


async def test_feedback_rejected_when_not_in_progress_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")  # received
        response = await author.post(
            f"/inquiries/{inquiry['id']}/comments", json={"body": "선접수"}
        )
    assert response.status_code == 422


async def test_feedback_by_non_author_404(seeded: AsyncSession) -> None:
    inquiry_id = await _create_assign_progress(seeded)
    async with _make_client(seeded, OTHER_ID, ("RESIDENT",)) as other:
        response = await other.post(f"/inquiries/{inquiry_id}/comments", json={"body": "남의 민원"})
    assert response.status_code == 404  # 격리 — 존재 여부 노출 안 함


async def test_feedback_allowed_when_reopened(seeded: AsyncSession) -> None:
    inquiry_id = await _create_done(seeded)
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        await author.post(f"/inquiries/{inquiry_id}/reopen")  # done → reopened
        response = await author.post(
            f"/inquiries/{inquiry_id}/comments", json={"body": "다시 문제입니다"}
        )
    assert response.status_code == 200  # reopened에서도 피드백 허용


# ── ack(열람 → 처리중) ─────────────────────────────────────────────────────


async def test_ack_by_assignee_when_assigned_transitions(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        acked = await staff.post(f"/admin/inquiries/{inquiry['id']}/ack")
        assert acked.status_code == 200
        assert acked.json()["status"] == "in_progress"

        events = (await staff.get(f"/inquiries/{inquiry['id']}/events")).json()["items"]
        last = events[-1]
        assert last["type"] == "status_changed"
        assert last["payload"] == {"from": "assigned", "to": "in_progress"}


async def test_ack_by_non_assignee_is_noop(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)
    async with _make_client(seeded, STAFF2_ID, ("STAFF",)) as other_staff:
        acked = await other_staff.post(f"/admin/inquiries/{inquiry['id']}/ack")
        assert acked.status_code == 200
        assert acked.json()["status"] == "assigned"  # no-op — 상태 유지


async def test_ack_by_manager_is_noop(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)  # 소장은 담당자 아님
        acked = await mgr.post(f"/admin/inquiries/{inquiry['id']}/ack")
        assert acked.status_code == 200
        assert acked.json()["status"] == "assigned"  # no-op


async def test_ack_on_done_is_noop(seeded: AsyncSession) -> None:
    inquiry_id = await _create_done(seeded)
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        acked = await staff.post(f"/admin/inquiries/{inquiry_id}/ack")
        assert acked.status_code == 200
        assert acked.json()["status"] == "done"  # no-op — 완료 유지


# ── complete(완료) ─────────────────────────────────────────────────────────


async def test_complete_requires_reply(seeded: AsyncSession) -> None:
    inquiry_id = await _create_assign_progress(seeded)
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        no_reply = await staff.post(f"/admin/inquiries/{inquiry_id}/complete")
        assert no_reply.status_code == 422  # 답변 없는 완료 금지

        await staff.post(f"/admin/inquiries/{inquiry_id}/comments", json={"body": "처리 완료"})
        done = await staff.post(f"/admin/inquiries/{inquiry_id}/complete")
        assert done.status_code == 200
        assert done.json()["status"] == "done"


async def test_complete_rejected_when_not_in_progress_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        await _assign(mgr, inquiry["id"], STAFF_ID)  # assigned(처리중 아님)
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        response = await staff.post(f"/admin/inquiries/{inquiry['id']}/complete")
    assert response.status_code == 422


async def test_complete_from_reopened(seeded: AsyncSession) -> None:
    inquiry_id = await _create_done(seeded)
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        await author.post(f"/inquiries/{inquiry_id}/reopen")  # done → reopened
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as staff:
        done = await staff.post(f"/admin/inquiries/{inquiry_id}/complete")  # reply는 이미 있음
    assert done.status_code == 200
    assert done.json()["status"] == "done"


async def test_complete_notifies_author(seeded: AsyncSession) -> None:
    await _create_done(seeded)
    notif = await seeded.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == AUTHOR_ID,
            Notification.type == "inquiry_status",
            Notification.title == "민원이 완료 처리되었습니다",
        )
    )
    assert notif == 1


# ── reopen(재접수) ─────────────────────────────────────────────────────────


async def test_reopen_by_author_when_done(seeded: AsyncSession) -> None:
    inquiry_id = await _create_done(seeded)
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        response = await author.post(f"/inquiries/{inquiry_id}/reopen")
        assert response.status_code == 200
        assert response.json()["status"] == "reopened"

        events = (await author.get(f"/inquiries/{inquiry_id}/events")).json()["items"]
        last = events[-1]
        assert last["type"] == "status_changed"
        assert last["payload"] == {"from": "done", "to": "reopened"}

    notif = await seeded.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.user_id == STAFF_ID,
            Notification.title == "담당 민원이 재접수되었습니다",
        )
    )
    assert notif == 1  # 담당자에게 재접수 알림


async def test_reopen_by_non_author_404(seeded: AsyncSession) -> None:
    inquiry_id = await _create_done(seeded)
    async with _make_client(seeded, OTHER_ID, ("RESIDENT",)) as other:
        response = await other.post(f"/inquiries/{inquiry_id}/reopen")
    assert response.status_code == 404  # 격리 — 존재 여부 노출 안 함


async def test_reopen_rejected_when_not_done_422(seeded: AsyncSession) -> None:
    inquiry_id = await _create_assign_progress(seeded)  # in_progress
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        response = await author.post(f"/inquiries/{inquiry_id}/reopen")
    assert response.status_code == 422


# ── category(분류 수정) ─────────────────────────────────────────────────────


async def test_category_set_by_admin(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/category",
            json={"category_code_id": str(CATEGORY_ID)},
        )
    assert response.status_code == 200
    assert response.json()["category_code_id"] == str(CATEGORY_ID)


async def test_category_clear_with_null(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b", category_code_id=CATEGORY_ID)
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/category", json={"category_code_id": None}
        )
    assert response.status_code == 200
    assert response.json()["category_code_id"] is None


async def test_category_rejects_foreign_group_code_422(seeded: AsyncSession) -> None:
    async with _make_client(seeded, AUTHOR_ID, ("RESIDENT",)) as author:
        inquiry = await _create(author, title="t", body="b")
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        response = await mgr.post(
            f"/admin/inquiries/{inquiry['id']}/category",
            json={"category_code_id": str(NOTICE_CODE_ID)},
        )
    assert response.status_code == 422


# ── 완료 잠금(done) ────────────────────────────────────────────────────────


async def test_done_locks_admin_mutations_422(seeded: AsyncSession) -> None:
    inquiry_id = await _create_done(seeded)
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as mgr:
        assert (
            await mgr.post(
                f"/admin/inquiries/{inquiry_id}/assign",
                json={"assignee_user_id": str(STAFF2_ID)},
            )
        ).status_code == 422
        assert (
            await mgr.post(f"/admin/inquiries/{inquiry_id}/priority", json={"priority": "urgent"})
        ).status_code == 422
        assert (
            await mgr.post(
                f"/admin/inquiries/{inquiry_id}/category",
                json={"category_code_id": str(CATEGORY_ID)},
            )
        ).status_code == 422
        assert (
            await mgr.post(f"/admin/inquiries/{inquiry_id}/comments", json={"body": "추가 답변"})
        ).status_code == 422
