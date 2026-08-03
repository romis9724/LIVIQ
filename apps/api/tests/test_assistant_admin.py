"""관리자 홈 AI 비서 `POST /admin/assistant/ask` (H20-2, ADR-0028 결정 2).

스트림·영속은 입주민 ask와 같은 헬퍼라 이미 검증돼 있다. 여기서는 이 엔드포인트에만
있는 것 — 역할 게이트(CRITICAL)와 admin 채널의 답변 캐시 우회 — 를 실 PG로 확인한다.
"""

from __future__ import annotations

import datetime
import typing
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from app import answer_cache
from app.ai_backend import backend_id
from app.deps import (
    RequestContext,
    get_context,
    get_llm,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from app.routers.assistant import _admin_overrides, _History
from app.session import get_redis
from conftest import TENANT_ID, USER_ID
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession
from test_assistant import _parse_sse, _seed_conversation, _seed_indexed_document

from ai_core.llm.client import LlmClient
from ai_core.orchestrator import DoneEvent
from ai_core.rag.prompt import (
    ADMIN_AGENT_ASK_UNIT_PROMPT,
    ADMIN_AGENT_SYSTEM_PROMPT,
    ADMIN_AGENT_UNIT_PROMPT,
    ADMIN_ANSWER_SYSTEM_PROMPT,
    AGENT_SYSTEM_PROMPT,
    ANSWER_SYSTEM_PROMPT,
)
from ai_core.tools import ToolContext
from ai_core.tools.clarify import CLARIFY_TOOL_NAME
from ai_core.tools.floor_plan import HOUSEHOLD_DEVICES_TOOL

ADMIN_ASK = "/admin/assistant/ask"
ADMIN_LATEST = "/admin/assistant/conversations/latest"
QUESTION = "주차장 언제 열어요?"
# 캐시에만 있고 가짜 LLM은 절대 내지 않는 문장 — 재생 여부를 답변 본문으로 가른다.
CACHED_ANSWER = "캐시에 남아 있던 옛 답변입니다 [1]."


def _client(
    db_session: AsyncSession, llm: LlmClient, redis: object, *, roles: tuple[str, ...]
) -> httpx.AsyncClient:
    app = create_app()
    ctx = RequestContext(TENANT_ID, USER_ID, roles=roles, visibilities=visibilities_for(roles))
    app.dependency_overrides[get_context] = lambda: ctx
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_redis] = lambda: redis
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def doc_only_llm(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> LlmClient:
    """문서 검색만 부르는 가짜 LLM — 관리자에겐 입주민 전용 도구(get_fees)가 없다.

    env를 먼저 세팅해야 fake_llm이 그 값으로 만들어진다(clarify_llm과 같은 패턴).
    """
    monkeypatch.setenv("_TEST_LLM_TOOLS", "search_documents")
    return typing.cast(LlmClient, request.getfixturevalue("fake_llm"))


@pytest_asyncio.fixture
async def manager_client(
    db_session: AsyncSession, doc_only_llm: LlmClient, fake_redis: object
) -> AsyncIterator[httpx.AsyncClient]:
    await _seed_indexed_document(db_session)
    async with _client(db_session, doc_only_llm, fake_redis, roles=("MANAGER",)) as c:
        yield c


@pytest.fixture
def system_prompts(
    doc_only_llm: LlmClient, monkeypatch: pytest.MonkeyPatch
) -> dict[str, list[str]]:
    """두 turn에 실제로 실린 시스템 프롬프트 기록 — agent=도구 결정, answer=최종 답변."""
    captured: dict[str, list[str]] = {"agent": [], "answer": []}

    def spy(kind: str, original: typing.Any) -> typing.Any:
        def wrapped(messages: typing.Any, **kwargs: typing.Any) -> typing.Any:
            captured[kind].append(str(messages[0]["content"]))
            return original(messages, **kwargs)

        return wrapped

    monkeypatch.setattr(doc_only_llm, "chat", spy("agent", doc_only_llm.chat))
    monkeypatch.setattr(doc_only_llm, "chat_stream", spy("answer", doc_only_llm.chat_stream))
    return captured


@pytest.fixture
def tool_names(doc_only_llm: LlmClient, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """결정 turn마다 실제로 스펙에 실린 도구 이름(가시성 검증용)."""
    captured: list[list[str]] = []
    original = doc_only_llm.chat

    def wrapped(messages: typing.Any, **kwargs: typing.Any) -> typing.Any:
        specs = kwargs.get("tools") or []
        captured.append([s["function"]["name"] for s in specs])
        return original(messages, **kwargs)

    monkeypatch.setattr(doc_only_llm, "chat", wrapped)
    return captured


def _done(body: str) -> dict[str, object]:
    events = _parse_sse(body)
    assert events[-1][0] == "done"
    return events[-1][1]


async def _seed_cached_answer(
    redis: object, llm: LlmClient, *, roles: tuple[str, ...]
) -> list[str]:
    """호출자와 **같은 키**가 되도록 캐시를 심고, 심긴 키 목록을 돌려준다.

    building_id=None인 것은 라우터와 같다 — 관리자는 역할로 면제되고, 시드 입주민은 세대가
    없다. 키가 어긋나면 우회 테스트가 공허해지므로 입주민 대조 테스트가 이 헬퍼를 검증한다.
    """
    await answer_cache.store(
        redis,  # type: ignore[arg-type]
        ctx=ToolContext(
            tenant_id=TENANT_ID,
            user_id=USER_ID,
            roles=roles,
            visibilities=visibilities_for(roles),
            building_id=None,
        ),
        question=QUESTION,
        done=DoneEvent(
            status="answered",
            confidence=0.9,
            needs_review=False,
            usage=None,
            answer=CACHED_ANSWER,
        ),
        backend=backend_id(llm.settings),
    )
    keys = await redis.keys("cache:ans:*")  # type: ignore[attr-defined]
    assert len(keys) == 1, "캐시 시드 실패 — 키가 1개여야 한다"
    return typing.cast(list[str], keys)


# ── 역할 게이트 ────────────────────────────────────────────────────────


async def test_resident_cannot_use_admin_assistant(
    db_session: AsyncSession, fake_llm: LlmClient, fake_redis: object
) -> None:
    """CRITICAL 인가(규칙 4) — 입주민 세션은 관리자 어시스턴트에 접근할 수 없다."""
    await _seed_indexed_document(db_session)
    async with _client(db_session, fake_llm, fake_redis, roles=("RESIDENT",)) as c:
        response = await c.post(ADMIN_ASK, json={"question": QUESTION})

    assert response.status_code == 403


async def test_manager_streams_answer(manager_client: httpx.AsyncClient) -> None:
    """MANAGER는 입주민 ask와 동일한 SSE 4종으로 답변을 받는다."""
    response = await manager_client.post(ADMIN_ASK, json={"question": QUESTION})

    assert response.status_code == 200
    events = _parse_sse(response.text)
    names = [name for name, _ in events]
    assert {"status", "token", "citation"} <= set(names)
    assert names[-1] == "done"
    assert events[-1][1]["status"] == "answered"


_GENERAL = (ANSWER_SYSTEM_PROMPT, AGENT_SYSTEM_PROMPT, (), None, None)
# 동·호수가 확정된 질의에서 감추는 도구 — 공용 설비 목록(H20-16) + 되묻기(H20-17b).
_UNIT_HIDDEN = ("get_facilities", CLARIFY_TOOL_NAME)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        # 세대 평면도 설비 위치 + 동·호수 있음 → 되묻기 금지 + 공용 설비 목록 도구 감춤 +
        # 그 세대를 조회 대상으로 실어 보낸다(H20-17). 조회 질의 원문도 함께 간다(H20-17b).
        (
            "404동 301호 콘센트는 어디에 있지?",
            (
                ADMIN_ANSWER_SYSTEM_PROMPT,
                ADMIN_AGENT_UNIT_PROMPT,
                _UNIT_HIDDEN,
                ("404", 301),
                "404동 301호 콘센트는 어디에 있지?",
            ),
        ),
        # 동의어(H20-7)도 같은 판정 — 대상 세대만 다르다
        (
            "402동 201호 두꺼비집 어디에 있어?",
            (
                ADMIN_ANSWER_SYSTEM_PROMPT,
                ADMIN_AGENT_UNIT_PROMPT,
                _UNIT_HIDDEN,
                ("402", 201),
                "402동 201호 두꺼비집 어디에 있어?",
            ),
        ),
        # 동·호수 없음 → 되묻기 예외(조회 대상 없음 = 세대 도구 비노출)
        (
            "콘센트 어디 있는지 알려줘",
            (ADMIN_ANSWER_SYSTEM_PROMPT, ADMIN_AGENT_ASK_UNIT_PROMPT, (), None, None),
        ),
        # 공용 설비 위치는 되묻기 대상이 아니다(사용자 지시 2026-08-03)
        ("승강기는 어디에 있나요?", _GENERAL),
        # 설비 현황·대수 질의는 위치 질문이 아니다 — 골든셋 시설 클래스가 여기 걸리면 회귀
        ("소방 설비 현황을 알려주세요.", _GENERAL),
        ("단지 공용 설비가 총 몇 개인가요?", _GENERAL),
        ("미배정 민원 몇 건인가요?", _GENERAL),
    ],
)
def test_admin_overrides_scope(
    question: str,
    expected: tuple[str, str, tuple[str, ...], tuple[str, int] | None, str | None],
) -> None:
    """관리자 변형은 **세대 평면도 설비 위치 질의**에만 걸린다(H20-16·H20-17)."""
    assert _admin_overrides(question, _History()) == expected


