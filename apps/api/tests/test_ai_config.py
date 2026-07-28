"""H15-1 관리자 AI 설정 — 인가(CRITICAL)·마스킹(CRITICAL)·upsert·env 폴백·연결 테스트.

실 PG(testcontainers) + 의존성 오버라이드. api_key 원문이 응답으로 새지 않는지, 비 SYS_ADMIN이
전역 설정에 손대지 못하는지가 게이트다. env 폴백 검증은 `LLM_*`를 fixture로 주입해 확인한다
(ai_core 설정은 lru_cache라 fixture가 캐시를 비운다).
"""

from __future__ import annotations

import datetime
import uuid
from collections.abc import Callable, Iterator

import httpx
import pytest
from app import ai_backend
from app.deps import RequestContext, get_context, get_queue, get_tenant_session
from app.main import create_app
from app.routers import ai_config
from app.schemas import ai_config as ai_config_schemas
from conftest import EMBED_DIM, MANAGER_USER_ID, TENANT_ID, FakeQueue
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings, get_settings
from ai_core.llm.client import LlmClient
from ai_core.rag.chunking import CHUNK_MAX_TOKENS
from ai_core.rag.retrieval import DEFAULT_TOP_K
from liviq_db.models import AiBackendConfig, Code, CodeGroup, Document, Notice, Tenant

SYS_ADMIN_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
ENV_BASE_URL = "http://env-llm.test/v1"
ENV_MODEL = "llama3.1:8b"
ENV_API_KEY = "sk-env-key-abcd"
ENV_EMBED_URL = "http://embed.test/v1"
ENV_EMBED_MODEL = "bge-m3"
DB_BASE_URL = "http://db-llm.test/v1"
DB_MODEL = "qwen3:8b"
DB_API_KEY = "sk-db-key-1234"
DB_EMBED_URL = "http://db-embed.test/v1"
DB_EMBED_KEY = "sk-embed-key-5678"
# env 기본값(폴백) — AiCoreSettings·app.config의 기본값과 같은 값이어야 한다.
ENV_MAX_OUTPUT = 1024
ENV_TIMEOUT_S = 60.0
ENV_CACHE_TTL_S = 3600
DEFAULT_TOOL_CONFIDENCE = 0.8


