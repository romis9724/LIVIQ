"""H15-1 관리자 AI 설정 — 인가(CRITICAL)·마스킹(CRITICAL)·upsert·env 폴백·연결 테스트.

실 PG(testcontainers) + 의존성 오버라이드. api_key 원문이 응답으로 새지 않는지, 비 SYS_ADMIN이
전역 설정에 손대지 못하는지가 게이트다. env 폴백 검증은 `LLM_*`를 fixture로 주입해 확인한다
(ai_core 설정은 lru_cache라 fixture가 캐시를 비운다).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator

import httpx
import pytest
from app import ai_backend
from app.deps import RequestContext, get_context, get_tenant_session
from app.main import create_app
from app.routers import ai_config
from conftest import MANAGER_USER_ID, TENANT_ID
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings, get_settings
from ai_core.llm.client import LlmClient
from liviq_db.models import AiBackendConfig

SYS_ADMIN_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
ENV_BASE_URL = "http://env-llm.test/v1"
ENV_MODEL = "llama3.1:8b"
ENV_API_KEY = "sk-env-key-abcd"
DB_BASE_URL = "http://db-llm.test/v1"
DB_MODEL = "qwen3:8b"
DB_API_KEY = "sk-db-key-1234"


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
    db_session: AsyncSession, *, ctx: RequestContext | str = _SYS_ADMIN_CTX
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    if isinstance(ctx, RequestContext):
        app.dependency_overrides[get_context] = lambda: ctx
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _row(**overrides: str | None) -> AiBackendConfig:
    values: dict[str, str | None] = {
        "base_url": DB_BASE_URL,
        "model": DB_MODEL,
        "api_key": DB_API_KEY,
        "reasoning_effort": None,
    }
    values.update(overrides)
    return AiBackendConfig(id=ai_backend.CONFIG_ROW_ID, **values)


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


async def test_get_falls_back_to_env_when_unconfigured(db_session: AsyncSession) -> None:
    """행이 없으면 env 값을 source="env"로 — api_key는 끝 4자만."""
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
    }
    assert ENV_API_KEY not in response.text  # 원문 미노출(CRITICAL)


async def test_put_then_get_roundtrip_masks_api_key(db_session: AsyncSession) -> None:
    """upsert 왕복 — 저장 값이 그대로 조회되고 api_key는 마스킹만(CRITICAL)."""
    body = {
        "base_url": DB_BASE_URL,
        "model": DB_MODEL,
        "api_key": DB_API_KEY,
        "reasoning_effort": "none",
    }
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
