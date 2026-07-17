"""assistant 도구 에이전트 통합 테스트 — 실 PG(도구 SQL·RLS) + 가짜 도구호출 LLM.

- get_fees 도구가 본인 세대 확정 데이터를 근거 카드로 반환하고, 도구 인용이 영속되는지.
- 도구 경로가 도메인 데이터를 변경하지 않는지(규칙 8 — 읽기 전용).
"""

from __future__ import annotations

import datetime
import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_llm, get_tenant_session
from app.main import create_app
from conftest import BUILDING_ID, EMBED_DIM, TENANT_ID, USER_ID
from httpx import ASGITransport
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from liviq_db.models import Building, Citation, Fee, Household, Tenant, User

HOUSEHOLD_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _fee_agent_llm(*, answer: str = "이번 달 관리비는 100,000원입니다.") -> LlmClient:
    """get_fees만 호출한 뒤 스트림 답변하는 가짜 도구호출 LLM."""
    settings = AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="test",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            texts = body["input"]
            data = [{"index": i, "embedding": [0.05] * EMBED_DIM} for i in range(len(texts))]
            return httpx.Response(200, json={"data": data})
        if body.get("stream"):
            sse = "\n\n".join(
                [
                    f"data: {json.dumps({'choices': [{'delta': {'content': answer}}]})}",
                    "data: [DONE]",
                    "",
                ]
            )
            return httpx.Response(200, content=sse.encode())
        if any(m.get("role") == "tool" for m in body.get("messages", [])):
            return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_fees",
                                    "type": "function",
                                    "function": {"name": "get_fees", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            },
        )

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


async def _seed_fee(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    session.add(Building(id=BUILDING_ID, tenant_id=TENANT_ID, name="101", floors=15))
    await session.flush()
    session.add(
        Household(
            id=HOUSEHOLD_ID,
            tenant_id=TENANT_ID,
            building_id=BUILDING_ID,
            floor=3,
            unit_no=301,
            status="active",
        )
    )
    await session.flush()
    session.add(
        User(
            id=USER_ID,
            tenant_id=TENANT_ID,
            status="active",
            household_id=HOUSEHOLD_ID,
            approved_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC),
        )
    )
    await session.flush()
    session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=HOUSEHOLD_ID,
            period="2026-06",
            breakdown={"일반관리비": 80000, "청소비": 20000},
            total_amount=100000,
            source="excel",
        )
    )
    await session.flush()


def _client(db_session: AsyncSession, llm: LlmClient) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(TENANT_ID, USER_ID)
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_llm] = lambda: llm
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    name = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line[len("data:") :].strip())))
    return events


@pytest_asyncio.fixture
async def fee_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    await _seed_fee(db_session)
    async with _client(db_session, _fee_agent_llm()) as c:
        yield c


async def test_get_fees_tool_answers_with_persisted_tool_citation(
    fee_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    response = await fee_client.post("/assistant/ask", json={"question": "이번 달 관리비 알려줘"})
    assert response.status_code == 200
    events = _parse_sse(response.text)
    done = events[-1][1]
    assert events[-1][0] == "done"
    assert done["status"] == "answered"

    # 도구 결과 인용(citation SSE)에 document_id 없음(H2-5 완화 재사용).
    citations = [data for name, data in events if name == "citation"]
    assert citations and citations[0]["document_id"] is None
    assert "관리비 2026-06" in str(citations[0]["document_title"])

    # 인용 영속: source_kind=tool:get_fees.
    kind = await db_session.scalar(select(Citation.source_kind))
    assert kind == "tool:get_fees"


async def test_tool_path_does_not_mutate_domain_data(
    fee_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """규칙 8 — 도구는 읽기 전용. /ask 후에도 fees 행 수 불변(도구가 쓰지 않음)."""
    before = await db_session.scalar(select(func.count()).select_from(Fee))
    await fee_client.post("/assistant/ask", json={"question": "관리비?"})
    after = await db_session.scalar(select(func.count()).select_from(Fee))
    assert before == after == 1
