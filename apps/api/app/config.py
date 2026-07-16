"""apps/api env 검증 — api 소유 env(docs/09 §8.1).

누락 시 ValidationError로 기동 실패(fail-closed). 시크릿 하드코딩 금지.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ADR-0011 세션 스토어 + arq 큐. 기본값 금지 — 명시 주입 강제.
    redis_url: str = Field(..., validation_alias="REDIS_URL")
    api_env: str = Field("local", validation_alias="API_ENV")

    # S3 호환(MinIO) — 원본 문서 저장(docs/11 §1). 키 프리픽스 `{tenant_id}/`.
    s3_endpoint_url: str = Field(..., validation_alias="S3_ENDPOINT_URL")
    s3_access_key_id: str = Field(..., validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(..., validation_alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field("liviq", validation_alias="S3_BUCKET")


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()  # type: ignore[call-arg]
