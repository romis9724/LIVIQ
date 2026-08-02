"""assistant SSE 계약 — 이벤트 4종(token·citation·status·done), 스키마 불변(docs/09 §1.1)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

QUESTION_MAX_CHARS = 2000  # 거대 붙여넣기 거절(docs/08 §8)

StatusStage = Literal["searching", "generating", "verifying"]
# clarify = 되묻기(ADR-0025 §4). **리터럴 확장**이지 이벤트 종류 추가가 아니다 —
# done 이벤트의 status 값만 늘었고 SSE 4종 계약은 그대로다.
AnswerStatus = Literal["answered", "fallback", "clarify"]


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=QUESTION_MAX_CHARS)
    conversation_id: uuid.UUID | None = None
    # 되묻기 허용 여부 — **자동 발화**(관리자 진입 브리핑)가 끄는 용도다(additive, 기본 True).
    # 화면을 연 직후 코드가 보내는 질의라 되물어도 답할 사람이 없다 — 되묻기로 끝나면 그냥
    # 빈손이다. 능력을 **줄이는** 방향만이라(도구를 감출 뿐 강제하지 않는다) 규칙 8 무관이고,
    # 근거 규율도 그대로다: 되물을 수 없으면 답변 아니면 폴백으로 끝난다.
    allow_clarify: bool = True


# ── SSE data 페이로드 (이벤트 이름은 token|citation|status|done) ────────


class StatusData(BaseModel):
    stage: StatusStage
    # 지금 실행 중인 도구 이름(ADR-0025 §5) — additive 필드. stage 리터럴 3종은 확장하지 않는다.
    # 기존 소비자는 stage만 읽으면 그대로 동작한다.
    tool: str | None = None


class TokenData(BaseModel):
    text: str


class CitationData(BaseModel):
    ref: int
    document_id: uuid.UUID | None = None  # 문서 인용은 UUID, 확정 데이터(관리비 등) 인용은 null
    document_title: str
    quote: str
    page: int | None = None
    clause: str | None = None
    # 도구 카드의 구조화 페이로드(ADR-0025 §6) — 표·목록을 값 그대로 렌더하기 위한 것.
    # 문서 인용은 항상 null. 스키마는 도구마다 다르고 `kind` 키로 분기한다.
    # 이 값은 LLM을 거치지 않은 도구 확정 값이다(규칙 5·8 — 숫자 재작성 경로 없음).
    data: dict[str, Any] | None = None


class DoneData(BaseModel):
    message_id: uuid.UUID | None = None  # 폴백 등 미저장 시 None
    conversation_id: uuid.UUID
    status: AnswerStatus
    confidence: float
    needs_review: bool
    fallback_reason: str | None = None
    # 호출한 도구 이름 순서(H3-4) — additive 필드, SSE 이벤트 4종 계약 불변.
    tool_path: list[str] = Field(default_factory=list)
    # 토큰 usage(H15-2 질의당 원가 계량) — additive 필드, SSE 이벤트 4종 계약 불변.
    # usage 없는 경로(근거 0 폴백 등)는 None. token_estimated=True면 프로바이더 미제공 추정치다.
    token_input: int | None = None
    token_output: int | None = None
    token_estimated: bool = False
    # 서버가 확정한 답변 본문 — 클라이언트는 이 값이 있으면 **정본으로** 쓴다(additive 필드).
    # 스트리밍 토큰은 마스킹된 원문이라 PII 자리표시자가 보일 수 있는데, 이 값은 unmask 후의
    # 최종본이다. 서버가 확정한 답변과 화면이 갈라지지 않게 하는 것이 목적이다.
    answer: str | None = None
    # 다음 행동 제안(ADR-0025 §7) — tool_path 기반 코드 규칙, LLM 호출 0. additive 필드로
    # 빈 배열이 기본이라 기존 소비자는 몰라도 된다.
    suggestions: list[str] = Field(default_factory=list)


# ── 서버 대화 복원 (ADR-0027 결정 1) ────────


class RestoredMessage(BaseModel):
    """복원 메시지 — **텍스트 위주**. 구조화 표·CTA·진행 단계는 복원 대상이 아니다."""

    id: uuid.UUID
    role: str  # user|assistant
    content: str
    status: str | None  # answered|fallback|handed_off|clarify|None(user 메시지)


class LatestConversationResponse(BaseModel):
    # 대화가 없으면 conversation_id=null + 빈 배열 — 첫 방문은 오류가 아니다.
    conversation_id: uuid.UUID | None
    messages: list[RestoredMessage]
