"""활성 AI 백엔드·튜닝 노브 해석 — DB 행 우선·env/코드 기본값 폴백 (H15-1·H15-3, docs/03 §4.7).

api(요청 단위)와 ai-worker(잡 단위)가 **같은 해석 규칙**을 써야 한다 — 그래서 순수 해석은
여기(ai_core)에 둔다. 행 로드(SELECT)는 모델을 아는 쪽(api `app.ai_backend`·ai-worker)이 한다
(ai_core는 liviq_db에 의존하지 않는다).

규칙은 하나다: **DB 값이 NULL이면 env/코드 기본값**. UI가 키 원문을 되돌려줄 수 없으니
(마스킹) 비운 채 저장해도 env 키가 살아 있어야 운영이 조용히 깨지지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from ai_core.config import AiCoreSettings
from ai_core.rag.chunking import CHUNK_MAX_TOKENS
from ai_core.rag.retrieval import DEFAULT_TOP_K

CONFIG_ROW_ID = 1  # 전역 단일 행 — DDL의 CHECK (id = 1)과 같은 값
# 확정 데이터·도구 결과만으로 답할 때의 신뢰도(검색 점수 아님 — orchestrator가 소비).
DEFAULT_TOOL_CONFIDENCE = 0.8
# 답변 캐시 TTL 기본값(api `CACHE_TTL_S` 기본값과 같은 값 — env가 있으면 그쪽이 base).
DEFAULT_ANSWER_CACHE_TTL_S = 3600


class BackendConfigRow(Protocol):
    """`ai_backend_config` 단일 행이 제공해야 하는 읽기 속성(liviq_db 모델이 구조적으로 만족).

    NULL 가능 컬럼은 None = "설정 안 함" = env/코드 기본값 폴백.
    """

    base_url: str
    model: str
    api_key: str | None
    reasoning_effort: str | None
    embedding_base_url: str | None
    embedding_model: str | None
    embedding_api_key: str | None
    chunk_max_tokens: int | None
    retrieval_top_k: int | None
    llm_max_output_tokens: int | None
    llm_timeout_s: float | None
    tool_confidence: float | None
    answer_cache_ttl_s: int | None


@dataclass(frozen=True)
class AiTuning:
    """AiCoreSettings에 없는 RAG 튜닝 노브 — 코드 기본값이 곧 폴백(H15-3)."""

    chunk_max_tokens: int = CHUNK_MAX_TOKENS
    retrieval_top_k: int = DEFAULT_TOP_K
    tool_confidence: float = DEFAULT_TOOL_CONFIDENCE
    answer_cache_ttl_s: int = DEFAULT_ANSWER_CACHE_TTL_S


def merge_settings(row: BackendConfigRow | None, *, env: AiCoreSettings) -> AiCoreSettings:
    """DB 행을 env 설정 위에 덮은 새 설정 객체(불변 — model_copy). NULL 컬럼은 env 유지."""
    if row is None:
        return env
    return env.model_copy(
        update={
            "llm_base_url": row.base_url,
            "llm_model": row.model,
            "llm_api_key": row.api_key or env.llm_api_key,
            "llm_reasoning_effort": row.reasoning_effort or env.llm_reasoning_effort,
            "llm_max_output_tokens": row.llm_max_output_tokens or env.llm_max_output_tokens,
            "llm_timeout_s": row.llm_timeout_s or env.llm_timeout_s,
            "embedding_base_url": row.embedding_base_url or env.embedding_base_url,
            "embedding_model": row.embedding_model or env.embedding_model,
            "embedding_api_key": row.embedding_api_key or env.embedding_api_key,
        }
    )


def merge_tuning(row: BackendConfigRow | None, *, base: AiTuning | None = None) -> AiTuning:
    """DB 행의 NULL 아닌 노브만 덮은 새 AiTuning(불변). base=코드/env 기본값."""
    resolved = base or AiTuning()
    if row is None:
        return resolved
    overrides = {
        field: value
        for field in (
            "chunk_max_tokens",
            "retrieval_top_k",
            "tool_confidence",
            "answer_cache_ttl_s",
        )
        if (value := getattr(row, field)) is not None
    }
    return replace(resolved, **overrides)
