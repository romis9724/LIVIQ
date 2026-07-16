"""documents 라우터 통합 테스트 — 실 PG + 가짜 스토리지·큐."""

from __future__ import annotations

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


async def test_missing_dev_headers_rejected() -> None:
    """오버라이드 없이(=정식 컨텍스트 경로) dev 헤더 없으면 401."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/documents")
    assert response.status_code == 401
