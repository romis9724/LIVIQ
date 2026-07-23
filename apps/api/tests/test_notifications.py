"""notifications 라우터 통합 — 실 PG. 본인 알림 조회·읽음 멱등·소유권 격리 (ADR-0012).

CRITICAL(규칙 4): 타 사용자 알림은 목록에 노출되지 않고, 읽음 처리도 404다.
notifications RLS는 tenant 단위라 user 격리는 라우터 쿼리 필터가 유일한 방어선.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_tenant_session
from app.main import create_app
from conftest import TENANT_ID
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Notification, Tenant, User

USER_A = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
USER_B = uuid.UUID("ffffffff-0000-0000-0000-000000000002")
NOTIF_A1 = uuid.UUID("ffffffff-1111-0000-0000-000000000001")  # A, 오래된
NOTIF_A2 = uuid.UUID("ffffffff-1111-0000-0000-000000000002")  # A, 최신
NOTIF_B1 = uuid.UUID("ffffffff-2222-0000-0000-000000000001")  # B

_BASE = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)


def _at(seconds: int) -> datetime.datetime:
    return _BASE + datetime.timedelta(seconds=seconds)


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    for uid in (USER_A, USER_B):
        session.add(User(id=uid, tenant_id=TENANT_ID, status="active"))
    await session.flush()

    session.add(
        Notification(
            id=NOTIF_A1,
            tenant_id=TENANT_ID,
            user_id=USER_A,
            type="inquiry_status",
            title="민원 담당자가 배정되었습니다",
            link="/inquiries/x",
            created_at=_at(0),
        )
    )
    session.add(
        Notification(
            id=NOTIF_A2,
            tenant_id=TENANT_ID,
            user_id=USER_A,
            type="system",
            title="AI 답변이 검수 결과 정정되었습니다",
            body="관리사무소로 문의해 주세요.",
            link="/assistant",
            created_at=_at(10),
        )
    )
    session.add(
        Notification(
            id=NOTIF_B1,
            tenant_id=TENANT_ID,
            user_id=USER_B,
            type="notice",
            title="B의 알림",
            created_at=_at(5),
        )
    )
    await session.flush()


def _make_client(db_session: AsyncSession, user_id: uuid.UUID) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, user_id, roles=("RESIDENT",)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed(db_session)
    yield db_session


# ── 목록 (본인 것만·최신순) ────────────────────────────────────────────────


async def test_list_returns_only_own_notifications_newest_first(seeded: AsyncSession) -> None:
    async with _make_client(seeded, USER_A) as c:
        body = (await c.get("/notifications")).json()

    assert body["total"] == 2  # B의 알림은 미집계
    ids = [n["id"] for n in body["items"]]
    assert ids == [str(NOTIF_A2), str(NOTIF_A1)]  # 최신순
    assert all(uuid.UUID(n["id"]) != NOTIF_B1 for n in body["items"])  # 타 사용자 미노출


async def test_list_pagination_limits_page(seeded: AsyncSession) -> None:
    async with _make_client(seeded, USER_A) as c:
        body = (await c.get("/notifications", params={"page": 1, "limit": 1})).json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["id"] == str(NOTIF_A2)  # 첫 페이지 = 최신


# ── 읽음 처리 (멱등·소유권) ────────────────────────────────────────────────


async def test_mark_read_stamps_and_is_idempotent(seeded: AsyncSession) -> None:
    async with _make_client(seeded, USER_A) as c:
        first = await c.post(f"/notifications/{NOTIF_A1}/read")
        assert first.status_code == 200, first.text
        stamped = first.json()["read_at"]
        assert stamped is not None

        again = await c.post(f"/notifications/{NOTIF_A1}/read")
        assert again.status_code == 200
        assert again.json()["read_at"] == stamped  # 멱등 — 시각 유지


async def test_mark_read_other_users_notification_returns_404(seeded: AsyncSession) -> None:
    # CRITICAL(규칙 4): USER_A가 USER_B의 알림을 읽음 처리 불가.
    async with _make_client(seeded, USER_A) as c:
        res = await c.post(f"/notifications/{NOTIF_B1}/read")
    assert res.status_code == 404

    notif = await seeded.scalar(select(Notification).where(Notification.id == NOTIF_B1))
    assert notif is not None
    assert notif.read_at is None  # 남의 알림은 건드리지 않음


async def test_mark_read_unknown_returns_404(seeded: AsyncSession) -> None:
    async with _make_client(seeded, USER_A) as c:
        res = await c.post(f"/notifications/{uuid.uuid4()}/read")
    assert res.status_code == 404


# ── 삭제 (하드 삭제·소유권) ────────────────────────────────────────────────


async def test_delete_removes_own_notification_from_list(seeded: AsyncSession) -> None:
    async with _make_client(seeded, USER_A) as c:
        res = await c.delete(f"/notifications/{NOTIF_A1}")
        assert res.status_code == 204, res.text

        body = (await c.get("/notifications")).json()

    assert body["total"] == 1  # 2 → 1
    assert all(uuid.UUID(n["id"]) != NOTIF_A1 for n in body["items"])
    gone = await seeded.scalar(select(Notification).where(Notification.id == NOTIF_A1))
    assert gone is None  # 하드 삭제


async def test_delete_other_users_notification_returns_404(seeded: AsyncSession) -> None:
    # CRITICAL(규칙 4): USER_A가 USER_B의 알림을 삭제 불가.
    async with _make_client(seeded, USER_A) as c:
        res = await c.delete(f"/notifications/{NOTIF_B1}")
    assert res.status_code == 404

    notif = await seeded.scalar(select(Notification).where(Notification.id == NOTIF_B1))
    assert notif is not None  # 남의 알림은 남아 있음


async def test_delete_is_not_repeatable_returns_404(seeded: AsyncSession) -> None:
    async with _make_client(seeded, USER_A) as c:
        first = await c.delete(f"/notifications/{NOTIF_A1}")
        assert first.status_code == 204
        again = await c.delete(f"/notifications/{NOTIF_A1}")
    assert again.status_code == 404


async def test_delete_unknown_returns_404(seeded: AsyncSession) -> None:
    async with _make_client(seeded, USER_A) as c:
        res = await c.delete(f"/notifications/{uuid.uuid4()}")
    assert res.status_code == 404
