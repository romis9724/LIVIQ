"""운영 대시보드 집계 통합 테스트 — 실 PG + 역할 가드·비율 정합(H4-3, FR-ADM-06).

시드: assistant 메시지 3건(answered 2·fallback 1, 검수 플래그 1, 토큰 일부 null) +
민원 3건(received 2·done 1) + 시설 2건(normal 1·fault 1). 기대값은 각 집계식으로 계산.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import AsyncIterator, Iterator

import httpx
import pytest
import pytest_asyncio
from app.config import get_settings
from app.deps import RequestContext, get_context, get_tenant_session
from app.main import create_app
from app.session import get_redis
from conftest import MANAGER_USER_ID, TENANT_ID, seed_tenant
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Conversation, Facility, Inquiry, Message


async def _seed_dashboard(session: AsyncSession) -> None:
    households = await seed_tenant(session)
    household_id = households[(3, 301)]

    conversation = Conversation(tenant_id=TENANT_ID, user_id=MANAGER_USER_ID, channel="admin")
    session.add(conversation)
    await session.flush()

    # 제외 대상 — user 메시지는 assistant 집계에 잡히지 않아야 한다.
    session.add(
        Message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            role="user",
            content="질문",
        )
    )
    # answered·토큰 있음·검수 플래그 없음.
    session.add(
        Message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            role="assistant",
            content="답변1",
            status="answered",
            token_input=100,
            token_output=200,
        )
    )
    # answered·토큰 있음·검수 대기.
    session.add(
        Message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            role="assistant",
            content="답변2",
            status="answered",
            review_status="needs_review",
            token_input=300,
            token_output=400,
        )
    )
    # fallback·토큰 null(평균에서 제외돼야 한다).
    session.add(
        Message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            role="assistant",
            content="담당자 연결",
            status="fallback",
        )
    )

    for status in ("received", "received", "done"):
        session.add(
            Inquiry(
                tenant_id=TENANT_ID,
                household_id=household_id,
                author_user_id=MANAGER_USER_ID,
                title="민원",
                body="본문",
                status=status,
            )
        )
    session.add(Facility(tenant_id=TENANT_ID, name="승강기", status="normal"))
    session.add(Facility(tenant_id=TENANT_ID, name="펌프", status="fault"))
    await session.flush()


def _client(
    db_session: AsyncSession,
    *,
    roles: tuple[str, ...] = ("MANAGER",),
    redis: object | None = None,
) -> httpx.AsyncClient:
    from fakeredis.aioredis import FakeRedis

    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, MANAGER_USER_ID, roles=roles
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_redis] = lambda: redis or FakeRedis(decode_responses=True)
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def dash_client(db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    await _seed_dashboard(db_session)
    async with _client(db_session) as c:
        yield c


async def test_stats_aggregates_match_seed(dash_client: httpx.AsyncClient) -> None:
    response = await dash_client.get("/admin/dashboard/stats")
    assert response.status_code == 200
    body = response.json()

    ai = body["ai"]
    assert ai["query_count"] == 3  # assistant만(user 메시지 제외)
    assert ai["avg_token_input"] == 200.0  # avg(100, 300) — null 제외
    assert ai["avg_token_output"] == 300.0  # avg(200, 400)
    assert ai["answer_rate"] == 2 / 3
    assert ai["fallback_rate"] == 1 / 3
    assert ai["needs_review_rate"] == 1 / 3

    # 캐시 카운터 미설정 → 0·null(0 나누기 회피).
    assert body["cache"] == {"hits": 0, "misses": 0, "hit_rate": None}

    assert body["inquiries"] == {"received": 2, "assigned": 0, "in_progress": 0, "done": 1}
    assert body["facilities"] == {"normal": 1, "check": 0, "fault": 1, "risk": 0}


async def test_stats_cache_hit_rate(db_session: AsyncSession) -> None:
    """H4-2 Redis 카운터를 읽어 적중률 계산 — hits/(hits+misses)."""
    from fakeredis.aioredis import FakeRedis

    await _seed_dashboard(db_session)
    redis = FakeRedis(decode_responses=True)
    await redis.set(f"cache:hits:{TENANT_ID}", 7)
    await redis.set(f"cache:misses:{TENANT_ID}", 3)
    async with _client(db_session, redis=redis) as c:
        response = await c.get("/admin/dashboard/stats")
    assert response.status_code == 200
    assert response.json()["cache"] == {"hits": 7, "misses": 3, "hit_rate": 0.7}


async def test_stats_empty_period_yields_null_rates(db_session: AsyncSession) -> None:
    """집계 대상 0건이면 비율은 null(분모 0), 카운트는 0."""
    await seed_tenant(db_session)
    async with _client(db_session) as c:
        response = await c.get("/admin/dashboard/stats")
    body = response.json()
    ai = body["ai"]
    assert ai["query_count"] == 0
    assert ai["avg_token_input"] is None
    assert ai["answer_rate"] is None
    assert ai["fallback_rate"] is None
    assert ai["needs_review_rate"] is None


async def test_stats_forbidden_for_staff(db_session: AsyncSession) -> None:
    """STAFF는 대시보드 접근 불가(MANAGER 전용, 규칙 4 — 403)."""
    await _seed_dashboard(db_session)
    async with _client(db_session, roles=("STAFF",)) as c:
        response = await c.get("/admin/dashboard/stats")
    assert response.status_code == 403


async def test_stats_forbidden_for_resident(db_session: AsyncSession) -> None:
    await _seed_dashboard(db_session)
    async with _client(db_session, roles=("RESIDENT",)) as c:
        response = await c.get("/admin/dashboard/stats")
    assert response.status_code == 403


async def test_days_param_out_of_range_returns_422(dash_client: httpx.AsyncClient) -> None:
    """days 범위 검증(1~90) — 경계 밖은 422."""
    assert (await dash_client.get("/admin/dashboard/stats?days=0")).status_code == 422
    assert (await dash_client.get("/admin/dashboard/stats?days=91")).status_code == 422
    assert (await dash_client.get("/admin/dashboard/stats?days=90")).status_code == 200


# ── 일일 토큰 예산 (H4-4, NFR-COST-01 — 경고만·차단 없음) ──────────────────────
# 시드 assistant 토큰 합계: (100+200)+(300+400)=1000, fallback 은 null→0.
_SEED_USED_TODAY = 1000


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """예산 env 오버라이드가 다른 테스트로 새지 않도록 lru_cache 초기화."""
    yield
    get_settings.cache_clear()


def _set_budget(monkeypatch: pytest.MonkeyPatch, value: int) -> None:
    monkeypatch.setenv("LLM_DAILY_TOKEN_BUDGET", str(value))
    get_settings.cache_clear()


async def test_budget_disabled_by_default(dash_client: httpx.AsyncClient) -> None:
    """예산 미설정(0)이면 enabled·exceeded 모두 false — used_today 는 그대로 집계."""
    body = (await dash_client.get("/admin/dashboard/stats")).json()
    assert body["budget"] == {
        "enabled": False,
        "budget": 0,
        "used_today": _SEED_USED_TODAY,
        "exceeded": False,
    }


async def test_budget_within_limit_not_exceeded(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """예산 내 사용이면 enabled true·exceeded false."""
    await _seed_dashboard(db_session)
    _set_budget(monkeypatch, 100_000)
    async with _client(db_session) as c:
        body = (await c.get("/admin/dashboard/stats")).json()
    assert body["budget"] == {
        "enabled": True,
        "budget": 100_000,
        "used_today": _SEED_USED_TODAY,
        "exceeded": False,
    }


async def test_budget_exceeded_flags_and_logs_warning(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """예산 초과면 exceeded true + 구조화 warning 로그(tenant·used·budget) — 차단은 없음."""
    await _seed_dashboard(db_session)
    _set_budget(monkeypatch, 500)  # used 1000 > 500
    with caplog.at_level(logging.WARNING, logger="app.dashboard"):
        async with _client(db_session) as c:
            response = await c.get("/admin/dashboard/stats")
    assert response.status_code == 200  # 초과해도 200 — 차단 금지
    assert response.json()["budget"]["exceeded"] is True

    warnings = [r for r in caplog.records if "daily-token-budget" in r.getMessage()]
    assert len(warnings) == 1
    message = warnings[0].getMessage()
    assert str(TENANT_ID) in message
    assert "used=1000" in message
    assert "budget=500" in message


async def test_budget_used_today_excludes_earlier_days(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """used_today 는 UTC 자정 이후만 — 어제 메시지 토큰은 제외(cutoff 경계)."""
    await seed_tenant(db_session)
    conversation = Conversation(tenant_id=TENANT_ID, user_id=MANAGER_USER_ID, channel="admin")
    db_session.add(conversation)
    await db_session.flush()
    yesterday = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=1)
    db_session.add(
        Message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            role="assistant",
            content="어제",
            status="answered",
            token_input=5000,
            token_output=5000,
            created_at=yesterday,
        )
    )
    db_session.add(
        Message(
            tenant_id=TENANT_ID,
            conversation_id=conversation.id,
            role="assistant",
            content="오늘",
            status="answered",
            token_input=100,
            token_output=100,
        )
    )
    await db_session.flush()

    _set_budget(monkeypatch, 1000)
    async with _client(db_session) as c:
        body = (await c.get("/admin/dashboard/stats")).json()
    # 오늘 200 만 집계(어제 10000 제외) → 예산 1000 내라 미초과.
    assert body["budget"]["used_today"] == 200
    assert body["budget"]["exceeded"] is False
