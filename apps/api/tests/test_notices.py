"""notices 게시판 통합 — 실 PG + 가짜 스토리지 (H8-1, ADR-0015).

CRUD·목록 정렬(pinned 우선)·미발행 제외·발행 알림·상태 전이·soft delete·인가와,
CRITICAL 첨부 인가(교차 tenant·미발행 공지 첨부 접근 거부)·확장자/크기/개수 검증을 본다.
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app.deps import (
    RequestContext,
    get_context,
    get_queue,
    get_session_store,
    get_storage,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from app.routers import notices as notices_router
from conftest import MANAGER_USER_ID, TENANT_ID, USER_ID, FakeQueue, FakeStorage
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import ContentChunk, Notice, NoticeAttachment, Notification, Tenant, User

TENANT_B_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _future() -> str:
    at = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)
    return at.isoformat()


def _past() -> str:
    at = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    return at.isoformat()


async def _seed(session: AsyncSession) -> None:
    """단지A + active 사용자 2명(MANAGER·RESIDENT — 발행 알림 대상)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    session.add(User(id=MANAGER_USER_ID, tenant_id=TENANT_ID, status="active"))
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await session.flush()


def _client(
    db_session: AsyncSession,
    *,
    roles: tuple[str, ...] = ("MANAGER",),
    user_id: uuid.UUID = MANAGER_USER_ID,
    storage: FakeStorage | None = None,
    queue: FakeQueue | None = None,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, user_id, roles=roles, visibilities=visibilities_for(roles)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    # 발행·본문/첨부 변경 훅이 ingest_notice_task를 enqueue한다 → 항상 FakeQueue로 대체
    # (미대체 시 실 arq 연결 시도). 어서션이 필요한 테스트는 queue를 주입한다(H8-3).
    app.dependency_overrides[get_queue] = lambda: queue or FakeQueue()
    if storage is not None:
        app.dependency_overrides[get_storage] = lambda: storage
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed(db_session)
    yield db_session


# ── 작성·발행·알림 ────────────────────────────────────────────────────────────


async def test_create_draft_does_not_notify(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        response = await c.post(
            "/admin/notices", json={"title": "임시", "body": "본문", "status": "draft"}
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft" and body["pinned"] is False
    notifs = await seeded.scalar(select(func.count()).select_from(Notification))
    assert notifs == 0  # 초안은 알림 없음


async def test_create_published_notifies_active_users(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        response = await c.post(
            "/admin/notices", json={"title": "발행", "body": "본문", "status": "published"}
        )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "published"
    notifs = await seeded.scalar(
        select(func.count()).select_from(Notification).where(Notification.type == "notice")
    )
    assert notifs == 2  # active 사용자 2명


async def test_staff_can_create_and_publish(seeded: AsyncSession) -> None:
    """STAFF도 작성·발행 허용(H7-2 부분 개정, ADR-0015)."""
    async with _client(seeded, roles=("STAFF",)) as c:
        response = await c.post(
            "/admin/notices", json={"title": "직원 공지", "body": "본문", "status": "published"}
        )
    assert response.status_code == 201, response.text


# ── 예약 발행 상태 검증 ────────────────────────────────────────────────────────


async def test_scheduled_requires_scheduled_at(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        response = await c.post(
            "/admin/notices", json={"title": "예약", "body": "본문", "status": "scheduled"}
        )
    assert response.status_code == 422  # scheduled_at 누락


async def test_scheduled_rejects_past_time(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        response = await c.post(
            "/admin/notices",
            json={"title": "예약", "body": "본문", "status": "scheduled", "scheduled_at": _past()},
        )
    assert response.status_code == 422  # 과거 시각


async def test_scheduled_creates_without_notify(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        response = await c.post(
            "/admin/notices",
            json={
                "title": "예약",
                "body": "본문",
                "status": "scheduled",
                "scheduled_at": _future(),
            },
        )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "scheduled"
    notifs = await seeded.scalar(select(func.count()).select_from(Notification))
    assert notifs == 0  # 예약은 도달 시(cron) 알림 — 생성 시점엔 없음


# ── 상태 전이 ──────────────────────────────────────────────────────────────────


async def test_patch_publish_transition_notifies(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        created = await c.post(
            "/admin/notices", json={"title": "초안", "body": "본문", "status": "draft"}
        )
        notice_id = created.json()["id"]
        patched = await c.patch(f"/admin/notices/{notice_id}", json={"status": "published"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["status"] == "published"
    assert patched.json()["published_at"] is not None
    notifs = await seeded.scalar(
        select(func.count()).select_from(Notification).where(Notification.type == "notice")
    )
    assert notifs == 2


async def test_patch_published_to_draft_rejected(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        created = await c.post(
            "/admin/notices", json={"title": "발행", "body": "본문", "status": "published"}
        )
        notice_id = created.json()["id"]
        patched = await c.patch(f"/admin/notices/{notice_id}", json={"status": "draft"})
    assert patched.status_code == 409  # 발행 취소 불가


async def test_patch_updates_pinned_and_title(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        created = await c.post(
            "/admin/notices", json={"title": "원제목", "body": "본문", "status": "published"}
        )
        notice_id = created.json()["id"]
        patched = await c.patch(
            f"/admin/notices/{notice_id}", json={"title": "새 제목", "pinned": True}
        )
    assert patched.status_code == 200
    assert patched.json()["title"] == "새 제목" and patched.json()["pinned"] is True


# ── 조회·정렬·soft delete ──────────────────────────────────────────────────────


async def _publish(c: httpx.AsyncClient, *, title: str, pinned: bool = False) -> str:
    response = await c.post(
        "/admin/notices",
        json={"title": title, "body": "본문", "status": "published", "pinned": pinned},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_resident_list_published_pinned_first(seeded: AsyncSession) -> None:
    async with _client(seeded) as admin:
        await _publish(admin, title="일반 공지")
        pinned_id = await _publish(admin, title="고정 공지", pinned=True)
        # 미발행은 입주민 목록에서 제외.
        await admin.post("/admin/notices", json={"title": "초안", "body": "b", "status": "draft"})
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID) as res:
        response = await res.get("/notices")
    items = response.json()["items"]
    assert [i["title"] for i in items] == ["고정 공지", "일반 공지"]
    assert items[0]["id"] == pinned_id


async def test_resident_cannot_see_scheduled(seeded: AsyncSession) -> None:
    async with _client(seeded) as admin:
        await admin.post(
            "/admin/notices",
            json={"title": "예약", "body": "b", "status": "scheduled", "scheduled_at": _future()},
        )
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID) as res:
        response = await res.get("/notices")
    assert response.json()["items"] == []


async def test_soft_delete_hides_from_resident(seeded: AsyncSession) -> None:
    async with _client(seeded) as admin:
        notice_id = await _publish(admin, title="삭제될 공지")
        deleted = await admin.delete(f"/admin/notices/{notice_id}")
        assert deleted.status_code == 204
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID) as res:
        res_list = await res.get("/notices")
        assert res_list.json()["items"] == []
        detail = await res.get(f"/notices/{notice_id}")
        assert detail.status_code == 404


# ── 인가 ───────────────────────────────────────────────────────────────────────


async def test_resident_forbidden_on_admin(seeded: AsyncSession) -> None:
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID) as c:
        assert (await c.get("/admin/notices")).status_code == 403
        assert (await c.post("/admin/notices", json={"title": "x", "body": "y"})).status_code == 403


async def test_list_requires_auth(db_session: AsyncSession, session_store: object) -> None:
    app = create_app()
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_session_store] = lambda: session_store
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/notices")  # 세션·dev 헤더 없음 → 401
    assert response.status_code == 401


# ── 첨부: 업로드 검증 ──────────────────────────────────────────────────────────


async def _create_notice_row(session: AsyncSession, *, status: str, tenant_id: uuid.UUID) -> Notice:
    notice = Notice(
        tenant_id=tenant_id,
        title="공지",
        body="본문",
        status=status,
        pinned=False,
        audience="ALL",
        published_at=datetime.datetime.now(datetime.UTC) if status == "published" else None,
    )
    session.add(notice)
    await session.flush()
    return notice


async def test_attachment_rejects_bad_extension(seeded: AsyncSession) -> None:
    storage = FakeStorage()
    notice = await _create_notice_row(seeded, status="draft", tenant_id=TENANT_ID)
    async with _client(seeded, storage=storage) as c:
        response = await c.post(
            f"/admin/notices/{notice.id}/attachments",
            files={"file": ("악성.exe", b"data", "application/octet-stream")},
        )
    assert response.status_code == 422
    assert storage.objects == {}


async def test_attachment_rejects_oversize(
    seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notices_router, "MAX_ATTACHMENT_BYTES", 10)
    storage = FakeStorage()
    notice = await _create_notice_row(seeded, status="draft", tenant_id=TENANT_ID)
    async with _client(seeded, storage=storage) as c:
        response = await c.post(
            f"/admin/notices/{notice.id}/attachments",
            files={"file": ("안내.pdf", b"x" * 11, "application/pdf")},
        )
    assert response.status_code == 413


async def test_attachment_count_limit(
    seeded: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notices_router, "MAX_ATTACHMENTS_PER_NOTICE", 1)
    storage = FakeStorage()
    notice = await _create_notice_row(seeded, status="draft", tenant_id=TENANT_ID)
    async with _client(seeded, storage=storage) as c:
        first = await c.post(
            f"/admin/notices/{notice.id}/attachments",
            files={"file": ("1.pdf", b"a", "application/pdf")},
        )
        assert first.status_code == 201, first.text
        second = await c.post(
            f"/admin/notices/{notice.id}/attachments",
            files={"file": ("2.pdf", b"b", "application/pdf")},
        )
    assert second.status_code == 422  # 6번째(여기선 2번째) 거부


# ── 첨부: 다운로드 인가 (CRITICAL) ─────────────────────────────────────────────


async def _upload_attachment(
    c: httpx.AsyncClient, notice_id: uuid.UUID, *, name: str = "안내.pdf"
) -> str:
    response = await c.post(
        f"/admin/notices/{notice_id}/attachments",
        files={"file": (name, "PDF 내용".encode(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_resident_downloads_published_attachment(seeded: AsyncSession) -> None:
    storage = FakeStorage()
    async with _client(seeded, storage=storage) as admin:
        notice_id = await _publish(admin, title="첨부 공지")
        att_id = await _upload_attachment(admin, uuid.UUID(notice_id), name="안내문.pdf")
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID, storage=storage) as res:
        response = await res.get(f"/notices/{notice_id}/attachments/{att_id}")
    assert response.status_code == 200
    assert response.content == "PDF 내용".encode()
    # 한글 파일명 RFC 5987 인코딩(filename*)로 노출.
    assert "filename*=UTF-8''" in response.headers["content-disposition"]


async def test_list_includes_attachment_meta(seeded: AsyncSession) -> None:
    """목록 응답에 첨부 메타 포함 — 목록 화면(관리자 첨부 수·입주민 상세)이 소비한다."""
    storage = FakeStorage()
    async with _client(seeded, storage=storage) as admin:
        notice_id = await _publish(admin, title="첨부 목록")
        await _upload_attachment(admin, uuid.UUID(notice_id), name="안내문.pdf")
        admin_list = await admin.get("/admin/notices")
    admin_items = [n for n in admin_list.json()["items"] if n["id"] == notice_id]
    assert admin_items and admin_items[0]["attachments"][0]["filename"] == "안내문.pdf"
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID, storage=storage) as res:
        response = await res.get("/notices")
    items = [n for n in response.json()["items"] if n["id"] == notice_id]
    assert items and items[0]["attachments"][0]["filename"] == "안내문.pdf"


async def test_resident_denied_unpublished_attachment(seeded: AsyncSession) -> None:
    """CRITICAL: draft 공지의 첨부는 입주민이 다운로드할 수 없다."""
    storage = FakeStorage()
    async with _client(seeded, storage=storage) as admin:
        created = await admin.post(
            "/admin/notices", json={"title": "초안", "body": "본문", "status": "draft"}
        )
        notice_id = created.json()["id"]
        att_id = await _upload_attachment(admin, uuid.UUID(notice_id))
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID, storage=storage) as res:
        response = await res.get(f"/notices/{notice_id}/attachments/{att_id}")
    assert response.status_code == 404  # 미발행 → 노출 안 함


async def test_cross_tenant_attachment_denied(seeded: AsyncSession) -> None:
    """CRITICAL: 타 단지(B) 공지 첨부는 A 입주민이 접근할 수 없다."""
    # 단지 B + published 공지 + 첨부를 직접 시드(RLS는 superuser 우회 — 앱 tenant 필터로 차단).
    seeded.add(Tenant(id=TENANT_B_ID, name="단지B", status="active"))
    await seeded.flush()
    notice_b = await _create_notice_row(seeded, status="published", tenant_id=TENANT_B_ID)
    att_b = NoticeAttachment(
        tenant_id=TENANT_B_ID,
        notice_id=notice_b.id,
        filename="B첨부.pdf",
        content_type="application/pdf",
        size_bytes=3,
        storage_key=f"{TENANT_B_ID}/notices/{notice_b.id}/x",
    )
    seeded.add(att_b)
    await seeded.flush()

    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID) as res:
        response = await res.get(f"/notices/{notice_b.id}/attachments/{att_b.id}")
    assert response.status_code == 404  # A 컨텍스트 → B 공지 미발견


# ── 첨부: 삭제 ─────────────────────────────────────────────────────────────────


async def test_delete_attachment_removes_row_and_object(seeded: AsyncSession) -> None:
    storage = FakeStorage()
    async with _client(seeded, storage=storage) as admin:
        notice_id = await _publish(admin, title="첨부 공지")
        att_id = await _upload_attachment(admin, uuid.UUID(notice_id))
        assert len(storage.objects) == 1
        deleted = await admin.delete(f"/admin/notices/{notice_id}/attachments/{att_id}")
    assert deleted.status_code == 204
    assert storage.objects == {}  # MinIO 객체 제거
    count = await seeded.scalar(select(func.count()).select_from(NoticeAttachment))
    assert count == 0


# ── 벡터화 인제스트 트리거 (H8-3) ───────────────────────────────────────────────


def _ingest_jobs(queue: FakeQueue) -> list[tuple[object, ...]]:
    return [args for task, args in queue.jobs if task == "ingest_notice_task"]


async def test_create_published_enqueues_ingest(seeded: AsyncSession) -> None:
    queue = FakeQueue()
    async with _client(seeded, queue=queue) as c:
        response = await c.post(
            "/admin/notices", json={"title": "발행", "body": "본문", "status": "published"}
        )
    notice_id = response.json()["id"]
    assert _ingest_jobs(queue) == [(notice_id, str(TENANT_ID))]


async def test_create_draft_does_not_enqueue(seeded: AsyncSession) -> None:
    queue = FakeQueue()
    async with _client(seeded, queue=queue) as c:
        await c.post("/admin/notices", json={"title": "초안", "body": "본문", "status": "draft"})
    assert _ingest_jobs(queue) == []


async def test_patch_publish_transition_enqueues(seeded: AsyncSession) -> None:
    queue = FakeQueue()
    async with _client(seeded, queue=queue) as c:
        created = await c.post(
            "/admin/notices", json={"title": "초안", "body": "본문", "status": "draft"}
        )
        notice_id = created.json()["id"]
        await c.patch(f"/admin/notices/{notice_id}", json={"status": "published"})
    assert _ingest_jobs(queue) == [(notice_id, str(TENANT_ID))]


async def test_patch_published_body_change_reingests(seeded: AsyncSession) -> None:
    queue = FakeQueue()
    async with _client(seeded, queue=queue) as c:
        created = await c.post(
            "/admin/notices", json={"title": "발행", "body": "본문", "status": "published"}
        )
        notice_id = created.json()["id"]
        await c.patch(f"/admin/notices/{notice_id}", json={"body": "수정 본문"})
    # 발행 시 1회 + 본문 수정 시 1회 재인제스트.
    assert _ingest_jobs(queue) == [(notice_id, str(TENANT_ID)), (notice_id, str(TENANT_ID))]


async def test_patch_published_pinned_only_no_reingest(seeded: AsyncSession) -> None:
    queue = FakeQueue()
    async with _client(seeded, queue=queue) as c:
        created = await c.post(
            "/admin/notices", json={"title": "발행", "body": "본문", "status": "published"}
        )
        notice_id = created.json()["id"]
        await c.patch(f"/admin/notices/{notice_id}", json={"pinned": True})
    # pinned은 벡터 본문과 무관 → 발행 1회만, 재인제스트 없음.
    assert _ingest_jobs(queue) == [(notice_id, str(TENANT_ID))]


async def test_draft_body_change_no_ingest(seeded: AsyncSession) -> None:
    queue = FakeQueue()
    async with _client(seeded, queue=queue) as c:
        created = await c.post(
            "/admin/notices", json={"title": "초안", "body": "본문", "status": "draft"}
        )
        notice_id = created.json()["id"]
        await c.patch(f"/admin/notices/{notice_id}", json={"body": "수정"})
    assert _ingest_jobs(queue) == []  # 미발행 → 인제스트 안 함


async def test_published_attachment_change_reingests(seeded: AsyncSession) -> None:
    queue = FakeQueue()
    storage = FakeStorage()
    async with _client(seeded, storage=storage, queue=queue) as c:
        notice_id = await _publish(c, title="첨부 공지")
        att_id = await _upload_attachment(c, uuid.UUID(notice_id))
        await c.delete(f"/admin/notices/{notice_id}/attachments/{att_id}")
    # 발행 + 첨부 업로드 + 첨부 삭제 = 3회.
    assert _ingest_jobs(queue) == [(notice_id, str(TENANT_ID))] * 3


async def test_soft_delete_removes_notice_chunks(seeded: AsyncSession) -> None:
    """soft delete 시 notice 청크 즉시 삭제 → 검색에서 즉시 사라짐(CRITICAL 경로)."""
    notice = await _create_notice_row(seeded, status="published", tenant_id=TENANT_ID)
    seeded.add(
        ContentChunk(
            tenant_id=TENANT_ID,
            source_type="notice",
            notice_id=notice.id,
            chunk_index=0,
            content="공지 본문",
            embedding=[0.01] * 1024,
        )
    )
    await seeded.flush()
    async with _client(seeded) as c:
        deleted = await c.delete(f"/admin/notices/{notice.id}")
    assert deleted.status_code == 204
    remaining = await seeded.scalar(
        select(func.count()).select_from(ContentChunk).where(ContentChunk.notice_id == notice.id)
    )
    assert remaining == 0
