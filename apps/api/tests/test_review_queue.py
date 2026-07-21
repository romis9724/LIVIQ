"""review_queue 라우터 통합 — 실 PG. 사후 검수 목록·승인/반려·권한 (docs/01 §13, 04 §3)."""

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
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import (
    Citation,
    Conversation,
    Document,
    Message,
    Notification,
    Tenant,
    User,
)

MANAGER_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")
STAFF_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000002")
RESIDENT_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000003")
DOC_ID = uuid.UUID("dddddddd-0000-0000-0000-000000000001")
MSG_A = uuid.UUID("eeeeeeee-0000-0000-0000-000000000001")  # conf 0.62 + 인용
MSG_B = uuid.UUID("eeeeeeee-0000-0000-0000-000000000002")  # conf 0.34 fallback

_BASE = datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC)


def _at(seconds: int) -> datetime.datetime:
    return _BASE + datetime.timedelta(seconds=seconds)


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    for uid in (MANAGER_ID, STAFF_ID, RESIDENT_ID):
        session.add(User(id=uid, tenant_id=TENANT_ID, status="active"))
    session.add(
        Document(
            id=DOC_ID,
            tenant_id=TENANT_ID,
            title="관리비 납부 안내문",
            source_type="공지",
            visibility="ALL",
            storage_key="k",
            content_hash="h",
            index_status="indexed",
        )
    )
    await session.flush()

    conv1 = uuid.uuid4()
    conv2 = uuid.uuid4()
    for cid in (conv1, conv2):
        session.add(
            Conversation(id=cid, tenant_id=TENANT_ID, user_id=RESIDENT_ID, channel="resident")
        )
    await session.flush()

    # conv1: 무관 질문+답변(needs_review 아님) → 직전 질문 조인 함정 + 필터 검증.
    _msg(session, conv1, "user", "무관한 질문", at=_at(0))
    _msg(session, conv1, "assistant", "정상 답변", at=_at(1), confidence=0.9, status="answered")
    _msg(session, conv1, "user", "관리비 자동납부는 어떻게 하나요?", at=_at(2))
    _msg(
        session,
        conv1,
        "assistant",
        "앱에서 신청할 수 있습니다.",
        at=_at(3),
        mid=MSG_A,
        confidence=0.62,
        status="answered",
        review_status="needs_review",
    )
    # conv2: 저신뢰 fallback(인용 없음).
    _msg(session, conv2, "user", "전기차 충전 요금은?", at=_at(0))
    _msg(
        session,
        conv2,
        "assistant",
        "확정 근거를 찾지 못했습니다. 담당자 연결을 권장합니다.",
        at=_at(1),
        mid=MSG_B,
        confidence=0.34,
        status="fallback",
        review_status="needs_review",
    )
    await session.flush()

    session.add(
        Citation(
            tenant_id=TENANT_ID,
            message_id=MSG_A,
            source_kind="document_chunk",
            document_id=DOC_ID,
            quote="자동납부는 앱에서 신청",
        )
    )
    await session.flush()


def _msg(
    session: AsyncSession,
    conversation_id: uuid.UUID,
    role: str,
    content: str,
    *,
    at: datetime.datetime,
    mid: uuid.UUID | None = None,
    confidence: float | None = None,
    status: str | None = None,
    review_status: str | None = None,
) -> None:
    kwargs: dict[str, object] = {}
    if mid is not None:
        kwargs["id"] = mid
    session.add(
        Message(
            tenant_id=TENANT_ID,
            conversation_id=conversation_id,
            role=role,
            content=content,
            created_at=at,
            confidence=confidence,
            status=status,
            review_status=review_status,
            **kwargs,
        )
    )


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


# ── 목록 ──────────────────────────────────────────────────────────────────


async def test_list_joins_question_orders_by_confidence_and_includes_citations(
    seeded: AsyncSession,
) -> None:
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        body = (await c.get("/admin/review-queue")).json()

    assert body["total"] == 2
    ids = [i["message_id"] for i in body["items"]]
    assert ids == [str(MSG_B), str(MSG_A)]  # 신뢰도 오름차순(0.34 < 0.62)

    a = body["items"][1]
    assert a["question"] == "관리비 자동납부는 어떻게 하나요?"  # 직전 user(무관 질문 아님)
    assert a["status"] == "answered"
    assert a["citations"] == [
        {"document_title": "관리비 납부 안내문", "quote": "자동납부는 앱에서 신청"}
    ]

    b = body["items"][0]
    assert b["question"] == "전기차 충전 요금은?"
    assert b["citations"] == []
    assert b["review_status"] == "needs_review"


