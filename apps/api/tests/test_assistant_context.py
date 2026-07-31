"""멀티턴 컨텍스트 + 되묻기의 api 배선 (H18-1, ADR-0025 §3·4).

히스토리 주입·상한 자체는 ai-core 테스트가 담당한다. 여기서는 api만 할 수 있는 것 —
DB 히스토리 로드 순서, 캐시 우회, clarify 영속 — 을 실 PG로 확인한다.
"""

from __future__ import annotations

import typing
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app.deps import RequestContext, get_context, get_llm, get_tenant_session
from app.main import create_app
from app.routers.assistant import _load_history
from app.schemas.assistant import AnswerStatus
from app.session import get_redis
from conftest import TENANT_ID, USER_ID
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from test_assistant import _parse_sse, _seed_indexed_document

from ai_core.llm.client import LlmClient
from liviq_db.models import Conversation, Message


def _client(db_session: AsyncSession, llm: LlmClient, redis: object) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(TENANT_ID, USER_ID)
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_redis] = lambda: redis
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded_client(
    db_session: AsyncSession, fake_llm: LlmClient, fake_redis: object
) -> AsyncIterator[httpx.AsyncClient]:
    await _seed_indexed_document(db_session)
    async with _client(db_session, fake_llm, fake_redis) as c:
        yield c


