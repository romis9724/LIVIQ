"""documents 게시판 라우터 통합 테스트 — 실 PG + 가짜 스토리지·큐·redis (ADR-0016)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_queue, get_storage, get_tenant_session
from app.main import create_app
from app.session import get_redis
from conftest import EMBED_DIM, TENANT_ID, USER_ID, FakeQueue, FakeStorage
from fakeredis.aioredis import FakeRedis
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import ContentChunk, Document, DocumentVersion, Tenant, User

OTHER_TENANT_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")

Client = tuple[httpx.AsyncClient, FakeStorage, FakeQueue, FakeRedis]


async def _seed_tenant_user(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await session.flush()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_redis: FakeRedis) -> AsyncIterator[Client]:
    await _seed_tenant_user(db_session)
    storage, queue = FakeStorage(), FakeQueue()
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, USER_ID, roles=("MANAGER",)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue
    app.dependency_overrides[get_redis] = lambda: fake_redis
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, storage, queue, fake_redis


async def _create(
    c: httpx.AsyncClient,
    *,
    title: str = "문서A",
    body: str | None = "설명 본문",
    filename: str = "a.txt",
    content: str = "내용 A",
    source_type: str = "공지",
    visibility: str = "ALL",
) -> httpx.Response:
    data = {"title": title, "source_type": source_type, "visibility": visibility}
    if body is not None:
        data["body"] = body
    return await c.post(
        "/documents",
        files={"file": (filename, content.encode(), "text/plain")},
        data=data,
    )


async def _gen(redis: FakeRedis) -> int:
    raw = await redis.get(f"cache:gen:{TENANT_ID}")
    return int(raw) if raw is not None else 0


# ── 작성 ──────────────────────────────────────────────────────────────────


async def test_create_stores_version1_and_enqueues(
    client: Client, db_session: AsyncSession
) -> None:
    c, storage, queue, _ = client
    response = await _create(c)
    assert response.status_code == 201
    body = response.json()
    assert body["version"] == 1
    assert body["index_status"] == "pending"
    doc_id = body["id"]

    assert len(storage.objects) == 1
    (key,) = storage.objects
    assert "/documents/" in key and "/v1" in key
    assert queue.jobs == [("ingest_document_task", (doc_id, str(TENANT_ID)))]

    assert await db_session.scalar(select(func.count()).select_from(Document)) == 1
    version = await db_session.scalar(
        select(DocumentVersion).where(DocumentVersion.document_id == uuid.UUID(doc_id))
    )
    assert version is not None
    assert version.version == 1
    assert version.filename == "a.txt"
    assert version.size_bytes == len("내용 A".encode())


async def test_create_without_file_rejected(client: Client) -> None:
    c, _, _, _ = client
    response = await c.post(
        "/documents",
        data={"title": "제목", "source_type": "공지", "visibility": "ALL"},
    )
    assert response.status_code == 422


async def test_create_rejects_unsupported_extension(client: Client) -> None:
    c, _, _, _ = client
    response = await _create(c, filename="명부.hwp")
    assert response.status_code == 422


async def test_create_rejects_empty_file(client: Client) -> None:
    c, _, _, _ = client
    response = await c.post(
        "/documents",
        files={"file": ("빈.txt", b"", "text/plain")},
        data={"title": "빈", "source_type": "공지", "visibility": "ALL"},
    )
    assert response.status_code == 422


async def test_duplicate_current_version_hash_rejected(client: Client) -> None:
    c, _, queue, _ = client
    first = await _create(c, title="원본", content="같은 내용")
    assert first.status_code == 201
    dup = await _create(c, title="복제", content="같은 내용")
    assert dup.status_code == 409
    assert len(queue.jobs) == 1  # 재큐잉 없음


# ── 상세 ──────────────────────────────────────────────────────────────────


async def test_detail_includes_body_and_versions(client: Client) -> None:
    c, _, _, _ = client
    doc_id = (await _create(c, body="상세 설명", content="v1")).json()["id"]
    await c.post(
        f"/documents/{doc_id}/file", files={"file": ("b.txt", b"v2 content", "text/plain")}
    )

    response = await c.get(f"/documents/{doc_id}")
    assert response.status_code == 200
    detail = response.json()
    assert detail["body"] == "상세 설명"
    assert detail["version"] == 2
    versions = detail["versions"]
    assert [v["version"] for v in versions] == [2, 1]  # 내림차순


# ── 새 버전 ────────────────────────────────────────────────────────────────


async def test_new_version_increments_reenqueues_and_bumps_cache(
    client: Client, db_session: AsyncSession
) -> None:
    c, _, queue, redis = client
    doc_id = (await _create(c, content="원본 내용")).json()["id"]
    queue.jobs.clear()
    gen_before = await _gen(redis)

    response = await c.post(
        f"/documents/{doc_id}/file",
        files={"file": ("v2.txt", "개정 내용".encode(), "text/plain")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["index_status"] == "pending"
    assert queue.jobs == [("ingest_document_task", (doc_id, str(TENANT_ID)))]
    assert await _gen(redis) == gen_before + 1

    count = await db_session.scalar(
        select(func.count())
        .select_from(DocumentVersion)
        .where(DocumentVersion.document_id == uuid.UUID(doc_id))
    )
    assert count == 2


async def test_new_version_same_hash_rejected(client: Client) -> None:
    c, _, _, _ = client
    doc_id = (await _create(c, content="변함없음")).json()["id"]
    response = await c.post(
        f"/documents/{doc_id}/file",
        files={"file": ("same.txt", "변함없음".encode(), "text/plain")},
    )
    assert response.status_code == 409


async def test_new_version_duplicate_of_other_document_rejected(client: Client) -> None:
    c, _, _, _ = client
    await _create(c, title="A", content="AAA")
    doc_b = (await _create(c, title="B", content="BBB")).json()["id"]
    response = await c.post(
        f"/documents/{doc_b}/file",
        files={"file": ("x.txt", b"AAA", "text/plain")},
    )
    assert response.status_code == 409


# ── 다운로드 ──────────────────────────────────────────────────────────────


async def test_download_version_streams_with_disposition(client: Client) -> None:
    c, _, _, _ = client
    doc_id = (await _create(c, filename="규약.txt", content="첨부 원문")).json()["id"]
    response = await c.get(f"/documents/{doc_id}/versions/1/download")
    assert response.status_code == 200
    assert response.content == "첨부 원문".encode()
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment; filename*=UTF-8''")


async def test_download_missing_version_404(client: Client) -> None:
    c, _, _, _ = client
    doc_id = (await _create(c)).json()["id"]
    response = await c.get(f"/documents/{doc_id}/versions/99/download")
    assert response.status_code == 404


# ── 교차 tenant 격리 (CRITICAL) ────────────────────────────────────────────


async def test_cross_tenant_access_returns_404(client: Client, db_session: AsyncSession) -> None:
    """다른 단지 컨텍스트는 문서의 존재를 알 수 없다(규칙 3, app 레벨 2차 방어)."""
    c, _, _, _ = client
    doc_id = (await _create(c)).json()["id"]

    other_app = create_app()
    other_app.dependency_overrides[get_context] = lambda: RequestContext(
        OTHER_TENANT_ID, USER_ID, roles=("MANAGER",)
    )
    other_app.dependency_overrides[get_tenant_session] = lambda: db_session
    other_app.dependency_overrides[get_storage] = lambda: FakeStorage()
    other_app.dependency_overrides[get_queue] = lambda: FakeQueue()
    transport = ASGITransport(app=other_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as other:
        assert (await other.get(f"/documents/{doc_id}")).status_code == 404
        assert (
            await other.patch(f"/documents/{doc_id}", json={"title": "탈취"})
        ).status_code == 404
        assert (await other.get(f"/documents/{doc_id}/versions/1/download")).status_code == 404
        assert (await other.delete(f"/documents/{doc_id}")).status_code == 404


# ── 삭제 ──────────────────────────────────────────────────────────────────


async def test_delete_soft_deletes_removes_chunks_and_bumps_cache(
    client: Client, db_session: AsyncSession
) -> None:
    c, _, _, redis = client
    doc_id = (await _create(c)).json()["id"]
    db_session.add(
        ContentChunk(
            tenant_id=TENANT_ID,
            source_type="document",
            document_id=uuid.UUID(doc_id),
            notice_id=None,
            chunk_index=0,
            content="청크 본문",
            embedding=[0.0] * EMBED_DIM,
        )
    )
    await db_session.flush()
    gen_before = await _gen(redis)

    response = await c.delete(f"/documents/{doc_id}")
    assert response.status_code == 204

    assert (await c.get("/documents")).json()["items"] == []
    chunks = await db_session.scalar(
        select(func.count())
        .select_from(ContentChunk)
        .where(ContentChunk.document_id == uuid.UUID(doc_id))
    )
    assert chunks == 0
    # 버전 이력은 보존(감사 대응).
    versions = await db_session.scalar(
        select(func.count())
        .select_from(DocumentVersion)
        .where(DocumentVersion.document_id == uuid.UUID(doc_id))
    )
    assert versions == 1
    assert await _gen(redis) == gen_before + 1


# ── 메타 수정 ──────────────────────────────────────────────────────────────


async def test_patch_updates_all_fields(client: Client) -> None:
    c, _, _, _ = client
    doc_id = (await _create(c, title="원제목", body="원본문")).json()["id"]
    response = await c.patch(
        f"/documents/{doc_id}",
        json={
            "title": "새 제목",
            "body": "새 본문",
            "source_type": "지침",
            "visibility": "ADMIN",
        },
    )
    assert response.status_code == 200
    assert response.json()["title"] == "새 제목"
    assert response.json()["visibility"] == "ADMIN"
    detail = (await c.get(f"/documents/{doc_id}")).json()
    assert detail["body"] == "새 본문"
    assert detail["source_type"] == "지침"


async def test_patch_visibility_bumps_cache(client: Client) -> None:
    c, _, _, redis = client
    doc_id = (await _create(c, visibility="ALL")).json()["id"]
    gen_before = await _gen(redis)
    await c.patch(f"/documents/{doc_id}", json={"visibility": "ADMIN"})
    assert await _gen(redis) == gen_before + 1


async def test_patch_missing_document_returns_404(client: Client) -> None:
    c, _, _, _ = client
    response = await c.patch(f"/documents/{uuid.uuid4()}", json={"title": "없음"})
    assert response.status_code == 404


# ── 목록·필터 ──────────────────────────────────────────────────────────────


async def test_list_returns_created(client: Client) -> None:
    c, _, _, _ = client
    await _create(c, title="문서A", content="내용 A")
    items = (await c.get("/documents")).json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "문서A"
    assert "body" not in items[0]  # 목록은 본문 제외(경량)


async def _set_status(session: AsyncSession, doc_id: str, status: str) -> None:
    document = await session.get(Document, uuid.UUID(doc_id))
    assert document is not None
    document.index_status = status
    await session.flush()


async def test_list_filters_by_index_status(client: Client, db_session: AsyncSession) -> None:
    c, _, _, _ = client
    pending_id = (await _create(c, title="대기", content="대기 본문")).json()["id"]
    other = (await _create(c, title="완료", content="완료 본문")).json()["id"]
    await _set_status(db_session, other, "indexed")

    pending = await c.get("/documents", params={"index_status": "pending"})
    assert [i["id"] for i in pending.json()["items"]] == [pending_id]
    indexed = await c.get("/documents", params={"index_status": "indexed"})
    assert [i["id"] for i in indexed.json()["items"]] == [other]


async def test_list_rejects_unknown_index_status(client: Client) -> None:
    c, _, _, _ = client
    response = await c.get("/documents", params={"index_status": "bogus"})
    assert response.status_code == 422


async def test_list_filters_by_title_query(client: Client) -> None:
    c, _, _, _ = client
    await _create(c, title="주차장 운영 세칙", content="주차 본문")
    await _create(c, title="분리수거 안내문", content="수거 본문")
    response = await c.get("/documents", params={"q": "주차"})
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "주차장 운영 세칙"


# ── 재색인 ────────────────────────────────────────────────────────────────


async def test_reindex_resets_status_and_reenqueues(
    client: Client, db_session: AsyncSession
) -> None:
    c, _, queue, _ = client
    doc_id = (await _create(c, content="본문")).json()["id"]
    await _set_status(db_session, doc_id, "failed")
    queue.jobs.clear()

    response = await c.post(f"/documents/{doc_id}/reindex")
    assert response.status_code == 200
    assert response.json()["index_status"] == "pending"
    assert queue.jobs == [("ingest_document_task", (doc_id, str(TENANT_ID)))]


async def test_reindex_conflicts_while_indexing(client: Client, db_session: AsyncSession) -> None:
    c, _, _, _ = client
    doc_id = (await _create(c, content="본문")).json()["id"]
    await _set_status(db_session, doc_id, "indexing")
    response = await c.post(f"/documents/{doc_id}/reindex")
    assert response.status_code == 409


# ── 인가 ──────────────────────────────────────────────────────────────────


async def test_resident_role_forbidden(db_session: AsyncSession) -> None:
    """RESIDENT 역할은 문서 관리 엔드포인트 전부 403(교차 역할 격리, 규칙 4)."""
    await _seed_tenant_user(db_session)
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, USER_ID, roles=("RESIDENT",)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    transport = ASGITransport(app=app)
    doc_id = uuid.uuid4()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        assert (await c.get("/documents")).status_code == 403
        assert (await c.get(f"/documents/{doc_id}")).status_code == 403
        assert (await c.patch(f"/documents/{doc_id}", json={"title": "x"})).status_code == 403
        assert (await c.delete(f"/documents/{doc_id}")).status_code == 403
        assert (await c.post(f"/documents/{doc_id}/reindex")).status_code == 403
        assert (await c.get(f"/documents/{doc_id}/versions/1/download")).status_code == 403


async def test_missing_dev_headers_rejected() -> None:
    """오버라이드 없이(=정식 컨텍스트 경로) dev 헤더 없으면 401."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/documents")
    assert response.status_code == 401