# ── 되묻기 후속 턴 합성(H20-17b) ───────────────────────────────────────


def _after_clarify(question: str) -> _History:
    """직전 턴이 되묻기였던 히스토리 — 되물은 문장까지 그대로 담는다."""
    return _History(
        turns=(
            ("user", question),
            ("assistant", "어느 동·호수를 말씀하시나요? (예: 401동 201호)"),
        ),
        last_was_clarify=True,
        last_user_question=question,
    )


def test_clarify_followup_answers_original_question() -> None:
    """되묻기에 답한 짧은 후속 턴은 원 질문과 합쳐 판정한다 — 현재 턴만 보면 설비 어휘가 없다."""
    overrides = _admin_overrides("401동 201호", _after_clarify("콘센트 어디 있어?"))

    assert overrides.target_unit == ("401", 201)
    assert overrides.agent_prompt == ADMIN_AGENT_UNIT_PROMPT
    assert overrides.exclude_tools == _UNIT_HIDDEN
    # 조회 질의에는 요소 어휘가 남아 있어야 한다 — 없으면 도구가 위치를 특정하지 못한다.
    assert "콘센트" in (overrides.target_query or "")


def test_clarify_followup_prefers_the_unit_just_answered() -> None:
    """원 질문에 다른 동·호수가 있어도 방금 답한 세대가 이긴다(현재 턴을 앞에 둔다)."""
    overrides = _admin_overrides("405동 101호요", _after_clarify("402동 201호 콘센트 어디?"))

    assert overrides.target_unit == ("405", 101)


