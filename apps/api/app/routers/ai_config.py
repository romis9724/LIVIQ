"""ai_config — AI 백엔드·튜닝 설정 조회·저장·연결 테스트 (SYS_ADMIN 전용, H15-1·H15-3).

전역 설정이라 단지 데이터가 아니다 — SYS_ADMIN만 접근한다(규칙 4, 인가는 서버에서).
저장된 값은 api가 요청마다(`app.ai_backend`), ai-worker가 잡마다 읽어 반영한다(재시작 불필요).

- api_key류 원문은 어떤 응답에도 나가지 않는다(끝 4자 마스킹) — CRITICAL.
- PUT은 키 생략 시 기존 값 유지, 빈 문자열이면 삭제(env 폴백 복귀).
- 임베딩 백엔드가 **변경**되면 저장 전 실제 임베딩 1회로 차원을 실측한다 — 스키마
  `Vector(1024)`와 다르면 422로 저장을 거부한다(색인 오염 방지, docs/03 §4.7).
- POST /test·/test-embedding은 저장하지 않는다(스모크만). 재색인은 routers/ai_reindex.py.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.llm.client import EmbeddingDimensionError, LlmClient
from app.ai_backend import (
    CONFIG_ROW_ID,
    active_settings,
    active_tuning,
    load_config,
    mask_api_key,
)
from app.deps import RequestContext, get_tenant_session, require_roles
from app.schemas.ai_config import (
    AiConfigIn,
    AiConfigOut,
    AiConfigTestIn,
    AiConfigTestOut,
    AiEmbeddingTestIn,
    AiEmbeddingTestOut,
)
from liviq_db.models import AiBackendConfig
from liviq_db.models.documents import EMBEDDING_DIM

router = APIRouter(prefix="/system/ai-config", tags=["ai-config"])

_SYS_ADMIN = require_roles("SYS_ADMIN")

PING_MESSAGE = "ping"
PING_MAX_TOKENS = 8
# 연결 테스트는 UI 버튼 — 운영 타임아웃(기본 60s)만큼 사용자를 기다리게 하지 않는다.
TEST_TIMEOUT_S = 10.0
ERROR_MAX_CHARS = 200
# 노브 컬럼 — PUT은 미지정/null을 NULL(기본값 복귀)로 저장한다.
_KNOBS = (
    "chunk_max_tokens",
    "retrieval_top_k",
    "llm_max_output_tokens",
    "llm_timeout_s",
    "tool_confidence",
    "answer_cache_ttl_s",
)


def _to_out(row: AiBackendConfig | None) -> AiConfigOut:
    """현재 유효 설정(DB 우선·env 폴백)을 응답으로 — api_key류는 마스킹만."""
    settings = active_settings(row)
    tuning = active_tuning(row)
    embedding_from_db = row is not None and bool(row.embedding_base_url or row.embedding_model)
    return AiConfigOut(
        configured=row is not None,
        source="db" if row is not None else "env",
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        reasoning_effort=settings.llm_reasoning_effort,
        api_key_masked=mask_api_key(settings.llm_api_key),
        embedding_base_url=settings.embedding_base_url,
        embedding_model=settings.embedding_model,
        embedding_api_key_masked=mask_api_key(settings.embedding_api_key),
        embedding_source="db" if embedding_from_db else "env",
        chunk_max_tokens=tuning.chunk_max_tokens,
        retrieval_top_k=tuning.retrieval_top_k,
        llm_max_output_tokens=settings.llm_max_output_tokens,
        llm_timeout_s=settings.llm_timeout_s,
        tool_confidence=tuning.tool_confidence,
        answer_cache_ttl_s=tuning.answer_cache_ttl_s,
    )


@router.get("", response_model=AiConfigOut)
async def get_ai_config(
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> AiConfigOut:
    """현재 유효 설정 — 행이 없으면 env 값을 source="env"로 보여준다."""
    return _to_out(await load_config(session))


@router.put("", response_model=AiConfigOut)
async def put_ai_config(
    body: AiConfigIn,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> AiConfigOut:
    """전역 단일 행 upsert(id=1). 다음 요청부터 새 설정이 쓰인다.

    임베딩 백엔드가 바뀌면 저장 전에 차원을 실측해 1024가 아니면 거부한다(422).
    """
    row = await load_config(session)
    await _guard_embedding_dimensions(row, body)
    if row is None:
        row = AiBackendConfig(id=CONFIG_ROW_ID, base_url=str(body.base_url), model=body.model)
        session.add(row)
    _apply(row, body)
    await session.flush()
    return _to_out(row)


def _apply(row: AiBackendConfig, body: AiConfigIn) -> None:
    """요청 값을 행에 반영 — 키·임베딩 필드는 생략 시 기존 유지, 노브는 미지정=NULL."""
    row.base_url = str(body.base_url)
    row.model = body.model
    row.reasoning_effort = body.reasoning_effort or None
    if body.api_key is not None:  # 생략 = 기존 유지, 빈 문자열 = 삭제
        row.api_key = body.api_key or None
    if body.embedding_api_key is not None:
        row.embedding_api_key = body.embedding_api_key or None
    # base_url·model은 "생략=유지 / null=삭제"를 구분해야 한다(폼이 섹션을 안 보낼 수 있다).
    if "embedding_base_url" in body.model_fields_set:
        row.embedding_base_url = str(body.embedding_base_url) if body.embedding_base_url else None
    if "embedding_model" in body.model_fields_set:
        row.embedding_model = body.embedding_model or None
    for knob in _KNOBS:
        setattr(row, knob, getattr(body, knob))


async def _guard_embedding_dimensions(row: AiBackendConfig | None, body: AiConfigIn) -> None:
    """임베딩 백엔드 변경 시 실측 차원 검증(CRITICAL — 색인 오염·조용한 실패 방지).

    변경이 없으면 호출하지 않는다(불필요한 LLM 호출·지연 회피).
    """
    current = active_settings(row)
    candidate = _candidate_embedding_settings(row, body)
    unchanged = (
        candidate.embedding_base_url == current.embedding_base_url
        and candidate.embedding_model == current.embedding_model
    )
    if unchanged:
        return
    try:
        await _probe_embedding(candidate)
    except EmbeddingDimensionError as exc:
        raise HTTPException(
            status_code=422,
            detail=(
                f"임베딩 차원 불일치 — 스키마는 {EMBEDDING_DIM}차원 고정인데 "
                f"실측 {exc.actual}차원입니다. 다른 모델을 지정하세요."
            ),
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 연결 불가도 저장 거부(요약만, 키 노출 금지)
        raise HTTPException(
            status_code=422,
            detail=f"임베딩 연결 실패로 저장하지 않았습니다: "
            f"{_summarize(exc, candidate.embedding_api_key)}",
        ) from exc


async def _probe_embedding(settings: AiCoreSettings) -> int:
    """짧은 임베딩 1회 — 실측 차원 반환. 차원 불일치는 EmbeddingDimensionError."""
    client = LlmClient(settings, retry_backoff_s=0.0)
    vectors = await client.embed([PING_MESSAGE])
    return len(vectors[0]) if vectors else 0


@router.post("/test", response_model=AiConfigTestOut)
async def run_connection_test(
    body: AiConfigTestIn,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> AiConfigTestOut:
    """저장 전 스모크 — 후보 백엔드에 짧은 chat 1회. 실패도 200(ok=false)로 요약 반환."""
    settings = _candidate_settings(await load_config(session), body)
    client = LlmClient(settings, retry_backoff_s=0.0)
    started = time.perf_counter()
    try:
        await client.chat([{"role": "user", "content": PING_MESSAGE}], max_tokens=PING_MAX_TOKENS)
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 500이 아니라 ok=false 요약으로
        return AiConfigTestOut(
            ok=False,
            latency_ms=_elapsed_ms(started),
            model=settings.llm_model,
            error=_summarize(exc, settings.llm_api_key),
        )
    return AiConfigTestOut(ok=True, latency_ms=_elapsed_ms(started), model=settings.llm_model)


@router.post("/test-embedding", response_model=AiEmbeddingTestOut)
async def run_embedding_test(
    body: AiEmbeddingTestIn,
    _ctx: Annotated[RequestContext, Depends(_SYS_ADMIN)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> AiEmbeddingTestOut:
    """임베딩 스모크 — 실측 차원까지 돌려준다(1024가 아니면 저장은 거부된다)."""
    settings = _candidate_embedding_settings(await load_config(session), body)
    started = time.perf_counter()
    try:
        dimensions = await _probe_embedding(settings)
    except EmbeddingDimensionError as exc:
        return AiEmbeddingTestOut(
            ok=False,
            latency_ms=_elapsed_ms(started),
            model=settings.embedding_model,
            dimensions=exc.actual,  # 실측 차원 — 관리자가 원인을 바로 안다
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 — 연결 실패도 ok=false 요약으로
        return AiEmbeddingTestOut(
            ok=False,
            latency_ms=_elapsed_ms(started),
            model=settings.embedding_model,
            error=_summarize(exc, settings.embedding_api_key),
        )
    return AiEmbeddingTestOut(
        ok=True,
        latency_ms=_elapsed_ms(started),
        model=settings.embedding_model,
        dimensions=dimensions,
    )


def _candidate_settings(row: AiBackendConfig | None, body: AiConfigTestIn) -> AiCoreSettings:
    """제공 값 우선 · 미지정은 저장값 → env 폴백. 타임아웃만 테스트용으로 단축."""
    stored = active_settings(row)
    return stored.model_copy(
        update={
            "llm_base_url": str(body.base_url) if body.base_url else stored.llm_base_url,
            "llm_model": body.model or stored.llm_model,
            "llm_api_key": body.api_key or stored.llm_api_key,
            "llm_reasoning_effort": body.reasoning_effort or stored.llm_reasoning_effort,
            "llm_timeout_s": min(stored.llm_timeout_s, TEST_TIMEOUT_S),
        }
    )


def _candidate_embedding_settings(
    row: AiBackendConfig | None, body: AiConfigIn | AiEmbeddingTestIn
) -> AiCoreSettings:
    """임베딩 후보 설정 — 제공 값 우선 · 미지정은 저장값 → env 폴백(타임아웃은 단축)."""
    stored = active_settings(row)
    return stored.model_copy(
        update={
            "embedding_base_url": (
                str(body.embedding_base_url)
                if body.embedding_base_url
                else stored.embedding_base_url
            ),
            "embedding_model": body.embedding_model or stored.embedding_model,
            "embedding_api_key": body.embedding_api_key or stored.embedding_api_key,
            # 기대 차원은 env가 아니라 **스키마**가 정한다(Vector(1024)) — env 오설정으로
            # 색인이 오염되는 경로를 막는다.
            "embedding_dimensions": EMBEDDING_DIM,
            "llm_timeout_s": min(stored.llm_timeout_s, TEST_TIMEOUT_S),
        }
    )


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _summarize(exc: Exception, api_key: str | None) -> str:
    """오류 요약 — 클래스명+메시지 앞부분. 키가 메시지에 섞여도 지워서 내보낸다."""
    summary = f"{type(exc).__name__}: {exc}"
    if api_key:
        summary = summary.replace(api_key, "…")
    return summary[:ERROR_MAX_CHARS]
