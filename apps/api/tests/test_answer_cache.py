"""AI 질의 정확 캐시 테스트 — 격리 CRITICAL + 재생·무효화·fail-open (H4-2).

격리 검증은 answer_cache 단위에서 직접 한다(키에 tenant·user/roles·visibilities·gen이
들어가는지 = 스코프 A에 저장한 답변이 스코프 B로 히트되지 않는지). 배선·재생·토큰0 영속은
/assistant/ask 통합 테스트로 확인한다(실 PG + 가짜 도구호출 LLM).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, cast

import httpx
import pytest
import pytest_asyncio
from app import answer_cache
from conftest import EMBED_DIM, TENANT_ID, USER_ID
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_assistant_tools import _client, _parse_sse, _seed_fee

from ai_core.citations import Citation
from ai_core.config import AiCoreSettings
from ai_core.llm.client import ChatUsage, LlmClient
from ai_core.orchestrator import (
    CitationEvent,
    DoneEvent,
    StatusEvent,
    TokenEvent,
    ToolCitation,
    ToolCitationEvent,
)
from ai_core.tools import ToolContext
from liviq_db.models import Message

if TYPE_CHECKING:
    from fakeredis.aioredis import FakeRedis

QUESTION = "이번 달 관리비 알려줘"
TENANT_B = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _ctx(
    *,
    tenant: uuid.UUID = TENANT_ID,
    user: uuid.UUID = USER_ID,
    roles: tuple[str, ...] = ("RESIDENT",),
    visibilities: tuple[str, ...] = ("ALL", "RESIDENT"),
) -> ToolContext:
    return ToolContext(tenant_id=tenant, user_id=user, roles=roles, visibilities=visibilities)


def _done(
    *,
    tool_path: tuple[str, ...],
    status: str = "answered",
    needs_review: bool = False,
) -> DoneEvent:
    return DoneEvent(
        status=status,
        confidence=0.9,
        needs_review=needs_review,
        usage=ChatUsage(input_tokens=12, output_tokens=6, estimated=True),
        fallback_reason=None,
        citations=(
            Citation(
                ref=1,
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                document_title="관리규약",
                quote="지하주차장은 24시간 개방한다.",
                page=None,
                clause="제2조",
            ),
        ),
        tool_citations=(
            ToolCitation(
                ref=2, title="관리비 2026-06", quote="100,000원", source_kind="tool:get_fees"
            ),
        ),
        answer="24시간 개방합니다 [1].",
        tool_path=tool_path,
    )


# ── 격리 CRITICAL ──────────────────────────────────────────────────────


async def test_personal_answer_not_served_to_other_user(fake_redis: FakeRedis) -> None:
    """개인 도구(get_fees) 경로 답변은 user 스코프 키 — 같은 tenant·다른 user는 히트 금지."""
    ctx_a = _ctx(user=USER_ID)
    await answer_cache.store(
        fake_redis, ctx=ctx_a, question=QUESTION, done=_done(tool_path=("get_fees",))
    )

    assert await answer_cache.lookup(fake_redis, ctx=ctx_a, question=QUESTION) is not None
    ctx_b = _ctx(user=USER_B)
    assert await answer_cache.lookup(fake_redis, ctx=ctx_b, question=QUESTION) is None


async def test_no_cross_tenant_propagation(fake_redis: FakeRedis) -> None:
    """다른 단지로 캐시가 새지 않는다 — 키의 tenant 세그먼트가 분리."""
    ctx_a = _ctx(tenant=TENANT_ID)
    await answer_cache.store(
        fake_redis, ctx=ctx_a, question=QUESTION, done=_done(tool_path=("search_documents",))
    )
    assert await answer_cache.lookup(fake_redis, ctx=ctx_a, question=QUESTION) is not None
    ctx_other = _ctx(tenant=TENANT_B)
    assert await answer_cache.lookup(fake_redis, ctx=ctx_other, question=QUESTION) is None


async def test_no_role_visibility_propagation(fake_redis: FakeRedis) -> None:
    """tenant 스코프 키는 roles·visibilities로 분리 — 공개범위 다르면 히트 금지."""
    ctx_res = _ctx(roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))
    await answer_cache.store(
        fake_redis, ctx=ctx_res, question=QUESTION, done=_done(tool_path=("search_documents",))
    )
    assert await answer_cache.lookup(fake_redis, ctx=ctx_res, question=QUESTION) is not None
    ctx_mgr = _ctx(roles=("MANAGER",), visibilities=("ALL", "RESIDENT", "ADMIN", "COUNCIL"))
    assert await answer_cache.lookup(fake_redis, ctx=ctx_mgr, question=QUESTION) is None


# ── 무효화·저장 정책 ────────────────────────────────────────────────────


async def test_reindex_bumps_generation_causes_miss(fake_redis: FakeRedis) -> None:
    """세대 증가(재색인·visibility 변경) 후 이전 키는 자연 미스."""
    ctx = _ctx()
    await answer_cache.store(
        fake_redis, ctx=ctx, question=QUESTION, done=_done(tool_path=("get_fees",))
    )
    assert await answer_cache.lookup(fake_redis, ctx=ctx, question=QUESTION) is not None
    await answer_cache.bump_generation(fake_redis, ctx.tenant_id)
    assert await answer_cache.lookup(fake_redis, ctx=ctx, question=QUESTION) is None


async def test_fallback_and_needs_review_not_cached(fake_redis: FakeRedis) -> None:
    """폴백·검수 대상은 캐시하지 않는다(규칙 1·6)."""
    ctx = _ctx()
    await answer_cache.store(
        fake_redis, ctx=ctx, question=QUESTION, done=_done(tool_path=(), status="fallback")
    )
    assert await answer_cache.lookup(fake_redis, ctx=ctx, question=QUESTION) is None
    await answer_cache.store(
        fake_redis, ctx=ctx, question=QUESTION, done=_done(tool_path=(), needs_review=True)
    )
    assert await answer_cache.lookup(fake_redis, ctx=ctx, question=QUESTION) is None


async def test_ttl_zero_disables_cache(
    fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CACHE_TTL_S=0 → 저장·조회 모두 no-op(캐시 전체 비활성)."""
    monkeypatch.setattr(answer_cache, "_ttl", lambda: 0)
    ctx = _ctx()
    await answer_cache.store(
        fake_redis, ctx=ctx, question=QUESTION, done=_done(tool_path=("get_fees",))
    )
    assert await answer_cache.lookup(fake_redis, ctx=ctx, question=QUESTION) is None


