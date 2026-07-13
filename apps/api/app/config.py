"""apps/api env 검증 — api 소유 env(docs/09 §8.1).

누락 시 ValidationError로 기동 실패(fail-closed). 시크릿 하드코딩 금지.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ADR-0011 세션 스토어. H1에서 소비. 기본값 금지 — 명시 주입 강제.
    redis_url: str = Field(..., validation_alias="REDIS_URL")
    api_env: str = Field("local", validation_alias="API_ENV")


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()  # type: ignore[call-arg]
