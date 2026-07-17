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

    # 질의 레이트 리밋(docs/08 §8 가드레일) — AI 질의 분당 상한. 0=비활성.
    # Redis 고정 창(사용자별·단지별). 세션과 달리 fail-open(가용성 보조, docs/09 §8.5 H4-1).
    rate_limit_user_per_min: int = Field(10, validation_alias="RATE_LIMIT_USER_PER_MIN")
    rate_limit_tenant_per_min: int = Field(100, validation_alias="RATE_LIMIT_TENANT_PER_MIN")

    # AI 질의 정확 캐시 TTL 초(docs/08 §2.0·2.1, docs/09 §8.5 H4-2). 0=캐시 전체 비활성.
    # 히트 시 LLM 호출 0으로 SSE 재생 — 격리는 키(tenant·user/roles·visibilities·gen)로 보장.
    answer_cache_ttl_s: int = Field(3600, validation_alias="CACHE_TTL_S")

    # pii_vault 봉투 암호화 마스터 키(KEK) — 32byte base64. 필수(fail-closed, ADR-0010).
    # 유실 = pii_vault 복호 불능. 시크릿 매니저 + 오프라인 백업(docs/09 §7).
    pii_master_key: str = Field(..., validation_alias="PII_MASTER_KEY")

    # S3 호환(MinIO) — 원본 문서 저장(docs/11 §1). 키 프리픽스 `{tenant_id}/`.
    s3_endpoint_url: str = Field(..., validation_alias="S3_ENDPOINT_URL")
    s3_access_key_id: str = Field(..., validation_alias="S3_ACCESS_KEY_ID")
    s3_secret_access_key: str = Field(..., validation_alias="S3_SECRET_ACCESS_KEY")
    s3_bucket: str = Field("liviq", validation_alias="S3_BUCKET")

    # Google OAuth(PKCE) — optional. 미설정 시 /auth/google/* 503(부팅은 성공, ADR-0011).
    google_oauth_client_id: str | None = Field(None, validation_alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str | None = Field(
        None, validation_alias="GOOGLE_OAUTH_CLIENT_SECRET"
    )
    google_oauth_redirect_uri: str | None = Field(
        None, validation_alias="GOOGLE_OAUTH_REDIRECT_URI"
    )


@lru_cache
def get_settings() -> ApiSettings:
    return ApiSettings()  # type: ignore[call-arg]
