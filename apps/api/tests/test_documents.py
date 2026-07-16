"""documents 라우터 통합 테스트 — 실 PG + 가짜 스토리지·큐."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_queue, get_storage, get_tenant_session
from app.main import create_app
from conftest import TENANT_ID, USER_ID, FakeQueue, FakeStorage
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Document, Tenant, User


async def _seed_tenant_user(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await session.flush()


@pytest_asyncio.fixture
async def client(
    db_session: AsyncSession,
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeStorage, FakeQueue]]:
    await _seed_tenant_user(db_session)
    storage, queue = FakeStorage(), FakeQueue()
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, USER_ID, roles=("MANAGER",)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, storage, queue


async def test_upload_stores_creates_row_and_enqueues(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue], db_session: AsyncSession
) -> None:
    c, storage, queue = client
    response = await c.post(
        "/documents",
        files={"file": ("규약.txt", "관리 규약 본문".encode(), "text/plain")},
        data={"title": "관리규약", "source_type": "규약", "visibility": "ALL"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["index_status"] == "pending"
    assert body["duplicate"] is False

    assert len(storage.objects) == 1
    assert queue.jobs == [("ingest_document_task", (body["id"], str(TENANT_ID)))]
    count = await db_session.scalar(select(func.count()).select_from(Document))
    assert count == 1


async def test_duplicate_hash_returns_existing_without_reenqueue(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, queue = client
    files = {"file": ("규약.txt", "같은 내용".encode(), "text/plain")}
    data = {"title": "규약", "source_type": "규약", "visibility": "ALL"}
    first = await c.post("/documents", files=files, data=data)
    second = await c.post("/documents", files=files, data=data)
    assert second.status_code == 201
    assert second.json()["duplicate"] is True
    assert second.json()["id"] == first.json()["id"]
    assert len(queue.jobs) == 1  # 재큐잉 없음


async def test_rejects_unsupported_extension(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, _ = client
    response = await c.post(
        "/documents",
        files={"file": ("명부.hwp", b"...", "application/octet-stream")},
        data={"title": "명부", "source_type": "규약", "visibility": "ALL"},
    )
    assert response.status_code == 422


async def test_rejects_empty_file(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, _ = client
    response = await c.post(
        "/documents",
        files={"file": ("빈.txt", b"", "text/plain")},
        data={"title": "빈", "source_type": "규약", "visibility": "ALL"},
    )
    assert response.status_code == 422


async def test_list_returns_uploaded(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, _ = client
    await c.post(
        "/documents",
        files={"file": ("a.txt", "내용 A".encode(), "text/plain")},
        data={"title": "문서A", "source_type": "공지", "visibility": "ALL"},
    )
    response = await c.get("/documents")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "문서A"


async def _upload(c: httpx.AsyncClient, *, title: str, body: str, visibility: str = "ALL") -> str:
    response = await c.post(
        "/documents",
        files={"file": (f"{title}.txt", body.encode(), "text/plain")},
        data={"title": title, "source_type": "공지", "visibility": visibility},
    )
    assert response.status_code == 201
    return str(response.json()["id"])


async def _set_status(session: AsyncSession, doc_id: str, status: str) -> None:
    document = await session.get(Document, uuid.UUID(doc_id))
    assert document is not None
    document.index_status = status
    await session.flush()


async def test_list_filters_by_index_status(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue], db_session: AsyncSession
) -> None:
    c, _, _ = client
    doc_id = await _upload(c, title="대기문서", body="대기 본문")
    # 두 번째 문서를 indexed 로 승격해 필터 분리 확인
    other = await _upload(c, title="완료문서", body="완료 본문")
    await _set_status(db_session, other, "indexed")

    pending = await c.get("/documents", params={"index_status": "pending"})
    assert [i["id"] for i in pending.json()["items"]] == [doc_id]
    indexed = await c.get("/documents", params={"index_status": "indexed"})
    assert [i["id"] for i in indexed.json()["items"]] == [other]


async def test_list_rejects_unknown_index_status(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, _ = client
    response = await c.get("/documents", params={"index_status": "bogus"})
    assert response.status_code == 422


async def test_list_filters_by_title_query(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, _ = client
    await _upload(c, title="주차장 운영 세칙", body="주차 본문")
    await _upload(c, title="분리수거 안내문", body="수거 본문")
    response = await c.get("/documents", params={"q": "주차"})
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "주차장 운영 세칙"


async def test_patch_updates_title_and_visibility(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, _ = client
    doc_id = await _upload(c, title="원제목", body="본문")
    response = await c.patch(
        f"/documents/{doc_id}", json={"title": "새 제목", "visibility": "ADMIN"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "새 제목"
    assert body["visibility"] == "ADMIN"


async def test_patch_missing_document_returns_404(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue],
) -> None:
    c, _, _ = client
    response = await c.patch(f"/documents/{uuid.uuid4()}", json={"title": "없음"})
    assert response.status_code == 404


async def test_reindex_resets_status_and_reenqueues(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue], db_session: AsyncSession
) -> None:
    c, _, queue = client
    doc_id = await _upload(c, title="실패문서", body="본문")
    await _set_status(db_session, doc_id, "failed")
    queue.jobs.clear()

    response = await c.post(f"/documents/{doc_id}/reindex")
    assert response.status_code == 200
    assert response.json()["index_status"] == "pending"
    assert queue.jobs == [("ingest_document_task", (doc_id, str(TENANT_ID)))]


async def test_reindex_conflicts_while_indexing(
    client: tuple[httpx.AsyncClient, FakeStorage, FakeQueue], db_session: AsyncSession
) -> None:
    c, _, _ = client
    doc_id = await _upload(c, title="색인중문서", body="본문")
    await _set_status(db_session, doc_id, "indexing")
    response = await c.post(f"/documents/{doc_id}/reindex")
    assert response.status_code == 409


async def test_resident_role_forbidden(db_session: AsyncSession) -> None:
    """RESIDENT 역할은 문서 관리 엔드포인트 접근 403(교차 역할 격리, 규칙 4)."""
    await _seed_tenant_user(db_session)
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, USER_ID, roles=("RESIDENT",)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/documents")).status_code == 403
        assert (await c.patch(f"/documents/{uuid.uuid4()}", json={"title": "x"})).status_code == 403
        assert (await c.post(f"/documents/{uuid.uuid4()}/reindex")).status_code == 403


async def test_missing_dev_headers_rejected() -> None:
    """오버라이드 없이(=정식 컨텍스트 경로) dev 헤더 없으면 401."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/documents")
    assert response.status_code == 401
