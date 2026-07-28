"""활성 백엔드·튜닝 해석 — DB 행 우선·NULL은 env/코드 기본값 폴백 (H15-3, docs/03 §4.7).

api와 ai-worker가 이 규칙을 공유한다 — 폴백이 깨지면 관리자가 값을 비운 순간 운영이
조용히 다른 백엔드를 쓴다. 행 로드(SELECT)는 소비자 쪽 책임이라 여기선 순수 병합만 본다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai_core.backend_config import (
    DEFAULT_ANSWER_CACHE_TTL_S,
    DEFAULT_TOOL_CONFIDENCE,
    AiTuning,
    merge_settings,
    merge_tuning,
)
from ai_core.config import AiCoreSettings
from ai_core.rag.chunking import CHUNK_MAX_TOKENS
from ai_core.rag.retrieval import DEFAULT_TOP_K

ENV_EMBED_URL = "http://env-embed.test/v1"
DB_EMBED_URL = "http://db-embed.test/v1"


@dataclass
class FakeRow:
    """`ai_backend_config` 행 대역 — BackendConfigRow Protocol을 구조적으로 만족."""

    base_url: str = "http://db-llm.test/v1"
    model: str = "qwen3:8b"
    api_key: str | None = None
    reasoning_effort: str | None = None
    embedding_base_url: str | None = None
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    chunk_max_tokens: int | None = None
    retrieval_top_k: int | None = None
    llm_max_output_tokens: int | None = None
    llm_timeout_s: float | None = None
    tool_confidence: float | None = None
    answer_cache_ttl_s: int | None = None


def _env() -> AiCoreSettings:
    return AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://env-llm.test/v1",
        LLM_MODEL="llama3.1:8b",
        LLM_API_KEY="sk-env",
        LLM_MAX_OUTPUT_TOKENS=1024,
        LLM_TIMEOUT_S=60.0,
        EMBEDDING_BASE_URL=ENV_EMBED_URL,
        EMBEDDING_MODEL="bge-m3",
        EMBEDDING_API_KEY="sk-env-embed",
    )


# ── 설정 병합 ───────────────────────────────────────────────────────────


def test_merge_settings_returns_env_when_row_missing() -> None:
    """행 없음 = 기존 계약(전부 env) — 같은 객체를 그대로 돌려준다."""
    env = _env()
    assert merge_settings(None, env=env) is env


def test_merge_settings_overrides_embedding_and_limits_from_row() -> None:
    """임베딩·출력 상한·타임아웃도 DB 우선(H15-3) — 원본 env는 변하지 않는다(불변)."""
    env = _env()
    merged = merge_settings(
        FakeRow(
            embedding_base_url=DB_EMBED_URL,
            embedding_model="bge-m3:new",
            embedding_api_key="sk-db-embed",
            llm_max_output_tokens=2048,
            llm_timeout_s=30.0,
        ),
        env=env,
    )
    assert merged.embedding_base_url == DB_EMBED_URL
    assert merged.embedding_model == "bge-m3:new"
    assert merged.embedding_api_key == "sk-db-embed"
    assert merged.llm_max_output_tokens == 2048
    assert merged.llm_timeout_s == 30.0
    assert env.embedding_base_url == ENV_EMBED_URL  # 원본 불변


def test_merge_settings_falls_back_to_env_for_null_embedding_columns() -> None:
    """임베딩 컬럼이 NULL이면 env — UI에서 비워도 색인 백엔드가 사라지지 않는다."""
    merged = merge_settings(FakeRow(), env=_env())
    assert merged.embedding_base_url == ENV_EMBED_URL
    assert merged.embedding_model == "bge-m3"
    assert merged.embedding_api_key == "sk-env-embed"
    assert merged.llm_max_output_tokens == 1024
    assert merged.llm_timeout_s == 60.0


# ── 노브 병합 ───────────────────────────────────────────────────────────


def test_merge_tuning_uses_code_defaults_when_row_missing_or_null() -> None:
    """행 없음·NULL 노브는 코드 기본값 — 현재 상수와 같은 값이어야 한다."""
    for row in (None, FakeRow()):
        tuning = merge_tuning(row)
        assert tuning == AiTuning(
            chunk_max_tokens=CHUNK_MAX_TOKENS,
            retrieval_top_k=DEFAULT_TOP_K,
            tool_confidence=DEFAULT_TOOL_CONFIDENCE,
            answer_cache_ttl_s=DEFAULT_ANSWER_CACHE_TTL_S,
        )


def test_merge_tuning_overrides_only_non_null_knobs() -> None:
    """설정한 노브만 덮는다 — 나머지는 base(env 기본값) 유지."""
    base = AiTuning(answer_cache_ttl_s=900)
    tuning = merge_tuning(FakeRow(retrieval_top_k=20, tool_confidence=0.55), base=base)
    assert tuning.retrieval_top_k == 20
    assert tuning.tool_confidence == 0.55
    assert tuning.chunk_max_tokens == CHUNK_MAX_TOKENS
    assert tuning.answer_cache_ttl_s == 900  # env 기본값 유지
    assert base.retrieval_top_k == DEFAULT_TOP_K  # 원본 불변


def test_merge_tuning_keeps_zero_cache_ttl_as_explicit_disable() -> None:
    """TTL 0은 "캐시 끔"이라는 명시적 설정 — 미설정으로 오인하면 캐시가 안 꺼진다."""
    assert merge_tuning(FakeRow(answer_cache_ttl_s=0)).answer_cache_ttl_s == 0
