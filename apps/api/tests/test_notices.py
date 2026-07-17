"""notices 라우터 통합 — 실 PG(문서·청크 시드) + 가짜 LLM(논스트리밍 chat).

초안 근거 강제(근거 0→422)·발행은 MANAGER만·published 시 전 active 사용자 알림·
발행 공지만 조회 노출·미인증 401을 검증한다(docs/01 §13, 규칙 1·4·6).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import (
    RequestContext,
    get_context,
    get_llm,
    get_session_store,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from conftest import EMBED_DIM, MANAGER_USER_ID, TENANT_ID, USER_ID
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from liviq_db.models import Document, DocumentChunk, Notice, NoticeDraft, Notification, Tenant, User

DEFAULT_ANSWER = "지하주차장 개방 안내\n\n지하주차장은 24시간 개방합니다 [1]."


def _notice_llm(answer: str = DEFAULT_ANSWER) -> LlmClient:
    """임베딩 고정 벡터([0.05] — 시드 청크와 cosine=1) + 논스트리밍 chat JSON 응답."""
    settings = AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="test",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/embeddings"):
            texts = json.loads(request.content)["input"]
            data = [{"index": i, "embedding": [0.05] * EMBED_DIM} for i in range(len(texts))]
            return httpx.Response(200, json={"data": data})
        return httpx.Response(
            200, json={"choices": [{"message": {"role": "assistant", "content": answer}}]}
        )

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


async def _seed(session: AsyncSession, *, with_document: bool = True) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    # active 사용자 2명(발행 알림 대상) — MANAGER + RESIDENT.
    session.add(User(id=MANAGER_USER_ID, tenant_id=TENANT_ID, status="active"))
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await session.flush()
    if not with_document:
        return
    doc_id = uuid.uuid4()
    session.add(
        Document(
            id=doc_id,
            tenant_id=TENANT_ID,
            title="관리규약",
            source_type="규약",
            visibility="ALL",
            storage_key=f"{TENANT_ID}/documents/{doc_id}.txt",
            content_hash="hash-1",
            index_status="indexed",
        )
    )
    await session.flush()
    session.add(
        DocumentChunk(
            tenant_id=TENANT_ID,
            document_id=doc_id,
            chunk_index=0,
            content="지하주차장은 24시간 개방한다.",
            embedding=[0.05] * EMBED_DIM,
        )
    )
    await session.flush()


def _client(
    db_session: AsyncSession,
    *,
    roles: tuple[str, ...] = ("MANAGER",),
    user_id: uuid.UUID = MANAGER_USER_ID,
    llm: LlmClient | None = None,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, user_id, roles=roles, visibilities=visibilities_for(roles)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_llm] = lambda: llm or _notice_llm()
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed(db_session)
    yield db_session


# ── 초안 생성 ────────────────────────────────────────────────────────────────


async def test_create_draft_persists_and_returns_citation(
    seeded: AsyncSession,
) -> None:
    async with _client(seeded) as c:
        response = await c.post("/admin/notices/drafts", json={"keywords": ["주차장", "개방"]})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["title"] == "지하주차장 개방 안내"
    assert body["citations"] and body["citations"][0]["document_title"] == "관리규약"

    count = await seeded.scalar(select(func.count()).select_from(NoticeDraft))
    assert count == 1
    draft = await seeded.scalar(select(NoticeDraft))
    assert draft is not None and draft.review_status == "pending"


async def test_draft_without_evidence_returns_422(db_session: AsyncSession) -> None:
    await _seed(db_session, with_document=False)
    async with _client(db_session) as c:
        response = await c.post("/admin/notices/drafts", json={"keywords": ["주차장"]})
    assert response.status_code == 422
    count = await db_session.scalar(select(func.count()).select_from(NoticeDraft))
    assert count == 0  # 근거 0이면 초안 행을 만들지 않는다(규칙 1)


# ── 발행 ────────────────────────────────────────────────────────────────────


async def test_publish_creates_notice_and_notifies_active_users(
    seeded: AsyncSession,
) -> None:
    async with _client(seeded) as c:
        draft_resp = await c.post("/admin/notices/drafts", json={"keywords": ["주차장"]})
        draft_id = draft_resp.json()["draft_id"]
        publish_resp = await c.post(
            "/admin/notices",
            json={
                "draft_id": draft_id,
                "title": "지하주차장 개방 안내",
                "body": "24시간 개방합니다 [1].",
                "audience": "ALL",
            },
        )
    assert publish_resp.status_code == 201, publish_resp.text
    assert publish_resp.json()["status"] == "published"

    notices = await seeded.scalar(
        select(func.count()).select_from(Notice).where(Notice.status == "published")
    )
    assert notices == 1
    # active 사용자 2명 → 알림 2건.
    notifs = await seeded.scalar(
        select(func.count()).select_from(Notification).where(Notification.type == "notice")
    )
    assert notifs == 2
    draft = await seeded.scalar(select(NoticeDraft).where(NoticeDraft.id == uuid.UUID(draft_id)))
    assert draft is not None and draft.review_status == "approved"

    # 이미 검수된 초안 재발행 → 409.
    async with _client(seeded) as c:
        again = await c.post(
            "/admin/notices",
            json={"draft_id": draft_id, "title": "재발행", "body": "본문 [1].", "audience": "ALL"},
        )
    assert again.status_code == 409


# ── 역할 가드 ────────────────────────────────────────────────────────────────


async def test_staff_cannot_publish(seeded: AsyncSession) -> None:
    async with _client(seeded, roles=("STAFF",)) as c:
        response = await c.post(
            "/admin/notices",
            json={
                "draft_id": str(uuid.uuid4()),
                "title": "무단 발행",
                "body": "본문",
                "audience": "ALL",
            },
        )
    assert response.status_code == 403


async def test_resident_cannot_create_draft(seeded: AsyncSession) -> None:
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID) as c:
        response = await c.post("/admin/notices/drafts", json={"keywords": ["주차장"]})
    assert response.status_code == 403


# ── 조회 ────────────────────────────────────────────────────────────────────


async def test_list_returns_published_only(seeded: AsyncSession) -> None:
    import datetime

    seeded.add(
        Notice(
            tenant_id=TENANT_ID,
            title="발행 공지",
            body="본문",
            status="published",
            audience="ALL",
            published_at=datetime.datetime.now(datetime.UTC),
            published_by=MANAGER_USER_ID,
        )
    )
    seeded.add(
        Notice(
            tenant_id=TENANT_ID,
            title="예약 공지",
            body="본문",
            status="draft",
            audience="ALL",
        )
    )
    await seeded.flush()
    async with _client(seeded, roles=("RESIDENT",), user_id=USER_ID) as c:
        response = await c.get("/notices")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1 and items[0]["title"] == "발행 공지"


async def test_list_requires_auth(db_session: AsyncSession, session_store: object) -> None:
    app = create_app()
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_session_store] = lambda: session_store
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.get("/notices")  # 세션·dev 헤더 없음 → 401(fail-closed)
    assert response.status_code == 401
