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

from ai_core.backend_config import CONFIG_ROW_ID
from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from ai_core.tools.library import MIN_PEER_SAMPLE
from liviq_db.models import (
    AiBackendConfig,
    Building,
    Citation,
    Fee,
    Household,
    HouseholdGeometry,
    Tenant,
    User,
)

HOUSEHOLD_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


def _fee_agent_llm(
    *, answer: str = "이번 달 관리비는 100,000원입니다.", tool_args: str = "{}"
) -> LlmClient:
    """get_fees만 호출한 뒤 스트림 답변하는 가짜 도구호출 LLM(tool_args = 도구 인자)."""
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
                                    "function": {
                                        "name": "get_fees",
                                        "arguments": tool_args,
                                    },
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
            breakdown=[
                {"name": "일반관리비", "level": 0, "amount": 80000},
                {"name": "청소비", "level": 0, "amount": 20000},
            ],
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


async def test_tool_citation_carries_structured_data(fee_client: httpx.AsyncClient) -> None:
    """citation.data = 도구가 확정한 값 그대로(ADR-0025 §6) — LLM을 거치지 않는다.

    화면에 뿌려질 숫자는 fees 행의 값과 같아야 한다(규칙 5 — 확정 업로드 데이터가 단일 출처).
    """
    response = await fee_client.post("/assistant/ask", json={"question": "이번 달 관리비 알려줘"})
    citation = [data for name, data in _parse_sse(response.text) if name == "citation"][0]
    assert citation["data"] == {
        "kind": "fee_table",
        "period": "2026-06",
        "rows": [
            {"name": "일반관리비", "amount": 80000},
            {"name": "청소비", "amount": 20000},
        ],
        "total": 100000,
        "prev_total": None,  # 2026-05 행 없음
        "diff": None,
    }


# ── 여러 달 평균 (2026-08-01 사고 — 실 PG 집계) ────────────────────────────────


async def _add_fee(session: AsyncSession, period: str, total: int) -> None:
    session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=HOUSEHOLD_ID,
            period=period,
            breakdown=[{"name": "일반관리비", "level": 0, "amount": total}],
            total_amount=total,
            source="excel",
        )
    )
    await session.flush()


async def _multi_month_citation(db_session: AsyncSession, periods: str) -> dict[str, object]:
    llm = _fee_agent_llm(tool_args=json.dumps({"period": periods}))
    async with _client(db_session, llm) as client:
        response = await client.post("/assistant/ask", json={"question": "6,7월 관리비 평균은?"})
    citation = [data for name, data in _parse_sse(response.text) if name == "citation"][0]
    return citation["data"]  # type: ignore[return-value]


async def test_multi_month_average_comes_from_sql(db_session: AsyncSession) -> None:
    """평균은 PG 집계(avg OVER)가 낸 값 — 파이썬도 LLM도 나누지 않는다(규칙 5).

    사고 재현 방지: 6월 100,000 + 7월 120,000 → 평균 110,000이 도구 단계에서 확정된다.
    """
    await _seed_fee(db_session)  # 2026-06 = 100,000
    await _add_fee(db_session, "2026-07", 120_000)

    data = await _multi_month_citation(db_session, "2026-06,2026-07")
    assert data["months"] == [
        {"period": "2026-06", "total": 100_000},
        {"period": "2026-07", "total": 120_000},
    ]
    assert data["average_total"] == 110_000
    assert data["total"] is None  # 평균은 "합계" 칸에 들어가지 않는다


async def test_multi_month_without_all_data_refuses_average(db_session: AsyncSession) -> None:
    """있는 달로만 낸 평균은 주지 않는다 — 없는 달을 밝히고 평균은 비운다."""
    await _seed_fee(db_session)  # 2026-06만 존재

    data = await _multi_month_citation(db_session, "2026-06,2026-07")
    assert data["average_total"] is None
    assert data["missing_periods"] == ["2026-07"]
    assert data["months"] == [{"period": "2026-06", "total": 100_000}]


# ── 같은 평형 평균 비교 (H19-4 ①, ADR-0026 결정 3 — 실 PG 집계) ──────────────

_UNIT_LABEL = "84M(공공임대)"
_OTHER_LABEL = "59C(공공임대)"
_OTHER_TENANT_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")


async def _add_geometry(session: AsyncSession, household_id: uuid.UUID, label: str) -> None:
    session.add(
        HouseholdGeometry(
            tenant_id=TENANT_ID,
            household_id=household_id,
            polygon_2d=[],
            polygon_3d=[],
            base_z=0,
            floor_height=3,
            unit_type_label=label,
        )
    )
    await session.flush()


async def _seed_peer_group(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    building_id: uuid.UUID,
    label: str,
    amounts: list[int],
    floor: int,
) -> None:
    """같은 평형 라벨을 가진 세대 + 2026-06 관리비를 amounts 만큼 만든다."""
    for index, amount in enumerate(amounts):
        household = Household(
            tenant_id=tenant_id,
            building_id=building_id,
            floor=floor,
            unit_no=index + 1,
            status="active",
        )
        session.add(household)
        await session.flush()
        session.add(
            HouseholdGeometry(
                tenant_id=tenant_id,
                household_id=household.id,
                polygon_2d=[],
                polygon_3d=[],
                base_z=0,
                floor_height=3,
                unit_type_label=label,
            )
        )
        session.add(
            Fee(
                tenant_id=tenant_id,
                household_id=household.id,
                period="2026-06",
                breakdown=[],
                total_amount=amount,
                source="excel",
            )
        )
    await session.flush()


