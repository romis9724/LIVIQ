"""AI 백엔드 런타임 설정 로드 — DB(`ai_backend_config`) 우선·env 폴백 (H15-1·H15-3, docs/03 §4.7).

요청마다 전역 단일 행을 읽어 `AiCoreSettings`·`AiTuning`을 구성한다 — 관리자가 UI로 백엔드나
노브를 바꾸면 다음 요청부터 반영된다(재시작 불필요). 단일 행 SELECT 1회는 LLM 호출 비용 대비
무시 가능.

이 모듈은 **행 로드**만 담당한다 — 병합(폴백) 규칙은 `ai_core.backend_config`가 단일 지점이다
(ai-worker도 같은 규칙으로 잡 단위 해석). 행이 없으면 env 그대로 = 기존 계약(배포 무변화).
"""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.backend_config import CONFIG_ROW_ID, AiTuning, merge_settings, merge_tuning
from ai_core.config import AiCoreSettings
from ai_core.config import get_settings as get_env_ai_settings
from app.config import get_settings
from liviq_db.models import AiBackendConfig

__all__ = [
    "CONFIG_ROW_ID",
    "AiTuning",
    "active_settings",
    "active_tuning",
    "backend_id",
    "load_config",
    "mask_api_key",
    "merge_settings",
    "merge_tuning",
    "resolve_llm_settings",
    "resolve_tuning",
]

_MASK_TAIL = 4  # 마스킹에 남기는 끝 자릿수


async def load_config(session: AsyncSession) -> AiBackendConfig | None:
    """전역 단일 행 조회 — 없으면 None(env 폴백 신호)."""
    return await session.scalar(select(AiBackendConfig).where(AiBackendConfig.id == CONFIG_ROW_ID))


def active_settings(row: AiBackendConfig | None) -> AiCoreSettings:
    """행 + env → 활성 LLM·임베딩 설정(불변)."""
    return merge_settings(row, env=get_env_ai_settings())


def active_tuning(row: AiBackendConfig | None) -> AiTuning:
    """행 + 코드/env 기본값 → 활성 노브(불변). 캐시 TTL만 env(`CACHE_TTL_S`) 계약 유지."""
    return merge_tuning(row, base=AiTuning(answer_cache_ttl_s=get_settings().answer_cache_ttl_s))


async def resolve_llm_settings(session: AsyncSession) -> AiCoreSettings:
    """요청 단위 활성 LLM·임베딩 설정 — DB 행 우선, 없으면 env."""
    return active_settings(await load_config(session))


async def resolve_tuning(session: AsyncSession) -> AiTuning:
    """요청 단위 활성 튜닝 노브 — NULL 컬럼은 코드/env 기본값."""
    return active_tuning(await load_config(session))


def backend_id(settings: AiCoreSettings) -> str:
    """캐시 키용 활성 백엔드 식별자 `model@host`.

    모델명만으로는 부족하다 — ollama와 vLLM이 같은 모델명을 쓰면 답변이 서로 섞인다.
    """
    return f"{settings.llm_model}@{urlparse(settings.llm_base_url).netloc}"


def mask_api_key(api_key: str | None) -> str | None:
    """끝 4자만 노출 — 원문은 어떤 응답·로그에도 나가지 않는다(docs/03 §4.7).

    4자 이하 키는 전체가 곧 끝 4자이므로 아무것도 노출하지 않는다.
    """
    if not api_key:
        return None
    return f"…{api_key[-_MASK_TAIL:]}" if len(api_key) > _MASK_TAIL else "…"