@pytest.fixture
def clarify_llm(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> LlmClient:
    """되묻기만 부르는 가짜 LLM — env를 먼저 세팅해야 fake_llm이 그 값으로 만들어진다."""
    monkeypatch.setenv("_TEST_LLM_TOOLS", "ask_clarification")
    return typing.cast(LlmClient, request.getfixturevalue("fake_llm"))


@pytest_asyncio.fixture
async def clarify_client(
    db_session: AsyncSession, clarify_llm: LlmClient, fake_redis: object
) -> AsyncIterator[httpx.AsyncClient]:
    await _seed_indexed_document(db_session)
    async with _client(db_session, clarify_llm, fake_redis) as c:
        yield c


def _done(body: str) -> dict[str, object]:
    events = _parse_sse(body)
    assert events[-1][0] == "done"
    return events[-1][1]


# ── 히스토리 로드 ──────────────────────────────────────────────────────


async def test_load_history_keeps_question_answer_order(db_session: AsyncSession) -> None:
    """같은 요청의 user/assistant는 created_at이 같다(트랜잭션 시각) — 순서가 뒤집히면 안 된다."""
    await _seed_indexed_document(db_session)
    conversation = Conversation(tenant_id=TENANT_ID, user_id=USER_ID, channel="resident")
    db_session.add(conversation)
    await db_session.flush()
    db_session.add_all(
        [
            Message(
                tenant_id=TENANT_ID,
                conversation_id=conversation.id,
                role="user",
                content="관리비 얼마야?",
            ),
            Message(
                tenant_id=TENANT_ID,
                conversation_id=conversation.id,
                role="assistant",
                content="몇 월 관리비를 말씀하시나요?",
                status="clarify",
            ),
        ]
    )
    await db_session.flush()

    history = await _load_history(db_session, RequestContext(TENANT_ID, USER_ID), conversation.id)
    assert history.turns == (
        ("user", "관리비 얼마야?"),
        ("assistant", "몇 월 관리비를 말씀하시나요?"),
    )
    # 직전 답변이 되묻기 → 다음 턴은 되묻기 도구를 감춘다(연속 금지).
    assert history.last_was_clarify is True


async def test_load_history_ignores_other_conversations(db_session: AsyncSession) -> None:
    """다른 대화의 메시지는 섞이지 않는다(대화 소유권은 라우터가 이미 검증)."""
    await _seed_indexed_document(db_session)
    mine = Conversation(tenant_id=TENANT_ID, user_id=USER_ID, channel="resident")
    other = Conversation(tenant_id=TENANT_ID, user_id=USER_ID, channel="resident")
    db_session.add_all([mine, other])
    await db_session.flush()
    db_session.add(
        Message(tenant_id=TENANT_ID, conversation_id=other.id, role="user", content="남의 대화")
    )
    await db_session.flush()

    history = await _load_history(db_session, RequestContext(TENANT_ID, USER_ID), mine.id)
    assert history.turns == ()
    assert history.last_was_clarify is False


# ── 캐시 우회 ──────────────────────────────────────────────────────────


async def test_second_turn_bypasses_answer_cache(
    seeded_client: httpx.AsyncClient, fake_redis: typing.Any
) -> None:
    """히스토리가 있으면 캐시를 조회하지도, 저장하지도 않는다(ADR-0025 §3)."""
    question = {"question": "주차장 언제 열어요?"}
    first = _done((await seeded_client.post("/assistant/ask", json=question)).text)
    assert first["status"] == "answered"
    cached_keys = await fake_redis.keys("cache:ans:*")
    assert len(cached_keys) == 1  # 첫 턴은 캐시에 남는다

    # 같은 질문 + 같은 대화 → 히스토리가 있으므로 재생하지 않고 LLM을 다시 탄다.
    second = _done(
        (
            await seeded_client.post(
                "/assistant/ask",
                json={**question, "conversation_id": first["conversation_id"]},
            )
        ).text
    )
    assert second["status"] == "answered"
    # 캐시 재생이면 usage가 0으로 고정된다 — 0이 아니면 실제로 LLM을 탔다는 뜻.
    assert typing.cast(int, second["token_input"]) > 0
    # 맥락 의존 답변은 저장하지 않는다 — 키가 늘지 않아야 한다.
    assert await fake_redis.keys("cache:ans:*") == cached_keys


async def test_first_turn_still_replays_cache(
    seeded_client: httpx.AsyncClient, fake_redis: typing.Any
) -> None:
    """회귀: 히스토리 없는 첫 턴은 기존대로 캐시 히트로 재생된다(LLM 호출 0)."""
    question = {"question": "주차장 언제 열어요?"}
    _done((await seeded_client.post("/assistant/ask", json=question)).text)
    replayed = _done((await seeded_client.post("/assistant/ask", json=question)).text)
    assert replayed["status"] == "answered"
    assert replayed["token_input"] == 0  # 재생은 LLM 호출 0


# ── 되묻기 ─────────────────────────────────────────────────────────────


async def test_clarify_is_streamed_and_persisted(
    clarify_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """되묻기는 done.status=clarify로 나가고, 다음 턴 맥락을 위해 메시지로 남는다."""
    response = await clarify_client.post("/assistant/ask", json={"question": "관리비 얼마야?"})
    events = _parse_sse(response.text)
    done = events[-1][1]
    assert done["status"] == "clarify"
    assert done["answer"] == "어느 달 관리비를 말씀하시나요?"
    assert done["fallback_reason"] is None
    assert not [name for name, _ in events if name == "token"]  # 답변 생성 경로 미실행

    stored = (await db_session.scalars(select(Message).where(Message.role == "assistant"))).all()
    assert len(stored) == 1
    assert stored[0].status == "clarify"
    assert stored[0].content == "어느 달 관리비를 말씀하시나요?"


async def test_consecutive_clarify_is_blocked(clarify_client: httpx.AsyncClient) -> None:
    """직전 턴이 되묻기면 다음 턴은 되묻지 않는다 — 스펙에서 빠져 무시된다(ADR-0025 §4)."""
    first = _done(
        (await clarify_client.post("/assistant/ask", json={"question": "관리비 얼마야?"})).text
    )
    assert first["status"] == "clarify"

    second = _done(
        (
            await clarify_client.post(
                "/assistant/ask",
                json={"question": "그냥 알려줘", "conversation_id": first["conversation_id"]},
            )
        ).text
    )
    assert second["status"] != "clarify"


async def test_unknown_conversation_is_rejected(seeded_client: httpx.AsyncClient) -> None:
    """회귀: 남의(또는 없는) 대화 id로 히스토리를 끌어올 수 없다(규칙 4)."""
    response = await seeded_client.post(
        "/assistant/ask", json={"question": "안녕", "conversation_id": str(uuid.uuid4())}
    )
    assert response.status_code == 404


def test_answer_status_literal_includes_clarify() -> None:
    """SSE done.status 리터럴 확장(계약 문서와 타입이 함께 움직이는지)."""
    assert set(typing.get_args(AnswerStatus)) == {"answered", "fallback", "clarify"}