async def test_redis_failure_fail_open() -> None:
    """Redis 장애는 삼켜 정상 경로로(fail-open) — lookup은 None, store·bump는 예외 없음."""

    class _BrokenRedis:
        async def get(self, key: str) -> str | None:
            raise RedisError("down")

        async def set(self, *args: object, **kwargs: object) -> bool:
            raise RedisError("down")

        async def incr(self, key: str) -> int:
            raise RedisError("down")

    broken = cast(Redis, _BrokenRedis())
    ctx = _ctx()
    assert await answer_cache.lookup(broken, ctx=ctx, question=QUESTION) is None
    await answer_cache.store(
        broken, ctx=ctx, question=QUESTION, done=_done(tool_path=("get_fees",))
    )
    await answer_cache.bump_generation(broken, ctx.tenant_id)


# ── 재생 ───────────────────────────────────────────────────────────────


async def test_replay_yields_events_in_order_with_zero_tokens(fake_redis: FakeRedis) -> None:
    """히트 재생은 정상 경로와 동일한 이벤트 순서, done.usage 토큰 0(LLM 호출 없음)."""
    ctx = _ctx()
    await answer_cache.store(
        fake_redis, ctx=ctx, question=QUESTION, done=_done(tool_path=("get_fees",))
    )
    cached = await answer_cache.lookup(fake_redis, ctx=ctx, question=QUESTION)
    assert cached is not None

    events = [e async for e in answer_cache.replay(cached, tenant_id=ctx.tenant_id)]
    assert isinstance(events[0], StatusEvent) and events[0].stage == "searching"
    assert isinstance(events[1], StatusEvent) and events[1].stage == "generating"
    assert isinstance(events[2], TokenEvent) and events[2].text == "24시간 개방합니다 [1]."
    assert isinstance(events[3], StatusEvent) and events[3].stage == "verifying"
    assert any(isinstance(e, CitationEvent) for e in events)
    assert any(isinstance(e, ToolCitationEvent) for e in events)
    done = events[-1]
    assert isinstance(done, DoneEvent)
    assert done.status == "answered"
    assert done.usage is not None
    assert done.usage.input_tokens == 0 and done.usage.output_tokens == 0


