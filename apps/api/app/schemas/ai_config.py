"""AI 백엔드 설정 계약 — /system/ai-config (SYS_ADMIN, H15-1, docs/03 §4.7).

api_key는 **입력 전용**이다 — 응답에는 끝 4자 마스킹(`api_key_masked`)만 담고 원문은
어떤 필드로도 나가지 않는다. 그래서 PUT은 api_key 생략 시 기존 값을 유지한다(마스킹된
값을 되돌려 받아 원문을 지우는 사고 방지).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AnyHttpUrl, BaseModel, Field

__all__ = ["AiConfigIn", "AiConfigOut", "AiConfigTestIn", "AiConfigTestOut"]

MODEL_MAX_LEN = 200
API_KEY_MAX_LEN = 500
EFFORT_MAX_LEN = 20


class AiConfigIn(BaseModel):
    """저장 요청. api_key: 생략=기존 유지 · 빈 문자열=삭제(env 폴백으로 복귀)."""

    base_url: AnyHttpUrl  # http/https만 — OpenAI-호환 엔드포인트(`.../v1`)
    model: str = Field(min_length=1, max_length=MODEL_MAX_LEN)
    api_key: str | None = Field(default=None, max_length=API_KEY_MAX_LEN)
    # "none"이면 Ollama OpenAI 호환이 추론을 끈다(비추론 모델엔 무해). 빈 값=미전송.
    reasoning_effort: str | None = Field(default=None, max_length=EFFORT_MAX_LEN)


class AiConfigOut(BaseModel):
    """현재 유효 설정. configured=false면 값은 env `LLM_*` 폴백을 보여준다."""

    configured: bool
    source: Literal["db", "env"]
    base_url: str
    model: str
    reasoning_effort: str | None = None
    api_key_masked: str | None = None  # 끝 4자만 — 원문 미반환


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
