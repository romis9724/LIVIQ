"""packages/db env 검증 — DATABASE_URL 소유(docs/09 §2).

누락 시 ValidationError로 기동 실패(fail-closed). 시크릿 하드코딩 금지.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DbSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # asyncpg 스킴 필요: postgresql+asyncpg://user:pass@host:port/db
    database_url: str = Field(..., validation_alias="DATABASE_URL")


@lru_cache
def get_settings() -> DbSettings:
    return DbSettings()  # type: ignore[call-arg]
