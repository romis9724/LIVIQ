"""assistant SSE 라우터 통합 테스트 — 실 PG(문서·청크 시드) + 가짜 LLM."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_llm, get_tenant_session
from app.main import create_app
from conftest import EMBED_DIM, TENANT_ID, USER_ID
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from liviq_db.models import Citation, ContentChunk, Document, Message, Tenant, User


async def _seed_indexed_document(session: AsyncSession) -> uuid.UUID:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await session.flush()
    doc_id = uuid.uuid4()
    session.add(
        Document(
            id=doc_id,
            tenant_id=TENANT_ID,
            title="관리규약",
            source_type="규약",
            visibility="ALL",
            version=1,
            index_status="indexed",
        )
    )
    await session.flush()
    session.add(
        ContentChunk(
            tenant_id=TENANT_ID,
            source_type="document",
            document_id=doc_id,
            notice_id=None,
            chunk_index=0,
            content="지하주차장은 24시간 개방한다.",
            embedding=[0.05] * EMBED_DIM,  # fake_llm 임베딩과 동일 → cosine=1
        )
    )
    await session.flush()
    return doc_id


def _build_client(db_session: AsyncSession, fake_llm: LlmClient) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(TENANT_ID, USER_ID)
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_llm] = lambda: fake_llm
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    event_name = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            event_name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append((event_name, json.loads(line[len("data:") :].strip())))
    return events


@pytest_asyncio.fixture
async def seeded_client(
    db_session: AsyncSession, fake_llm: LlmClient
) -> AsyncIterator[httpx.AsyncClient]:
    await _seed_indexed_document(db_session)
    async with _build_client(db_session, fake_llm) as c:
        yield c


async def test_ask_streams_token_citation_done(
    seeded_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    response = await seeded_client.post("/assistant/ask", json={"question": "주차장 언제 열어요?"})
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert "status" in names
    assert "token" in names
    assert "citation" in names
    assert names[-1] == "done"

    done = events[-1][1]
    assert done["status"] == "answered"
    assert done["message_id"] is not None

    # 대화(user+assistant) + 인용 영속 확인
    msg_count = await db_session.scalar(select(func.count()).select_from(Message))
    assert msg_count == 2
    cit_count = await db_session.scalar(select(func.count()).select_from(Citation))
    assert cit_count is not None and cit_count >= 1


async def test_ask_without_evidence_falls_back(
    db_session: AsyncSession, fake_llm: LlmClient
) -> None:
    # 문서 시드 없음 → 근거 0 → 폴백
    await db_session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    db_session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    db_session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await db_session.flush()
    async with _build_client(db_session, fake_llm) as c:
        response = await c.post("/assistant/ask", json={"question": "관리소장 개인 연락처?"})
    events = _parse_sse(response.text)
    done = events[-1][1]
    assert events[-1][0] == "done"
    assert done["status"] == "fallback"
    assert done["fallback_reason"] == "no_evidence"


async def test_ask_rejects_oversized_question(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.post("/assistant/ask", json={"question": "가" * 3000})
    assert response.status_code == 422
