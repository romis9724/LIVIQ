"""ai-core 소유 env 검증 — 생성 LLM과 임베딩 env 분리(docs/09 §2, ADR-0005).

- `LLM_*`: 생성 모델. env 교체만으로 프로바이더 전환(Ollama·vLLM·OpenAI 등).
- `EMBEDDING_*`: bge-m3(1024) 고정 운용 — 모델 변경 = 전량 재색인 이벤트(docs/03 §8).
누락 시 ValidationError로 즉시 실패(fail-closed). 시크릿·URL 하드코딩 금지.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AiCoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ── 생성 LLM (OpenAI-호환 단일 엔드포인트) ─────────────────────────
    llm_base_url: str = Field(..., validation_alias="LLM_BASE_URL")
    llm_model: str = Field(..., validation_alias="LLM_MODEL")
    llm_api_key: str | None = Field(None, validation_alias="LLM_API_KEY")
    # 규칙 7(토큰=비용): 출력 상한은 설정으로 강제, 호출별 값도 이 상한과 min()
    llm_max_output_tokens: int = Field(1024, validation_alias="LLM_MAX_OUTPUT_TOKENS")
    llm_timeout_s: float = Field(60.0, validation_alias="LLM_TIMEOUT_S")

    # ── 임베딩 (생성 모델과 별개 고정) ──────────────────────────────────
    embedding_base_url: str = Field(..., validation_alias="EMBEDDING_BASE_URL")
    embedding_model: str = Field(..., validation_alias="EMBEDDING_MODEL")
    embedding_api_key: str | None = Field(None, validation_alias="EMBEDDING_API_KEY")
    embedding_dimensions: int = Field(1024, validation_alias="EMBEDDING_DIMENSIONS")


@lru_cache
def get_settings() -> AiCoreSettings:
    return AiCoreSettings()  # type: ignore[call-arg]