async def test_replay_rejects_tenant_mismatch(fake_redis: FakeRedis) -> None:
    """재생 직전 tenant 불일치는 거부(격리 방어선, fail-closed)."""
    ctx = _ctx()
    await answer_cache.store(
        fake_redis, ctx=ctx, question=QUESTION, done=_done(tool_path=("get_fees",))
    )
    cached = await answer_cache.lookup(fake_redis, ctx=ctx, question=QUESTION)
    assert cached is not None
    with pytest.raises(answer_cache.CacheIsolationError):
        _ = [e async for e in answer_cache.replay(cached, tenant_id=TENANT_B)]


# ── 통합: 히트 재생(LLM 0) + 토큰0 영속 ─────────────────────────────────


def _counting_fee_llm() -> tuple[LlmClient, dict[str, int]]:
    """get_fees만 호출해 답변하는 가짜 LLM + chat/completions 호출 카운터."""
    counter = {"chat": 0}
    settings = AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="test",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )
    answer = "이번 달 관리비는 100,000원입니다."

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/embeddings"):
            texts = body["input"]
            data = [{"index": i, "embedding": [0.05] * EMBED_DIM} for i in range(len(texts))]
            return httpx.Response(200, json={"data": data})
        counter["chat"] += 1
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

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0), counter


@pytest_asyncio.fixture
async def fee_setup(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed_fee(db_session)
    yield db_session


async def test_cache_hit_replays_without_llm_and_persists_token_zero(
    fee_setup: AsyncSession,
) -> None:
    """두 번째 동일 질의는 히트 — LLM 호출 0으로 SSE 재생 + 메시지 영속(token 0)."""
    from fakeredis.aioredis import FakeRedis

    db_session = fee_setup
    redis = FakeRedis(decode_responses=True)
    llm, counter = _counting_fee_llm()
    async with _client(db_session, llm, redis=redis) as c:
        first = await c.post("/assistant/ask", json={"question": QUESTION})
        assert first.status_code == 200
        assert _parse_sse(first.text)[-1][1]["status"] == "answered"
        assert counter["chat"] > 0  # 정상 경로 — LLM 호출됨

        counter["chat"] = 0
        second = await c.post("/assistant/ask", json={"question": QUESTION})
        assert second.status_code == 200
        events = _parse_sse(second.text)

    assert counter["chat"] == 0  # 히트 — LLM 호출 0
    names = [name for name, _ in events]
    assert set(names) <= {"status", "token", "citation", "done"}  # SSE 4종 계약 불변
    assert "token" in names and names[-1] == "done"
    assert events[-1][1]["status"] == "answered"

    # 히트 응답도 대화 이력에 영속 — token 0(정직한 기록: LLM 호출 없음).
    rows = (
        await db_session.scalars(
            select(Message).where(Message.role == "assistant").order_by(Message.created_at)
        )
    ).all()
    assert len(rows) == 2
    assert rows[-1].token_input == 0 and rows[-1].token_output == 0
