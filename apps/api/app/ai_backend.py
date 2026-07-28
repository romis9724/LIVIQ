"""LLM 백엔드 런타임 설정 — DB(`ai_backend_config`) 우선·env `LLM_*` 폴백 (H15-1, docs/03 §4.7).

요청마다 전역 단일 행을 읽어 `AiCoreSettings`를 구성한다 — 관리자가 UI로 백엔드를 바꾸면
다음 요청부터 반영된다(재시작 불필요). 단일 행 SELECT 1회는 LLM 호출 비용 대비 무시 가능.

- 행이 없으면 env 그대로 = 기존 계약(기존 배포 무변화).
- NULL 컬럼(api_key·reasoning_effort)도 env 폴백 — UI가 키 원문을 되돌려줄 수 없으니(마스킹),
  키를 비운 채 저장해도 env에 있던 키가 살아 있어야 운영이 조용히 깨지지 않는다.
- 임베딩(`EMBEDDING_*`)은 이 경로에 없다 — 모델 교체가 전량 재색인 이벤트라 env 전용(§8).
"""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.config import get_settings as get_env_ai_settings
from liviq_db.models import AiBackendConfig

CONFIG_ROW_ID = 1  # 전역 단일 행 — DDL의 CHECK (id = 1)과 같은 값
_MASK_TAIL = 4  # 마스킹에 남기는 끝 자릿수


async def load_config(session: AsyncSession) -> AiBackendConfig | None:
    """전역 단일 행 조회 — 없으면 None(env 폴백 신호)."""
    return await session.scalar(select(AiBackendConfig).where(AiBackendConfig.id == CONFIG_ROW_ID))


def merge_settings(
    row: AiBackendConfig | None, *, env: AiCoreSettings | None = None
) -> AiCoreSettings:
    """DB 행을 env 설정 위에 덮은 새 설정 객체(불변 — model_copy)."""
    base = env or get_env_ai_settings()
    if row is None:
        return base
    return base.model_copy(
        update={
            "llm_base_url": row.base_url,
            "llm_model": row.model,
            "llm_api_key": row.api_key or base.llm_api_key,
            "llm_reasoning_effort": row.reasoning_effort or base.llm_reasoning_effort,
        }
    )


async def resolve_llm_settings(session: AsyncSession) -> AiCoreSettings:
    """요청 단위 활성 LLM 설정 — DB 행 우선, 없으면 env."""
    return merge_settings(await load_config(session))


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