@pytest.fixture(autouse=True)
def llm_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """env `LLM_*`·`EMBEDDING_*` 주입 — 폴백 경로가 실제 env를 읽는지 확인하기 위해."""
    for key, value in {
        "LLM_BASE_URL": ENV_BASE_URL,
        "LLM_MODEL": ENV_MODEL,
        "LLM_API_KEY": ENV_API_KEY,
        "EMBEDDING_BASE_URL": "http://embed.test/v1",
        "EMBEDDING_MODEL": "bge-m3",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _ctx(roles: tuple[str, ...], *, user_id: uuid.UUID = SYS_ADMIN_ID) -> RequestContext:
    return RequestContext(TENANT_ID, user_id, roles=roles)


_SYS_ADMIN_CTX = _ctx(("SYS_ADMIN",))
_ANONYMOUS = "anonymous"  # ctx 대신 넘기면 미인증(세션·dev 헤더 없음) 경로


def _client(
    db_session: AsyncSession,
    *,
    ctx: RequestContext | str = _SYS_ADMIN_CTX,
    queue: object | None = None,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    if isinstance(ctx, RequestContext):
        app.dependency_overrides[get_context] = lambda: ctx
    if queue is not None:
        app.dependency_overrides[get_queue] = lambda: queue
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _row(**overrides: object) -> AiBackendConfig:
    values: dict[str, object] = {
        "base_url": DB_BASE_URL,
        "model": DB_MODEL,
        "api_key": DB_API_KEY,
        "reasoning_effort": None,
    }
    values.update(overrides)
    return AiBackendConfig(id=ai_backend.CONFIG_ROW_ID, **values)


def _put_body(**overrides: object) -> dict[str, object]:
    """PUT 최소 본문(필수 2필드) + 덮어쓸 값."""
    body: dict[str, object] = {"base_url": DB_BASE_URL, "model": DB_MODEL}
    body.update(overrides)
    return body


# ── 인가 (CRITICAL) ─────────────────────────────────────────────────────


@pytest.mark.parametrize("roles", [("MANAGER",), ("STAFF",), ("RESIDENT",)])
async def test_non_sys_admin_denied(db_session: AsyncSession, roles: tuple[str, ...]) -> None:
    """전역 AI 설정은 SYS_ADMIN 전용 — 소장·직원·입주민 전부 403(규칙 4)."""
    body = {"base_url": DB_BASE_URL, "model": DB_MODEL}
    async with _client(db_session, ctx=_ctx(roles, user_id=MANAGER_USER_ID)) as c:
        assert (await c.get("/system/ai-config")).status_code == 403
        assert (await c.put("/system/ai-config", json=body)).status_code == 403
        assert (await c.post("/system/ai-config/test", json={})).status_code == 403


async def test_unauthenticated_denied(db_session: AsyncSession) -> None:
    """세션·dev 헤더 없으면 401 — 익명 접근 불가(fail-closed)."""
    async with _client(db_session, ctx=_ANONYMOUS) as c:
        assert (await c.get("/system/ai-config")).status_code == 401
        assert (
            await c.put("/system/ai-config", json={"base_url": DB_BASE_URL, "model": DB_MODEL})
        ).status_code == 401
        assert (await c.post("/system/ai-config/test", json={})).status_code == 401


# ── 조회·저장 ───────────────────────────────────────────────────────────


def _env_defaults() -> dict[str, object]:
    """폴백이 적용된 유효값 — 임베딩·노브는 env/코드 기본값(H15-3)."""
    return {
        "embedding_base_url": ENV_EMBED_URL,
        "embedding_model": ENV_EMBED_MODEL,
        "embedding_api_key_masked": None,
        "embedding_source": "env",
        "chunk_max_tokens": CHUNK_MAX_TOKENS,
        "retrieval_top_k": DEFAULT_TOP_K,
        "llm_max_output_tokens": ENV_MAX_OUTPUT,
        "llm_timeout_s": ENV_TIMEOUT_S,
        "tool_confidence": DEFAULT_TOOL_CONFIDENCE,
        "answer_cache_ttl_s": ENV_CACHE_TTL_S,
    }


async def test_get_falls_back_to_env_when_unconfigured(db_session: AsyncSession) -> None:
    """행이 없으면 env 값을 source="env"로 — api_key는 끝 4자만, 노브는 코드 기본값."""
    async with _client(db_session) as c:
        response = await c.get("/system/ai-config")
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "configured": False,
        "source": "env",
        "base_url": ENV_BASE_URL,
        "model": ENV_MODEL,
        "reasoning_effort": None,
        "api_key_masked": "…abcd",
        **_env_defaults(),
    }
    assert ENV_API_KEY not in response.text  # 원문 미노출(CRITICAL)


async def test_put_then_get_roundtrip_masks_api_key(db_session: AsyncSession) -> None:
    """upsert 왕복 — 저장 값이 그대로 조회되고 api_key는 마스킹만(CRITICAL)."""
    body = _put_body(api_key=DB_API_KEY, reasoning_effort="none")
    async with _client(db_session) as c:
        put = await c.put("/system/ai-config", json=body)
        get = await c.get("/system/ai-config")
    assert put.status_code == 200
    expected = {
        "configured": True,
        "source": "db",
        "base_url": DB_BASE_URL,
        "model": DB_MODEL,
        "reasoning_effort": "none",
        "api_key_masked": "…1234",
        **_env_defaults(),
    }
    assert put.json() == expected
    assert get.json() == expected
    assert DB_API_KEY not in put.text and DB_API_KEY not in get.text


async def test_put_rejects_non_http_url_and_blank_model(db_session: AsyncSession) -> None:
    """경계 검증 — base_url은 http/https, model은 비어 있을 수 없다(422)."""
    async with _client(db_session) as c:
        assert (
            await c.put("/system/ai-config", json={"base_url": "ftp://x/y", "model": DB_MODEL})
        ).status_code == 422
        assert (
            await c.put("/system/ai-config", json={"base_url": DB_BASE_URL, "model": ""})
        ).status_code == 422


async def test_put_omitted_api_key_keeps_stored_value(db_session: AsyncSession) -> None:
    """api_key 생략 = 기존 유지 — 마스킹된 값을 되돌려 받아 키가 지워지지 않는다."""
    async with _client(db_session) as c:
        await c.put(
            "/system/ai-config",
            json={"base_url": DB_BASE_URL, "model": DB_MODEL, "api_key": DB_API_KEY},
        )
        second = await c.put("/system/ai-config", json={"base_url": DB_BASE_URL, "model": "other"})
    assert second.json()["api_key_masked"] == "…1234"
    row = await ai_backend.load_config(db_session)
    assert row is not None and row.api_key == DB_API_KEY and row.model == "other"


async def test_put_empty_api_key_clears_stored_value(db_session: AsyncSession) -> None:
    """빈 문자열 = 삭제 — 저장 키는 NULL이 되고 유효 키는 env 폴백으로 돌아간다."""
    async with _client(db_session) as c:
        await c.put(
            "/system/ai-config",
            json={"base_url": DB_BASE_URL, "model": DB_MODEL, "api_key": DB_API_KEY},
        )
        cleared = await c.put(
            "/system/ai-config",
            json={"base_url": DB_BASE_URL, "model": DB_MODEL, "api_key": ""},
        )
    row = await ai_backend.load_config(db_session)
    assert row is not None and row.api_key is None
    assert cleared.json()["api_key_masked"] == "…abcd"  # env 폴백 키의 마스킹


# ── 런타임 반영·캐시 키 ─────────────────────────────────────────────────


async def test_resolve_llm_settings_prefers_db_row_over_env(db_session: AsyncSession) -> None:
    """DB 행이 있으면 그 값, 없으면 env — 요청 단위 반영의 실제 해석 경로."""
    env_settings = await ai_backend.resolve_llm_settings(db_session)
    assert env_settings.llm_base_url == ENV_BASE_URL
    assert env_settings.llm_model == ENV_MODEL

    db_session.add(_row(reasoning_effort="none"))
    await db_session.flush()

    db_settings = await ai_backend.resolve_llm_settings(db_session)
    assert db_settings.llm_base_url == DB_BASE_URL
    assert db_settings.llm_model == DB_MODEL
    assert db_settings.llm_api_key == DB_API_KEY
    assert db_settings.llm_reasoning_effort == "none"
    # 테이블에 없는 필드는 env 계약 그대로.
    assert db_settings.embedding_model == env_settings.embedding_model


def test_merge_settings_falls_back_to_env_for_null_columns() -> None:
    """NULL api_key·reasoning_effort는 env 폴백 — UI에서 비워도 env 키가 살아 있다."""
    env = AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL=ENV_BASE_URL,
        LLM_MODEL=ENV_MODEL,
        LLM_API_KEY=ENV_API_KEY,
        LLM_REASONING_EFFORT="low",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )
    merged = ai_backend.merge_settings(_row(api_key=None), env=env)
    assert merged.llm_api_key == ENV_API_KEY
    assert merged.llm_reasoning_effort == "low"
    assert ai_backend.merge_settings(None, env=env) is env


