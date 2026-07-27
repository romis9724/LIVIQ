"""ai_config — LLM 백엔드 설정 조회·저장·연결 테스트 (SYS_ADMIN 전용, H15-1).

전역 설정이라 단지 데이터가 아니다 — SYS_ADMIN만 접근한다(규칙 4, 인가는 서버에서).
저장된 값은 `get_llm()`이 요청마다 읽어 반영한다(재시작 불필요, app.ai_backend).

- api_key 원문은 어떤 응답에도 나가지 않는다(끝 4자 마스킹) — CRITICAL.
- PUT은 api_key 생략 시 기존 값 유지, 빈 문자열이면 삭제(env 폴백 복귀).
- POST /test는 저장하지 않는다 — 후보 설정으로 1회 chat 스모크만(지연 ms 반환).
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient
from app.ai_backend import CONFIG_ROW_ID, load_config, mask_api_key, merge_settings
from app.deps import RequestContext, get_tenant_session, require_roles
from app.schemas.ai_config import AiConfigIn, AiConfigOut, AiConfigTestIn, AiConfigTestOut
from liviq_db.models import AiBackendConfig

router = APIRouter(prefix="/system/ai-config", tags=["ai-config"])

_SYS_ADMIN = require_roles("SYS_ADMIN")

PING_MESSAGE = "ping"
PING_MAX_TOKENS = 8
# 연결 테스트는 UI 버튼 — 운영 타임아웃(기본 60s)만큼 사용자를 기다리게 하지 않는다.
TEST_TIMEOUT_S = 10.0
ERROR_MAX_CHARS = 200


def _to_out(row: AiBackendConfig | None) -> AiConfigOut:
    """현재 유효 설정(DB 우선·env 폴백)을 응답으로 — api_key는 마스킹만."""
    settings = merge_settings(row)
    return AiConfigOut(
        configured=row is not None,
        source="db" if row is not None else "env",
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        reasoning_effort=settings.llm_reasoning_effort,
        api_key_masked=mask_api_key(settings.llm_api_key),
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
    """전역 단일 행 upsert(id=1). 다음 요청부터 새 백엔드가 쓰인다."""
    row = await load_config(session)
    api_key = row.api_key if row is not None else None  # 생략 = 기존 유지
    if body.api_key is not None:
        api_key = body.api_key or None  # 빈 문자열 = 삭제
    effort = body.reasoning_effort or None
    base_url = str(body.base_url)
    if row is None:
        row = AiBackendConfig(
            id=CONFIG_ROW_ID,
            base_url=base_url,
            model=body.model,
            api_key=api_key,
            reasoning_effort=effort,
        )
        session.add(row)
    else:
        row.base_url = base_url
        row.model = body.model
        row.api_key = api_key
        row.reasoning_effort = effort
    await session.flush()
    return _to_out(row)


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


def _candidate_settings(row: AiBackendConfig | None, body: AiConfigTestIn) -> AiCoreSettings:
    """제공 값 우선 · 미지정은 저장값 → env 폴백. 타임아웃만 테스트용으로 단축."""
    stored = merge_settings(row)
    return stored.model_copy(
        update={
            "llm_base_url": str(body.base_url) if body.base_url else stored.llm_base_url,
            "llm_model": body.model or stored.llm_model,
            "llm_api_key": body.api_key or stored.llm_api_key,
            "llm_reasoning_effort": body.reasoning_effort or stored.llm_reasoning_effort,
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
