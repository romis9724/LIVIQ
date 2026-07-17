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
from app.session import get_redis
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


def _client(
    db_session: AsyncSession,
    llm: LlmClient,
    *,
    roles: tuple[str, ...] = (),
    redis: object | None = None,
) -> httpx.AsyncClient:
    from fakeredis.aioredis import FakeRedis

    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(TENANT_ID, USER_ID, roles=roles)
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_llm] = lambda: llm
    # 레이트 리밋용 Redis — 기본은 fakeredis(한도 넉넉, 결정론). 초과 시나리오는 스텁 주입.
    app.dependency_overrides[get_redis] = lambda: redis or FakeRedis(decode_responses=True)
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


async def test_ask_done_carries_tool_path(
    fee_client: httpx.AsyncClient,
) -> None:
    """회귀 — /assistant/ask done 이벤트에 tool_path(호출 도구 이름) 추가(H3-4, additive)."""
    response = await fee_client.post("/assistant/ask", json={"question": "관리비?"})
    done = _parse_sse(response.text)[-1]
    assert done[0] == "done"
    assert done[1]["tool_path"] == ["get_fees"]


# ── 시설 AI 도우미 (POST /admin/facilities/assistant, H3-4) ────────────────────


async def test_facility_assistant_forbidden_for_resident(db_session: AsyncSession) -> None:
    """RESIDENT는 시설 도우미 접근 불가(규칙 4 — 서버 인가, 403)."""
    await _seed_fee(db_session)
    async with _client(db_session, _fee_agent_llm(), roles=("RESIDENT",)) as c:
        response = await c.post("/admin/facilities/assistant", json={"question": "승강기 소음"})
    assert response.status_code == 403


async def test_facility_assistant_streams_four_events_with_tool_path(
    db_session: AsyncSession,
) -> None:
    """MANAGER는 시설 도우미로 SSE 4이벤트 응답 + done.tool_path 포함(계약 불변)."""
    await _seed_fee(db_session)
    async with _client(db_session, _fee_agent_llm(), roles=("MANAGER",)) as c:
        response = await c.post(
            "/admin/facilities/assistant", json={"question": "승강기 원인 후보"}
        )
    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = {name for name, _ in events}
    # SSE 이벤트 타입 4종 리터럴만(status·token·citation·done) — 확장 없음.
    assert names <= {"status", "token", "citation", "done"}
    done = events[-1]
    assert done[0] == "done"
    assert done[1]["status"] == "answered"
    assert done[1]["tool_path"] == ["get_fees"]


# ── 레이트 리밋 엔드포인트 배선 (H4-1) ──────────────────────────────────────────


class _OverLimitRedis:
    """INCR가 항상 상한을 넘는 값을 돌려주는 스텁 — 429 배선 검증용."""

    async def incr(self, key: str) -> int:
        return 10_000

    async def expire(self, key: str, ttl: int) -> bool:  # pragma: no cover — 도달 안 함
        return True


async def test_ask_returns_429_when_rate_limited(db_session: AsyncSession) -> None:
    """/assistant/ask에 레이트 리밋 의존성이 배선돼 초과 시 429 + Retry-After."""
    await _seed_fee(db_session)
    async with _client(db_session, _fee_agent_llm(), redis=_OverLimitRedis()) as c:
        response = await c.post("/assistant/ask", json={"question": "관리비?"})
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"


async def test_facility_assistant_returns_429_when_rate_limited(db_session: AsyncSession) -> None:
    """시설 도우미 엔드포인트도 레이트 리밋 배선 — 초과 시 429(역할 통과 후에도)."""
    await _seed_fee(db_session)
    async with _client(
        db_session, _fee_agent_llm(), roles=("MANAGER",), redis=_OverLimitRedis()
    ) as c:
        response = await c.post("/admin/facilities/assistant", json={"question": "승강기?"})
    assert response.status_code == 429