async def _seed_other_tenant_peers(session: AsyncSession) -> None:
    """타 단지의 같은 평형 세대 — 집계에 절대 섞이면 안 된다(규칙 3)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(_OTHER_TENANT_ID))
    )
    session.add(Tenant(id=_OTHER_TENANT_ID, name="단지B", status="active"))
    await session.flush()
    building = Building(tenant_id=_OTHER_TENANT_ID, name="901", floors=15)
    session.add(building)
    await session.flush()
    await _seed_peer_group(
        session,
        tenant_id=_OTHER_TENANT_ID,
        building_id=building.id,
        label=_UNIT_LABEL,
        amounts=[9_000_000] * 12,
        floor=7,
    )
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )


async def _fee_citation(db_session: AsyncSession) -> dict[str, object]:
    async with _client(db_session, _fee_agent_llm()) as client:
        response = await client.post("/assistant/ask", json={"question": "관리비 비교해줘"})
    citation = [data for name, data in _parse_sse(response.text) if name == "citation"][0]
    return citation["data"]  # type: ignore[return-value]


async def test_peer_average_aggregates_same_unit_type_in_own_tenant_only(
    db_session: AsyncSession,
) -> None:
    """평균은 같은 단지·같은 평형만 — 타 평형·타 단지 금액은 섞이지 않는다.

    본인 100,000 + 같은 평형 9세대 90,000 = 10세대 평균 91,000(SQL AVG 값 그대로).
    """
    await _seed_fee(db_session)
    await _add_geometry(db_session, HOUSEHOLD_ID, _UNIT_LABEL)
    await _seed_peer_group(
        db_session,
        tenant_id=TENANT_ID,
        building_id=BUILDING_ID,
        label=_UNIT_LABEL,
        amounts=[90_000] * 9,
        floor=5,
    )
    await _seed_peer_group(
        db_session,
        tenant_id=TENANT_ID,
        building_id=BUILDING_ID,
        label=_OTHER_LABEL,
        amounts=[500_000] * 12,
        floor=6,
    )
    await _seed_other_tenant_peers(db_session)

    data = await _fee_citation(db_session)
    assert data["peer"] == {
        "unit_type": "84M",  # 라벨 접두만(seed_fees_demo와 같은 규칙)
        "avg_total": 91_000,
        "sample_size": 10,
        "diff": 9_000,
    }


async def test_peer_average_omitted_below_min_sample(db_session: AsyncSession) -> None:
    """표본 하한 미달이면 비교를 거부하고 본인 세대 값만 답한다(소표본 역산 방지)."""
    await _seed_fee(db_session)
    await _add_geometry(db_session, HOUSEHOLD_ID, _UNIT_LABEL)
    await _seed_peer_group(
        db_session,
        tenant_id=TENANT_ID,
        building_id=BUILDING_ID,
        label=_UNIT_LABEL,
        amounts=[90_000] * (MIN_PEER_SAMPLE - 2),  # 본인 포함 하한 -1
        floor=5,
    )

    data = await _fee_citation(db_session)
    assert "peer" not in data
    assert data["total"] == 100_000  # 본인 값은 정상 반환


async def test_peer_average_omitted_without_geometry(db_session: AsyncSession) -> None:
    """본인 세대 평형 미상이면 비교만 생략 — 폴백이 아니다."""
    await _seed_fee(db_session)
    await _seed_peer_group(
        db_session,
        tenant_id=TENANT_ID,
        building_id=BUILDING_ID,
        label=_UNIT_LABEL,
        amounts=[90_000] * 12,
        floor=5,
    )

    data = await _fee_citation(db_session)
    assert "peer" not in data
    assert data["total"] == 100_000


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


# ── 튜닝 노브 배선 (H15-3) ──────────────────────────────────────────────────────


async def test_tool_confidence_knob_applies_to_ask(db_session: AsyncSession) -> None:
    """`ai_backend_config.tool_confidence`가 요청 단위로 오케스트레이터에 전달된다.

    도구 결과만으로 답한 경로의 done.confidence로 확인 — 관리자가 값을 바꾸면 재시작 없이
    다음 요청부터 반영된다(H15-3).
    """
    await _seed_fee(db_session)
    db_session.add(
        AiBackendConfig(
            id=CONFIG_ROW_ID,
            base_url="http://llm.test/v1",
            model="test",
            tool_confidence=0.42,
            answer_cache_ttl_s=0,  # 캐시 끔 — 신뢰도 관측이 캐시 재생에 가려지지 않게
        )
    )
    await db_session.flush()

    async with _client(db_session, _fee_agent_llm()) as c:
        response = await c.post("/assistant/ask", json={"question": "이번 달 관리비 알려줘"})

    done = _parse_sse(response.text)[-1]
    assert done[0] == "done"
    assert done[1]["confidence"] == 0.42