def test_followup_without_clarify_is_not_merged() -> None:
    """되묻기가 아니었던 직전 턴은 합치지 않는다 — 앞 턴의 세대가 무관한 질의에 달라붙는다."""
    history = _History(
        turns=(("user", "402동 201호 콘센트 어디?"), ("assistant", "거실 왼쪽입니다.")),
        last_was_clarify=False,
        last_user_question="402동 201호 콘센트 어디?",
    )

    assert _admin_overrides("승강기는 어디에 있나요?", history) == _GENERAL


async def test_admin_ask_wires_overrides_into_both_turns(
    manager_client: httpx.AsyncClient, system_prompts: dict[str, list[str]]
) -> None:
    """일반 관리자 질의는 공통 프롬프트 — 변형이 전 질의로 새지 않는다(H20-16)."""
    await manager_client.post(ADMIN_ASK, json={"question": QUESTION})

    assert system_prompts["answer"][-1] == ANSWER_SYSTEM_PROMPT
    # 결정 turn은 날짜 문장이 뒤에 붙으므로 접두 비교(agent_system_prompt)
    assert system_prompts["agent"][0].startswith(AGENT_SYSTEM_PROMPT)


async def test_admin_ask_home_device_question_uses_admin_prompts(
    manager_client: httpx.AsyncClient, system_prompts: dict[str, list[str]]
) -> None:
    """세대 설비 위치 질의는 두 turn 다 관리자 변형 + 공용 설비 목록 도구 비노출."""
    await manager_client.post(ADMIN_ASK, json={"question": "404동 301호 콘센트는 어디에 있지?"})

    assert system_prompts["answer"][-1] == ADMIN_ANSWER_SYSTEM_PROMPT
    assert system_prompts["agent"][0].startswith(ADMIN_AGENT_SYSTEM_PROMPT)


