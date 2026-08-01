"""assistant SSE 라우터 통합 테스트 — 실 PG(문서·청크 시드) + 가짜 LLM."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_llm, get_tenant_session
from app.main import create_app
from app.routers.assistant import _building_id
from conftest import EMBED_DIM, TENANT_ID, USER_ID
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from liviq_db.models import (
    Building,
    Citation,
    Code,
    CodeGroup,
    ContentChunk,
    Document,
    Household,
    Message,
    Tenant,
    User,
)


async def _seed_indexed_document(session: AsyncSession) -> uuid.UUID:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    session.add(User(id=USER_ID, tenant_id=TENANT_ID, status="active"))
    await session.flush()
    group = CodeGroup(
        tenant_id=TENANT_ID, group_key="DOC_CATEGORY", name="문서 카테고리", is_system=True
    )
    session.add(group)
    await session.flush()
    code = Code(tenant_id=TENANT_ID, group_id=group.id, code="규약", label="규약")
    session.add(code)
    await session.flush()
    doc_id = uuid.uuid4()
    session.add(
        Document(
            id=doc_id,
            tenant_id=TENANT_ID,
            title="관리규약",
            category_code_id=code.id,
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
    # 토큰 usage 노출(H15-2 원가 계량) — 전 turn 합계. 가짜 LLM은 usage 미제공이라 추정치가 실린다.
    assert isinstance(done["token_input"], int) and done["token_input"] > 0
    assert isinstance(done["token_output"], int) and done["token_output"] > 0
    assert done["token_estimated"] is True

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
    # 근거 0 폴백도 도구 결정 turn 토큰은 이미 썼다 → 비용 기록에서 빠지지 않아야 한다(H15-2).
    assert isinstance(done["token_input"], int) and done["token_input"] > 0
    assert done["token_estimated"] is True


async def test_sse_new_fields_are_additive(seeded_client: httpx.AsyncClient) -> None:
    """ADR-0025 §5 — 이벤트 종류 4종 불변, 기존 필드 유지, 새 필드는 기본값으로 붙는다.

    기존 소비자(stage·tool_path만 읽는 웹)는 새 필드를 몰라도 그대로 동작해야 한다.
    """
    response = await seeded_client.post("/assistant/ask", json={"question": "주차장 언제 열어요?"})
    events = _parse_sse(response.text)
    assert {name for name, _ in events} <= {"status", "token", "citation", "done"}

    statuses = [p for name, p in events if name == "status"]
    assert all(p["stage"] in {"searching", "generating", "verifying"} for p in statuses)
    assert statuses[0]["tool"] is None  # 첫 searching은 도구 미상
    assert [p["tool"] for p in statuses if p["tool"]] == ["search_documents", "get_fees"]

    citations = [p for name, p in events if name == "citation"]
    assert citations, "문서 인용이 있어야 하위호환을 검증할 수 있다"
    for payload in citations:
        assert {"ref", "document_id", "document_title", "quote", "page", "clause"} <= set(payload)
        if payload["document_id"] is not None:
            assert payload["data"] is None  # 문서 인용은 구조화 페이로드가 없다

    done = events[-1][1]
    assert {"message_id", "conversation_id", "status", "confidence", "needs_review"} <= set(done)
    assert done["tool_path"] == ["search_documents", "get_fees"]
    # suggestions 필드는 계약으로 남지만(키 존재) 지금 도구 매핑은 비어 있다 —
    # 고정 문구가 맥락을 못 읽어 전부 제거했다(2026-08-01 "지난달과 비교하기" 실측).
    assert done["suggestions"] == []


async def test_ask_rejects_oversized_question(seeded_client: httpx.AsyncClient) -> None:
    response = await seeded_client.post("/assistant/ask", json={"question": "가" * 3000})
    assert response.status_code == 422


async def _assign_household(db_session: AsyncSession) -> uuid.UUID:
    """USER_ID에 401동 세대를 배정하고 building_id 반환."""
    building = Building(tenant_id=TENANT_ID, name="401")
    db_session.add(building)
    await db_session.flush()
    household = Household(
        tenant_id=TENANT_ID, building_id=building.id, floor=3, unit_no=301, status="active"
    )
    db_session.add(household)
    await db_session.flush()
    user = await db_session.get(User, USER_ID)
    assert user is not None
    user.household_id = household.id
    await db_session.flush()
    return building.id


async def test_building_id_resolves_from_household(db_session: AsyncSession) -> None:
    """ToolContext의 동은 로그인 세대에서 온다(H19-1) — 공지 검색 필터의 입력."""
    await _seed_indexed_document(db_session)
    building_id = await _assign_household(db_session)

    ctx = RequestContext(TENANT_ID, USER_ID, roles=("RESIDENT",))
    assert await _building_id(db_session, ctx) == building_id


async def test_building_id_is_none_without_household(db_session: AsyncSession) -> None:
    """세대 미배정이면 동이 없다 — 필터 미적용으로 전 동 검색을 유지한다."""
    await _seed_indexed_document(db_session)

    ctx = RequestContext(TENANT_ID, USER_ID, roles=("RESIDENT",))
    assert await _building_id(db_session, ctx) is None


async def test_building_id_exempts_admin_roles_even_with_household(
    db_session: AsyncSession,
) -> None:
    """관리자 면제는 역할로 판정한다 — 세대가 배정돼 있어도 전 동 검색을 유지한다.

    시더가 관리자에게 세대를 주지 않는 것은 우연이다(H19-1) — 입주민 겸 관리자가 생겨도
    "402동 점검" 질문이 자기 동으로 조용히 좁혀지면 안 된다.
    """
    await _seed_indexed_document(db_session)
    await _assign_household(db_session)

    for roles in (("MANAGER",), ("STAFF",), ("RESIDENT", "MANAGER")):
        ctx = RequestContext(TENANT_ID, USER_ID, roles=roles)
        assert await _building_id(db_session, ctx) is None, roles
