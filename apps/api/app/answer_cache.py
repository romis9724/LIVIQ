"""AI 질의 정확 캐시 — Redis 얇은 래퍼 (docs/08 §2.0·2.1, docs/09 §8.5 H4-2).

캐시 격리가 최우선(CRITICAL). 키에 tenant·(user 또는 roles·visibilities)·인제스트
세대(gen)·모델·정규화 질의 해시를 모두 넣어 다른 사용자/역할/단지로 히트가 전파되지
않게 한다. 히트 시 저장된 페이로드로 SSE 이벤트를 재생 → LLM 호출 0.

- 개인 데이터 도구(get_fees·get_my_inquiries) 경로 답변은 **user 스코프** 키에만 저장.
  그 외는 tenant 스코프(roles·visibilities 분리) 키.
- 무효화는 키 수준: `cache:gen:{tenant}` 증가(재색인·visibility 변경) → 이전 키 자연 미스.
- Redis 장애는 삼켜 정상 경로로(fail-open, rate_limit.py와 동일 원칙) — 캐시는 성능
  보조 장치이지 인가 게이트가 아니다.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from ai_core.citations import Citation
from ai_core.llm.client import ChatUsage
from ai_core.orchestrator import (
    AssistantEvent,
    CitationEvent,
    DoneEvent,
    StatusEvent,
    TokenEvent,
    ToolCitation,
    ToolCitationEvent,
)
from ai_core.tools import ToolContext
from app.config import get_settings

logger = logging.getLogger("app.answer_cache")

_KEY_PREFIX = "cache:ans:"
# 개인 데이터 도구 — 경로에 하나라도 있으면 user 스코프 키에 저장(사용자 간 전파 금지).
_PERSONAL_TOOLS = frozenset({"get_fees", "get_my_inquiries"})


class CacheIsolationError(RuntimeError):
    """재생 직전 tenant 불일치 — 키 격리가 뚫린 신호(절대 발생하면 안 됨, fail-closed)."""


@dataclass(frozen=True)
class CachedAnswer:
    """캐시된 답변 페이로드 — DoneEvent 재구성에 필요한 필드 일체."""

    tenant_id: str
    answer: str
    status: str
    confidence: float
    needs_review: bool
    fallback_reason: str | None
    tool_path: tuple[str, ...]
    citations: tuple[Citation, ...]
    tool_citations: tuple[ToolCitation, ...]


# ── 설정·정규화 ────────────────────────────────────────────────────────


def _ttl() -> int:
    """캐시 TTL 초. 0 = 캐시 전체 비활성."""
    return get_settings().answer_cache_ttl_s


def current_model() -> str:
    """캐시 키용 LLM 모델명 — env(LLM_MODEL) 직접. 모델 교체 시 키가 바뀌어 자연 무효화.

    ponytail: env 미노출(.env 파일로만 주입) 배포에선 ""로 수렴해 모델 교체 무효화가
    약해진다 — 운영은 실 env var 사용이라 무해. 강화 필요 시 ai_core 설정 주입으로 승급.
    """
    return os.environ.get("LLM_MODEL", "")


def _normalize(question: str) -> str:
    """보수적 정규화 — 공백 압축·소문자만(과도한 정규화는 다른 질문을 같은 키로 만든다)."""
    return " ".join(question.split()).lower()


def _qhash(question: str) -> str:
    return hashlib.sha256(_normalize(question).encode()).hexdigest()


# ── 키 ─────────────────────────────────────────────────────────────────


def _user_key(ctx: ToolContext, gen: int, model: str, qhash: str) -> str:
    return f"{_KEY_PREFIX}u:{ctx.tenant_id}:{ctx.user_id}:{gen}:{model}:{qhash}"


def _tenant_key(ctx: ToolContext, gen: int, model: str, qhash: str) -> str:
    roles = ",".join(sorted(ctx.roles))
    visibilities = ",".join(sorted(ctx.visibilities))
    return f"{_KEY_PREFIX}t:{ctx.tenant_id}:{roles}:{visibilities}:{gen}:{model}:{qhash}"


def _gen_key(tenant_id: uuid.UUID) -> str:
    return f"cache:gen:{tenant_id}"


async def _generation(redis: Redis, tenant_id: uuid.UUID) -> int:
    raw = await redis.get(_gen_key(tenant_id))
    return int(raw) if raw is not None else 0


def _is_personal(tool_path: tuple[str, ...]) -> bool:
    return any(name in _PERSONAL_TOOLS for name in tool_path)


# ── 조회·저장 ──────────────────────────────────────────────────────────


async def lookup(redis: Redis, *, ctx: ToolContext, question: str) -> CachedAnswer | None:
    """user 키 → tenant 키 순으로 조회. 히트/미스 카운터도 여기서 기록.

    Redis·디코드 실패는 삼켜 None(미스로 취급) — fail-open.
    """
    ttl = _ttl()
    if ttl <= 0:  # 캐시 비활성 — 카운터도 남기지 않음
        return None
    model = current_model()
    qhash = _qhash(question)
    try:
        gen = await _generation(redis, ctx.tenant_id)
        for key in (_user_key(ctx, gen, model, qhash), _tenant_key(ctx, gen, model, qhash)):
            raw = await redis.get(key)
            if raw is not None:
                await redis.incr(f"cache:hits:{ctx.tenant_id}")
                return _decode(raw)
        await redis.incr(f"cache:misses:{ctx.tenant_id}")
        return None
    except (RedisError, json.JSONDecodeError, KeyError, ValueError) as exc:
        logger.warning("answer-cache lookup 실패 — fail-open 미스: %s", exc)
        return None


async def store(redis: Redis, *, ctx: ToolContext, question: str, done: DoneEvent) -> None:
    """스트림 완료 후 저장. answered·검수 불필요만 캐시(폴백·needs_review 캐시 금지).

    개인 도구 경로면 user 키, 아니면 tenant 키. Redis 장애는 삼킨다(fail-open).
    """
    ttl = _ttl()
    if ttl <= 0:
        return
    if done.status != "answered" or done.needs_review:
        return
    model = current_model()
    qhash = _qhash(question)
    try:
        gen = await _generation(redis, ctx.tenant_id)
        key = (
            _user_key(ctx, gen, model, qhash)
            if _is_personal(done.tool_path)
            else _tenant_key(ctx, gen, model, qhash)
        )
        await redis.set(key, _encode(done, ctx.tenant_id), ex=ttl)
    except RedisError as exc:
        logger.warning("answer-cache store 실패 — fail-open: %s", exc)


async def bump_generation(redis: Redis, tenant_id: uuid.UUID) -> None:
    """인제스트 완료·문서 visibility 변경 시 세대 증가 → 이전 키 전량 자연 미스.

    Redis 장애는 삼킨다(fail-open) — 무효화 실패가 서비스 중단이 되면 안 된다.
    """
    try:
        await redis.incr(_gen_key(tenant_id))
    except RedisError as exc:
        logger.warning("answer-cache 세대 증가 실패 — fail-open: %s", exc)


# ── 재생 ───────────────────────────────────────────────────────────────


async def replay(cached: CachedAnswer, *, tenant_id: uuid.UUID) -> AsyncIterator[AssistantEvent]:
    """히트 페이로드를 정상 경로와 동일한 이벤트 순서로 재생(LLM 호출 없음).

    재생 직전 tenant 일치를 확인한다 — 키에 tenant가 들어가 구조적으로 안전하지만,
    페이로드 오염·키 충돌을 잡는 방어선(격리 CRITICAL, fail-closed).
    """
    if cached.tenant_id != str(tenant_id):
        raise CacheIsolationError(f"캐시 tenant 불일치: payload={cached.tenant_id} ctx={tenant_id}")
    yield StatusEvent(stage="searching")
    yield StatusEvent(stage="generating")
    yield TokenEvent(text=cached.answer)
    yield StatusEvent(stage="verifying")
    for citation in cached.citations:
        yield CitationEvent(citation=citation)
    for tc in cached.tool_citations:
        yield ToolCitationEvent(citation=tc)
    yield DoneEvent(
        status=cached.status,
        confidence=cached.confidence,
        needs_review=cached.needs_review,
        # LLM 호출 없음 → 토큰 0(정직한 기록). 추정 아님.
        usage=ChatUsage(input_tokens=0, output_tokens=0),
        fallback_reason=cached.fallback_reason,
        citations=cached.citations,
        tool_citations=cached.tool_citations,
        answer=cached.answer,
        tool_path=cached.tool_path,
    )


# ── 직렬화 ─────────────────────────────────────────────────────────────


def _encode(done: DoneEvent, tenant_id: uuid.UUID) -> str:
    payload = {
        "tenant_id": str(tenant_id),
        "answer": done.answer,
        "status": done.status,
        "confidence": done.confidence,
        "needs_review": done.needs_review,
        "fallback_reason": done.fallback_reason,
        "tool_path": list(done.tool_path),
        "citations": [
            {
                "ref": c.ref,
                "chunk_id": str(c.chunk_id),
                "document_id": str(c.document_id),
                "document_title": c.document_title,
                "quote": c.quote,
                "page": c.page,
                "clause": c.clause,
            }
            for c in done.citations
        ],
        "tool_citations": [
            {"ref": tc.ref, "title": tc.title, "quote": tc.quote, "source_kind": tc.source_kind}
            for tc in done.tool_citations
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def _decode(raw: str) -> CachedAnswer:
    data = json.loads(raw)
    citations = tuple(
        Citation(
            ref=c["ref"],
            chunk_id=uuid.UUID(c["chunk_id"]),
            document_id=uuid.UUID(c["document_id"]),
            document_title=c["document_title"],
            quote=c["quote"],
            page=c["page"],
            clause=c["clause"],
        )
        for c in data["citations"]
    )
    tool_citations = tuple(
        ToolCitation(ref=t["ref"], title=t["title"], quote=t["quote"], source_kind=t["source_kind"])
        for t in data["tool_citations"]
    )
    return CachedAnswer(
        tenant_id=data["tenant_id"],
        answer=data["answer"],
        status=data["status"],
        confidence=data["confidence"],
        needs_review=data["needs_review"],
        fallback_reason=data.get("fallback_reason"),
        tool_path=tuple(data["tool_path"]),
        citations=citations,
        tool_citations=tool_citations,
    )
