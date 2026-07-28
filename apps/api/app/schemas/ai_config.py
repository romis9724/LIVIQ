"""AI 백엔드 설정 계약 — /system/ai-config (SYS_ADMIN, H15-1·H15-3, docs/03 §4.7).

api_key류(생성·임베딩)는 **입력 전용**이다 — 응답에는 끝 4자 마스킹(`*_api_key_masked`)만
담고 원문은 어떤 필드로도 나가지 않는다. 그래서 PUT은 키 생략 시 기존 값을 유지한다(마스킹된
값을 되돌려 받아 원문을 지우는 사고 방지).

튜닝 노브(H15-3)는 `null`/생략 = 기본값 복귀(env/코드 폴백)다. 범위는 여기서 강제한다 —
경계 검증은 서버 몫(규칙: Pydantic v2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field

__all__ = [
    "AiConfigIn",
    "AiConfigOut",
    "AiConfigTestIn",
    "AiConfigTestOut",
    "AiEmbeddingTestIn",
    "AiEmbeddingTestOut",
    "ReindexOut",
    "ReindexStatusOut",
]

MODEL_MAX_LEN = 200
API_KEY_MAX_LEN = 500
EFFORT_MAX_LEN = 20

# 노브 허용 범위 — 밖이면 422(UI 슬라이더 상한과 같은 값).
TOP_K_MIN, TOP_K_MAX = 1, 50
CHUNK_TOKENS_MIN, CHUNK_TOKENS_MAX = 100, 2000
MAX_OUTPUT_MIN, MAX_OUTPUT_MAX = 64, 8192
TIMEOUT_MIN, TIMEOUT_MAX = 5.0, 300.0
CACHE_TTL_MIN, CACHE_TTL_MAX = 0, 86400


class AiConfigIn(BaseModel):
    """저장 요청.

    - api_key·embedding_api_key: 생략=기존 유지 · 빈 문자열=삭제(env 폴백으로 복귀).
    - embedding_base_url·embedding_model: 생략=기존 유지 · null=삭제(env 폴백).
    - 노브 6종: null·생략=기본값 복귀(NULL 저장).
    """

    base_url: AnyHttpUrl  # http/https만 — OpenAI-호환 엔드포인트(`.../v1`)
    model: str = Field(min_length=1, max_length=MODEL_MAX_LEN)
    api_key: str | None = Field(default=None, max_length=API_KEY_MAX_LEN)
    # "none"이면 Ollama OpenAI 호환이 추론을 끈다(비추론 모델엔 무해). 빈 값=미전송.
    reasoning_effort: str | None = Field(default=None, max_length=EFFORT_MAX_LEN)

    # ── 임베딩(위험 노브 — 변경 시 차원 실측 검증 + 재색인 필요) ──────────
    embedding_base_url: AnyHttpUrl | None = None
    embedding_model: str | None = Field(default=None, max_length=MODEL_MAX_LEN)
    embedding_api_key: str | None = Field(default=None, max_length=API_KEY_MAX_LEN)

    # ── 튜닝 노브 ────────────────────────────────────────────────────────
    chunk_max_tokens: int | None = Field(default=None, ge=CHUNK_TOKENS_MIN, le=CHUNK_TOKENS_MAX)
    retrieval_top_k: int | None = Field(default=None, ge=TOP_K_MIN, le=TOP_K_MAX)
    llm_max_output_tokens: int | None = Field(default=None, ge=MAX_OUTPUT_MIN, le=MAX_OUTPUT_MAX)
    llm_timeout_s: float | None = Field(default=None, ge=TIMEOUT_MIN, le=TIMEOUT_MAX)
    tool_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    answer_cache_ttl_s: int | None = Field(default=None, ge=CACHE_TTL_MIN, le=CACHE_TTL_MAX)


class AiConfigOut(BaseModel):
    """현재 **유효** 설정(폴백 적용). configured=false면 값은 env `LLM_*` 폴백을 보여준다."""

    configured: bool
    source: Literal["db", "env"]
    base_url: str
    model: str
    reasoning_effort: str | None = None
    api_key_masked: str | None = None  # 끝 4자만 — 원문 미반환

    embedding_base_url: str
    embedding_model: str
    embedding_api_key_masked: str | None = None
    embedding_source: Literal["db", "env"]

    # 노브는 항상 유효값(DB NULL이면 코드/env 기본값이 담긴다).
    chunk_max_tokens: int
    retrieval_top_k: int
    llm_max_output_tokens: int
    llm_timeout_s: float
    tool_confidence: float
    answer_cache_ttl_s: int


class AiConfigTestIn(BaseModel):
    """저장 전 연결 테스트 — 전 필드 optional, 미지정은 저장값→env 순으로 병합."""

    base_url: AnyHttpUrl | None = None
    model: str | None = Field(default=None, max_length=MODEL_MAX_LEN)
    api_key: str | None = Field(default=None, max_length=API_KEY_MAX_LEN)
    reasoning_effort: str | None = Field(default=None, max_length=EFFORT_MAX_LEN)


class AiConfigTestOut(BaseModel):
    """스모크 결과. error는 요약 메시지만(스택·시크릿 없음)."""

    ok: bool
    latency_ms: int
    model: str
    error: str | None = None


class AiEmbeddingTestIn(BaseModel):
    """임베딩 연결 테스트 — 미지정은 저장값→env 병합."""

    embedding_base_url: AnyHttpUrl | None = None
    embedding_model: str | None = Field(default=None, max_length=MODEL_MAX_LEN)
    embedding_api_key: str | None = Field(default=None, max_length=API_KEY_MAX_LEN)


class AiEmbeddingTestOut(BaseModel):
    """임베딩 스모크 결과. dimensions는 실측 차원(불일치도 측정값을 돌려준다)."""

    ok: bool
    latency_ms: int
    model: str
    dimensions: int | None = None
    error: str | None = None


class ReindexOut(BaseModel):
    """재색인 트리거 결과 — 큐에 넣은 건수(실행은 ai-worker)."""

    enqueued_documents: int
    enqueued_notices: int


class ReindexStatusOut(BaseModel):
    """전 단지 문서 색인 상태 집계(documents.index_status 어휘 그대로)."""

    pending: int
    indexing: int
    indexed: int
    failed: int
    total: int