def test_backend_id_separates_same_model_on_different_hosts() -> None:
    """캐시 키용 식별자는 `model@host` — 같은 모델명이라도 엔드포인트가 다르면 다르다."""

    def settings_for(base_url: str) -> AiCoreSettings:
        return AiCoreSettings(  # type: ignore[call-arg]
            LLM_BASE_URL=base_url,
            LLM_MODEL="llama3.1:8b",
            EMBEDDING_BASE_URL="http://embed.test/v1",
            EMBEDDING_MODEL="bge-m3",
        )

    ollama = ai_backend.backend_id(settings_for("http://ollama.test:11434/v1"))
    vllm = ai_backend.backend_id(settings_for("http://vllm.test:8000/v1"))
    assert ollama == "llama3.1:8b@ollama.test:11434"
    assert ollama != vllm


def test_mask_api_key_hides_short_keys() -> None:
    """짧은 키는 끝 4자가 곧 전체 — 아무것도 노출하지 않는다."""
    assert ai_backend.mask_api_key(None) is None
    assert ai_backend.mask_api_key("") is None
    assert ai_backend.mask_api_key("abcd") == "…"
    assert ai_backend.mask_api_key("sk-secret-9876") == "…9876"


# ── 연결 테스트 ─────────────────────────────────────────────────────────