async def test_list_pagination_limits_page(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        body = (await c.get("/admin/review-queue", params={"page": 1, "limit": 1})).json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["message_id"] == str(MSG_B)  # 첫 페이지 = 최저 신뢰도


# ── 결정(승인/반려) ──────────────────────────────────────────────────────────


async def test_approve_sets_status_and_reviewer(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        res = await c.post(f"/admin/review-queue/{MSG_A}/decide", json={"action": "approve"})
        assert res.status_code == 200, res.text
        assert res.json()["review_status"] == "approved"
        assert res.json()["reviewed_at"] is not None

    msg = await seeded.scalar(select(Message).where(Message.id == MSG_A))
    assert msg is not None
    assert msg.review_status == "approved"
    assert msg.reviewed_by == MANAGER_ID


async def test_reject_requires_note(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        missing = await c.post(f"/admin/review-queue/{MSG_B}/decide", json={"action": "reject"})
        assert missing.status_code == 422
        blank = await c.post(
            f"/admin/review-queue/{MSG_B}/decide", json={"action": "reject", "note": "  "}
        )
        assert blank.status_code == 422
        ok = await c.post(
            f"/admin/review-queue/{MSG_B}/decide",
            json={"action": "reject", "note": "근거 없는 추측"},
        )
        assert ok.status_code == 200
        assert ok.json()["review_status"] == "rejected"
        assert ok.json()["review_note"] == "근거 없는 추측"


async def test_reject_creates_correction_notification_for_conversation_owner(
    seeded: AsyncSession,
) -> None:
    # 사후 검수 루프 폐합 — 반려 시 대화 소유자(RESIDENT_ID)에게 인앱 정정 알림(같은 트랜잭션).
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        res = await c.post(
            f"/admin/review-queue/{MSG_B}/decide",
            json={"action": "reject", "note": "근거 없는 추측"},
        )
        assert res.status_code == 200, res.text

    notif = await seeded.scalar(select(Notification).where(Notification.user_id == RESIDENT_ID))
    assert notif is not None
    assert notif.type == "system"
    assert notif.link == "/assistant"
    # 검수 메모 원문은 알림에 노출하지 않는다(PII·내부 정보 방지, ADR-0012).
    assert "근거 없는 추측" not in (notif.body or "")


async def test_approve_does_not_create_notification(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        res = await c.post(f"/admin/review-queue/{MSG_A}/decide", json={"action": "approve"})
        assert res.status_code == 200, res.text

    count = await seeded.scalar(
        select(func.count()).select_from(
            select(Notification).where(Notification.tenant_id == TENANT_ID).subquery()
        )
    )
    assert count == 0


async def test_decide_already_processed_returns_409(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        await c.post(f"/admin/review-queue/{MSG_A}/decide", json={"action": "approve"})
        again = await c.post(f"/admin/review-queue/{MSG_A}/decide", json={"action": "approve"})
    assert again.status_code == 409


async def test_decide_unknown_message_returns_404(seeded: AsyncSession) -> None:
    async with _make_client(seeded, MANAGER_ID, ("MANAGER",)) as c:
        res = await c.post(f"/admin/review-queue/{uuid.uuid4()}/decide", json={"action": "approve"})
    assert res.status_code == 404


# ── 권한(docs/04 §4: 검수 큐 MANAGER 전용 · STAFF·RESIDENT 차단, H7-2) ──────────


async def test_staff_forbidden(seeded: AsyncSession) -> None:
    """검수 큐는 소장 전용(H7-2에서 STAFF 축소) — 조회·결정 모두 403(CRITICAL)."""
    async with _make_client(seeded, STAFF_ID, ("STAFF",)) as c:
        assert (await c.get("/admin/review-queue")).status_code == 403
        decide = await c.post(f"/admin/review-queue/{MSG_A}/decide", json={"action": "approve"})
        assert decide.status_code == 403


async def test_resident_forbidden(seeded: AsyncSession) -> None:
    async with _make_client(seeded, RESIDENT_ID, ("RESIDENT",)) as c:
        assert (await c.get("/admin/review-queue")).status_code == 403
        decide = await c.post(f"/admin/review-queue/{MSG_A}/decide", json={"action": "approve"})
        assert decide.status_code == 403