async def test_household_devices_tool_visible_only_with_unit(
    manager_client: httpx.AsyncClient, tool_names: list[list[str]]
) -> None:
    """세대 평면도 도구는 **동·호수가 확정된 질의에서만** 스펙에 실린다(H20-17)."""
    await manager_client.post(ADMIN_ASK, json={"question": "404동 301호 콘센트는 어디에 있지?"})

    assert HOUSEHOLD_DEVICES_TOOL in tool_names[0]
    assert "get_facilities" not in tool_names[0]  # 단지 공용 설비 목록은 계속 감춘다(H20-16)
    # 조회 대상이 확정됐으면 되물을 것이 없다 — 프롬프트가 아니라 **스펙에서** 뺀다(H20-17b:
    # qwen3-8b가 "되묻지 말라"는 지시를 받고도 '어떤 설비를 말씀하시나요?'로 되물었다).
    assert CLARIFY_TOOL_NAME not in tool_names[0]


async def test_clarify_followup_turn_exposes_household_devices_tool(
    manager_client: httpx.AsyncClient, db_session: AsyncSession, tool_names: list[list[str]]
) -> None:
    """되묻기 후속 턴("401동 201호")도 세대 도구가 실린다 — 원 질문과 합쳐 판정(H20-17b).

    이 배선이 없으면 후속 턴에는 설비 어휘가 없어 오버라이드가 통째로 풀리고, 세대 도구가
    노출조차 되지 않아 답할 방법이 사라진다(2026-08-03 dev 실측: 전부 no_evidence 폴백).
    """
    conversation_id = await _seed_conversation(
        db_session,
        channel="admin",
        at=_now(),
        messages=(
            ("user", "콘센트 어디 있어?", None),
            ("assistant", "어느 동·호수를 말씀하시나요? (예: 401동 201호)", "clarify"),
        ),
    )

    await manager_client.post(
        ADMIN_ASK, json={"question": "401동 201호", "conversation_id": str(conversation_id)}
    )

    assert HOUSEHOLD_DEVICES_TOOL in tool_names[0]
    assert "get_facilities" not in tool_names[0]


@pytest.mark.parametrize(
    "question",
    [
        "콘센트 어디 있는지 알려줘",  # 위치 질의지만 동·호수 없음 → 되묻기 경로
        "승강기는 어디에 있나요?",  # 공용 설비 — 관리자 변형 자체가 안 걸린다
        QUESTION,
    ],
)
async def test_household_devices_tool_hidden_without_unit(
    manager_client: httpx.AsyncClient, tool_names: list[list[str]], question: str
) -> None:
    """조회 대상 세대가 없으면 노출도 하지 않는다 — 다른 질의로 새는 경로를 없앤다."""
    await manager_client.post(ADMIN_ASK, json={"question": question})

    assert HOUSEHOLD_DEVICES_TOOL not in tool_names[0]


async def test_resident_ask_never_sees_household_devices_tool(
    db_session: AsyncSession,
    doc_only_llm: LlmClient,
    fake_redis: object,
    tool_names: list[list[str]],
) -> None:
    """CRITICAL 인가(규칙 4) — 입주민 채널은 동·호수를 적어도 타 세대 도구를 못 본다."""
    await _seed_indexed_document(db_session)
    async with _client(db_session, doc_only_llm, fake_redis, roles=("RESIDENT",)) as c:
        await c.post("/assistant/ask", json={"question": "404동 301호 콘센트는 어디에 있지?"})

    assert HOUSEHOLD_DEVICES_TOOL not in tool_names[0]


async def test_resident_ask_keeps_general_prompts(
    db_session: AsyncSession,
    doc_only_llm: LlmClient,
    fake_redis: object,
    system_prompts: dict[str, list[str]],
) -> None:
    """대조군 — 입주민 채널은 세대 설비 위치 질의에도 공통 프롬프트다(본인 세대 도구가 답한다)."""
    await _seed_indexed_document(db_session)
    async with _client(db_session, doc_only_llm, fake_redis, roles=("RESIDENT",)) as c:
        await c.post("/assistant/ask", json={"question": "404동 301호 콘센트는 어디에 있지?"})

    assert system_prompts["answer"] == [ANSWER_SYSTEM_PROMPT]
    assert system_prompts["agent"][0].startswith(AGENT_SYSTEM_PROMPT)
    assert "ask_clarification" not in system_prompts["agent"][0]


# ── 답변 캐시 우회(ADR-0028 결정 2) ────────────────────────────────────