def _stub_llm_client(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[AiCoreSettings]:
    """ai_config가 만드는 LlmClient에 MockTransport를 끼운다(네트워크 금지). 설정도 캡처."""
    seen: list[AiCoreSettings] = []

    def factory(settings: AiCoreSettings, **_kwargs: object) -> LlmClient:
        seen.append(settings)
        return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)

    monkeypatch.setattr(ai_config, "LlmClient", factory)
    return seen


async def test_connection_test_success_merges_stored_and_provided(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """제공 base_url + 저장 model·api_key 병합으로 스모크 — ok·지연·모델 반환."""
    db_session.add(_row())
    await db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "candidate.test"
        assert request.headers["Authorization"] == f"Bearer {DB_API_KEY}"
        return httpx.Response(200, json={"choices": [{"message": {"content": "pong"}}]})

    seen = _stub_llm_client(monkeypatch, handler)
    async with _client(db_session) as c:
        response = await c.post(
            "/system/ai-config/test", json={"base_url": "http://candidate.test/v1"}
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["model"] == DB_MODEL
    assert data["latency_ms"] >= 0
    assert data["error"] is None
    assert seen[0].llm_timeout_s == ai_config.TEST_TIMEOUT_S  # UI 대기 상한으로 단축
    assert DB_API_KEY not in response.text


async def test_connection_test_failure_returns_summary_without_api_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실패는 500이 아니라 ok=false + 요약 — 응답에 api_key 원문 없음(CRITICAL)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid api key: {DB_API_KEY}")

    _stub_llm_client(monkeypatch, handler)
    async with _client(db_session) as c:
        response = await c.post(
            "/system/ai-config/test",
            json={"base_url": DB_BASE_URL, "model": DB_MODEL, "api_key": DB_API_KEY},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["error"] and "LlmError" in data["error"]
    assert len(data["error"]) <= ai_config.ERROR_MAX_CHARS
    assert DB_API_KEY not in response.text


# ── H15-3 인가 (CRITICAL) ───────────────────────────────────────────────


@pytest.mark.parametrize("roles", [("MANAGER",), ("STAFF",), ("RESIDENT",)])
async def test_non_sys_admin_denied_on_h15_3_endpoints(
    db_session: AsyncSession, roles: tuple[str, ...]
) -> None:
    """임베딩 테스트·재색인·진행 조회도 SYS_ADMIN 전용 — 전 단지 영향 조작 차단(규칙 4)."""
    async with _client(
        db_session, ctx=_ctx(roles, user_id=MANAGER_USER_ID), queue=FakeQueue()
    ) as c:
        assert (await c.post("/system/ai-config/test-embedding", json={})).status_code == 403
        assert (await c.post("/system/ai-config/reindex")).status_code == 403
        assert (await c.get("/system/ai-config/reindex-status")).status_code == 403


async def test_unauthenticated_denied_on_h15_3_endpoints(db_session: AsyncSession) -> None:
    """익명은 401 — 재색인은 전 단지 큐를 채우는 조작이다(fail-closed)."""
    async with _client(db_session, ctx=_ANONYMOUS, queue=FakeQueue()) as c:
        assert (await c.post("/system/ai-config/test-embedding", json={})).status_code == 401
        assert (await c.post("/system/ai-config/reindex")).status_code == 401
        assert (await c.get("/system/ai-config/reindex-status")).status_code == 401


# ── 튜닝 노브 ───────────────────────────────────────────────────────────


async def test_put_knobs_roundtrip_then_null_restores_defaults(db_session: AsyncSession) -> None:
    """노브는 저장 즉시 유효값으로, null이면 코드/env 기본값으로 복귀한다."""
    async with _client(db_session) as c:
        saved = await c.put(
            "/system/ai-config",
            json=_put_body(
                chunk_max_tokens=600,
                retrieval_top_k=12,
                llm_max_output_tokens=2048,
                llm_timeout_s=30.0,
                tool_confidence=0.55,
                answer_cache_ttl_s=0,
            ),
        )
        reset = await c.put(
            "/system/ai-config",
            json=_put_body(retrieval_top_k=None),  # 나머지도 미지정 = 기본값 복귀
        )

    data = saved.json()
    assert (data["chunk_max_tokens"], data["retrieval_top_k"]) == (600, 12)
    assert (data["llm_max_output_tokens"], data["llm_timeout_s"]) == (2048, 30.0)
    assert (data["tool_confidence"], data["answer_cache_ttl_s"]) == (0.55, 0)

    back = reset.json()
    assert back["chunk_max_tokens"] == CHUNK_MAX_TOKENS
    assert back["retrieval_top_k"] == DEFAULT_TOP_K
    assert back["llm_max_output_tokens"] == ENV_MAX_OUTPUT
    assert back["llm_timeout_s"] == ENV_TIMEOUT_S
    assert back["tool_confidence"] == DEFAULT_TOOL_CONFIDENCE
    assert back["answer_cache_ttl_s"] == ENV_CACHE_TTL_S
    row = await ai_backend.load_config(db_session)
    assert row is not None and row.retrieval_top_k is None  # NULL 저장 = 폴백


@pytest.mark.parametrize(
    "knob",
    [
        {"retrieval_top_k": 0},
        {"retrieval_top_k": 51},
        {"chunk_max_tokens": 99},
        {"chunk_max_tokens": 2001},
        {"llm_max_output_tokens": 63},
        {"llm_timeout_s": 4.0},
        {"llm_timeout_s": 301.0},
        {"tool_confidence": 1.5},
        {"answer_cache_ttl_s": -1},
        {"answer_cache_ttl_s": 86401},
    ],
)
async def test_put_rejects_out_of_range_knobs(
    db_session: AsyncSession, knob: dict[str, object]
) -> None:
    """범위 밖 노브는 422 — 잘못된 상한이 검색·비용·캐시를 조용히 망가뜨리지 않는다."""
    async with _client(db_session) as c:
        assert (await c.put("/system/ai-config", json=_put_body(**knob))).status_code == 422


# ── 임베딩 백엔드·차원 검증 (CRITICAL) ──────────────────────────────────


def _embed_handler(dimensions: int) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/embeddings")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * dimensions}]})

    return handler


async def test_put_rejects_embedding_backend_with_wrong_dimensions(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """차원이 1024가 아니면 저장 거부(422) — 색인 오염 방지(CRITICAL). 실측 차원을 알린다."""
    _stub_llm_client(monkeypatch, _embed_handler(1536))
    async with _client(db_session) as c:
        response = await c.put(
            "/system/ai-config",
            json=_put_body(embedding_base_url=DB_EMBED_URL, embedding_model="text-embedding-3"),
        )

    assert response.status_code == 422
    assert "1536" in response.json()["detail"]
    assert await ai_backend.load_config(db_session) is None  # 저장되지 않았다


async def test_put_accepts_embedding_backend_with_matching_dimensions(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1024차원이면 저장 — 유효값·source가 db로 바뀌고 키는 마스킹만(CRITICAL)."""
    seen = _stub_llm_client(monkeypatch, _embed_handler(EMBED_DIM))
    async with _client(db_session) as c:
        response = await c.put(
            "/system/ai-config",
            json=_put_body(
                embedding_base_url=DB_EMBED_URL,
                embedding_model="bge-m3:custom",
                embedding_api_key=DB_EMBED_KEY,
            ),
        )

    assert response.status_code == 200
    data = response.json()
    assert data["embedding_base_url"] == DB_EMBED_URL
    assert data["embedding_model"] == "bge-m3:custom"
    assert data["embedding_source"] == "db"
    assert data["embedding_api_key_masked"] == "…5678"
    assert DB_EMBED_KEY not in response.text  # 원문 미노출(CRITICAL)
    assert seen[0].embedding_base_url == DB_EMBED_URL  # 후보 설정으로 실측했다
    assert seen[0].embedding_dimensions == EMBED_DIM  # 기대 차원은 스키마가 정한다


async def test_put_skips_embedding_probe_when_backend_unchanged(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """임베딩 무변경 PUT은 임베딩 호출 0 — 불필요한 지연·비용을 만들지 않는다."""

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("임베딩이 바뀌지 않았는데 호출됨")

    _stub_llm_client(monkeypatch, handler)
    async with _client(db_session) as c:
        first = await c.put("/system/ai-config", json=_put_body(retrieval_top_k=10))
        # 저장값과 같은 임베딩 설정을 다시 보내도 호출 없음.
        second = await c.put(
            "/system/ai-config",
            json=_put_body(embedding_base_url=ENV_EMBED_URL, embedding_model=ENV_EMBED_MODEL),
        )
    assert first.status_code == 200 and second.status_code == 200


async def test_put_rejects_unreachable_embedding_backend(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """연결 불가도 저장 거부(422) — 요약만 돌려주고 키는 지운다(CRITICAL)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid api key: {DB_EMBED_KEY}")

    _stub_llm_client(monkeypatch, handler)
    async with _client(db_session) as c:
        response = await c.put(
            "/system/ai-config",
            json=_put_body(embedding_base_url=DB_EMBED_URL, embedding_api_key=DB_EMBED_KEY),
        )
    assert response.status_code == 422
    assert DB_EMBED_KEY not in response.text
    assert await ai_backend.load_config(db_session) is None


async def test_embedding_connection_test_reports_measured_dimensions(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """임베딩 스모크 — 성공은 실측 차원, 불일치도 실측 차원을 담아 ok=false."""
    seen = _stub_llm_client(monkeypatch, _embed_handler(EMBED_DIM))
    async with _client(db_session) as c:
        ok = await c.post(
            "/system/ai-config/test-embedding",
            json={"embedding_base_url": DB_EMBED_URL, "embedding_api_key": DB_EMBED_KEY},
        )
    assert ok.status_code == 200
    data = ok.json()
    assert data["ok"] is True
    assert data["dimensions"] == EMBED_DIM
    assert data["model"] == ENV_EMBED_MODEL  # 미지정 = 저장값→env 병합
    assert data["error"] is None
    assert seen[0].embedding_base_url == DB_EMBED_URL
    assert DB_EMBED_KEY not in ok.text  # 원문 미노출(CRITICAL)

    _stub_llm_client(monkeypatch, _embed_handler(768))
    async with _client(db_session) as c:
        mismatch = await c.post(
            "/system/ai-config/test-embedding", json={"embedding_base_url": DB_EMBED_URL}
        )
    bad = mismatch.json()
    assert bad["ok"] is False
    assert bad["dimensions"] == 768
    assert "차원 불일치" in bad["error"]


async def test_embedding_connection_test_failure_hides_api_key(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """연결 실패는 200(ok=false) + 요약 — 응답에 키 원문 없음(CRITICAL)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"invalid api key: {DB_EMBED_KEY}")

    _stub_llm_client(monkeypatch, handler)
    async with _client(db_session) as c:
        response = await c.post(
            "/system/ai-config/test-embedding",
            json={"embedding_base_url": DB_EMBED_URL, "embedding_api_key": DB_EMBED_KEY},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["dimensions"] is None
    assert data["error"] and len(data["error"]) <= ai_config.ERROR_MAX_CHARS
    assert DB_EMBED_KEY not in response.text


# ── 재색인 트리거·진행 ──────────────────────────────────────────────────


async def _seed_documents_and_notices(session: AsyncSession) -> dict[str, uuid.UUID]:
    """단지 1개 + 문서 3건(indexed·failed·삭제됨) + 공지 2건(published·draft) 시드."""
    from sqlalchemy import text as sql_text

    await session.execute(
        sql_text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()
    group = CodeGroup(
        tenant_id=TENANT_ID, group_key="DOC_CATEGORY", name="문서 카테고리", is_system=True
    )
    session.add(group)
    await session.flush()
    code = Code(tenant_id=TENANT_ID, group_id=group.id, code="규약", label="규약")
    session.add(code)
    await session.flush()

    ids: dict[str, uuid.UUID] = {}
    for key, status, deleted in (
        ("indexed_doc", "indexed", False),
        ("failed_doc", "failed", False),
        ("deleted_doc", "indexed", True),
    ):
        doc = Document(
            tenant_id=TENANT_ID,
            title=key,
            category_code_id=code.id,
            visibility="ALL",
            version=1,
            index_status=status,
            deleted_at=datetime.datetime.now(datetime.UTC) if deleted else None,
        )
        session.add(doc)
        await session.flush()
        ids[key] = doc.id
    for key, status in (("published_notice", "published"), ("draft_notice", "draft")):
        notice = Notice(
            tenant_id=TENANT_ID,
            title=key,
            body="본문",
            status=status,
            pinned=False,
            audience="ALL",
            published_at=datetime.datetime.now(datetime.UTC) if status == "published" else None,
        )
        session.add(notice)
        await session.flush()
        ids[key] = notice.id
    return ids


async def test_reindex_enqueues_live_documents_and_published_notices(
    db_session: AsyncSession,
) -> None:
    """재색인은 삭제 안 된 문서 + 발행 공지만 큐에 넣고, 문서 상태를 pending으로 리셋한다."""
    ids = await _seed_documents_and_notices(db_session)
    queue = FakeQueue()
    async with _client(db_session, queue=queue) as c:
        response = await c.post("/system/ai-config/reindex")

    assert response.status_code == 200
    assert response.json() == {"enqueued_documents": 2, "enqueued_notices": 1}
    assert set(queue.jobs) == {
        ("ingest_document_task", (str(ids["indexed_doc"]), str(TENANT_ID))),
        ("ingest_document_task", (str(ids["failed_doc"]), str(TENANT_ID))),
        ("ingest_notice_task", (str(ids["published_notice"]), str(TENANT_ID))),
    }
    statuses = {
        doc_id: status
        for doc_id, status in await db_session.execute(
            select(Document.id, Document.index_status).where(Document.tenant_id == TENANT_ID)
        )
    }
    assert statuses[ids["indexed_doc"]] == "pending"
    assert statuses[ids["failed_doc"]] == "pending"
    assert statuses[ids["deleted_doc"]] == "indexed"  # 삭제 문서는 건드리지 않는다


async def test_reindex_status_aggregates_all_tenants(db_session: AsyncSession) -> None:
    """진행 표시는 전 단지 문서 상태 집계 — 삭제 문서는 제외."""
    await _seed_documents_and_notices(db_session)
    async with _client(db_session) as c:
        response = await c.get("/system/ai-config/reindex-status")

    assert response.status_code == 200
    assert response.json() == {
        "pending": 0,
        "indexing": 0,
        "indexed": 1,
        "failed": 1,
        "total": 2,
    }


async def test_reindex_status_is_empty_without_tenants(db_session: AsyncSession) -> None:
    """단지가 없으면 0 집계 — 빈 상태에서도 화면이 깨지지 않는다."""
    async with _client(db_session) as c:
        response = await c.get("/system/ai-config/reindex-status")
    assert response.json() == {
        "pending": 0,
        "indexing": 0,
        "indexed": 0,
        "failed": 0,
        "total": 0,
    }


def test_knob_ranges_match_schema_contract() -> None:
    """범위 상수는 UI·문서와 공유되는 계약 — 값이 바뀌면 이 테스트가 알려준다."""
    assert (ai_config_schemas.TOP_K_MIN, ai_config_schemas.TOP_K_MAX) == (1, 50)
    assert (ai_config_schemas.CHUNK_TOKENS_MIN, ai_config_schemas.CHUNK_TOKENS_MAX) == (100, 2000)
    assert (ai_config_schemas.MAX_OUTPUT_MIN, ai_config_schemas.MAX_OUTPUT_MAX) == (64, 8192)
    assert (ai_config_schemas.TIMEOUT_MIN, ai_config_schemas.TIMEOUT_MAX) == (5.0, 300.0)
    assert (ai_config_schemas.CACHE_TTL_MIN, ai_config_schemas.CACHE_TTL_MAX) == (0, 86400)