async def test_admin_ask_ignores_cached_answer(
    manager_client: httpx.AsyncClient, doc_only_llm: LlmClient, fake_redis: typing.Any
) -> None:
    """같은 키의 캐시가 있어도 admin 채널은 재생하지 않는다 — 운영 데이터는 매번 새로 읽는다."""
    await _seed_cached_answer(fake_redis, doc_only_llm, roles=("MANAGER",))

    done = _done((await manager_client.post(ADMIN_ASK, json={"question": QUESTION})).text)

    assert done["answer"] != CACHED_ANSWER
    assert typing.cast(int, done["token_input"]) > 0  # 재생이면 usage가 0으로 고정된다


async def test_admin_ask_does_not_store_answer_in_cache(
    manager_client: httpx.AsyncClient, fake_redis: typing.Any
) -> None:
    """admin 답변은 캐시에 남지 않는다 — 입주민 채널로 재생될 여지를 만들지 않는다."""
    done = _done((await manager_client.post(ADMIN_ASK, json={"question": QUESTION})).text)
    assert done["status"] == "answered"  # 저장 조건(answered)을 만족한 답변인데도

    assert await fake_redis.keys("cache:ans:*") == []


async def test_resident_ask_still_replays_same_seeded_key(
    db_session: AsyncSession, doc_only_llm: LlmClient, fake_redis: typing.Any
) -> None:
    """대조군 — 같은 헬퍼로 심은 캐시가 입주민 채널에서는 그대로 재생된다.

    이게 없으면 위 우회 테스트가 "키를 잘못 심어서 미스"였는지 구분할 수 없다.
    """
    await _seed_indexed_document(db_session)
    await _seed_cached_answer(fake_redis, doc_only_llm, roles=("RESIDENT",))

    async with _client(db_session, doc_only_llm, fake_redis, roles=("RESIDENT",)) as c:
        done = _done((await c.post("/assistant/ask", json={"question": QUESTION})).text)

    assert done["answer"] == CACHED_ANSWER
    assert done["token_input"] == 0  # 재생은 LLM 호출 0


# ── GET /admin/assistant/conversations/latest — 당일 한정 복원(ADR-0028 결정 2 개정) ──


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def test_admin_latest_restores_today_conversation(
    manager_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """오늘(KST) 대화는 그대로 복원된다 — 같은 턴은 user가 assistant보다 앞."""
    conversation_id = await _seed_conversation(
        db_session,
        channel="admin",
        at=_now(),
        messages=(
            ("user", "미배정 민원 몇 건인가요?", None),
            ("assistant", "3건입니다.", "answered"),
        ),
    )

    body = (await manager_client.get(ADMIN_LATEST)).json()

    assert body["conversation_id"] == str(conversation_id)
    assert [(m["role"], m["content"]) for m in body["messages"]] == [
        ("user", "미배정 민원 몇 건인가요?"),
        ("assistant", "3건입니다."),
    ]


async def test_admin_latest_ignores_yesterday_conversation(
    manager_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """일자가 바뀌면 새 대화다 — 어제 대화는 복원하지 않는다(그래야 브리핑이 다시 뜬다)."""
    await _seed_conversation(
        db_session,
        channel="admin",
        at=_now() - datetime.timedelta(days=1),
        messages=(("user", "어제 물어본 것", None), ("assistant", "어제 답변", "answered")),
    )

    response = await manager_client.get(ADMIN_LATEST)

    assert response.status_code == 200  # 빈 응답은 오류가 아니다
    assert response.json() == {"conversation_id": None, "messages": []}


async def test_admin_latest_ignores_resident_channel(
    manager_client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    """채널 격리 — 소장이 입주민 화면에서 나눈 오늘 대화는 관리자 홈에 나오지 않는다."""
    await _seed_conversation(
        db_session, channel="resident", at=_now(), messages=(("user", "내 관리비", None),)
    )

    body = (await manager_client.get(ADMIN_LATEST)).json()

    assert body == {"conversation_id": None, "messages": []}


async def test_resident_cannot_read_admin_latest(
    db_session: AsyncSession, fake_llm: LlmClient, fake_redis: object
) -> None:
    """CRITICAL 인가(규칙 4) — 복원 경로도 소장 전용이다."""
    await _seed_indexed_document(db_session)
    async with _client(db_session, fake_llm, fake_redis, roles=("RESIDENT",)) as c:
        response = await c.get(ADMIN_LATEST)

    assert response.status_code == 403
