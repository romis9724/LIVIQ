"""공지 초안 생성 — 검색→마스킹→생성→인용검증 (규칙 1·6, docs/01 §13).

질의응답(orchestrator)과 흐름은 같으나 세 가지가 다르다:
1. 논스트리밍 1회 생성(초안은 스트림 UX가 필요 없다).
2. 공지문 형식 프롬프트(첫 줄 제목 + 본문).
3. 근거 0·인용 검증 실패 시 예외(초안 자체를 만들지 않음 — 지어낸 공지 금지).

api가 예외를 422로 매핑하고, 생성된 초안은 사람 검수 후에만 발행한다(규칙 6).
검색·마스킹·인용검증·신뢰도 조각은 orchestrator와 동일 모듈을 재사용한다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from ai_core.budget import ScoredChunk, fit_chunks
from ai_core.citations import Citation, verify_citations
from ai_core.confidence import assess
from ai_core.llm.client import LlmClient
from ai_core.masking import ensure_masked, unmask
from ai_core.rag.prompt import NO_EVIDENCE_MARKER, build_context_block
from ai_core.rag.retrieval import DEFAULT_TOP_K, MIN_SCORE, RetrievedChunk, Retriever

# 관리자 공지 작성은 전 공개범위 문서를 근거로 쓸 수 있다(docs/03 §4.2).
ADMIN_VISIBILITIES = ("ALL", "RESIDENT", "ADMIN", "COUNCIL")
CONTEXT_BUDGET_TOKENS = 2400  # orchestrator와 동일 초기값(파일럿 보정)
DRAFT_MAX_TOKENS = 800  # 제목+본문 한 건 상한(비용, docs/08)

NOTICE_SYSTEM_PROMPT = """당신은 아파트 관리사무소의 공지문 작성 도우미입니다. 규칙:
1. 아래 [근거]에 있는 사실만으로 공지문을 작성하십시오. 근거에 없는 내용은 절대 지어내지 마십시오.
2. 첫 줄에 공지 제목만 쓰고, 한 줄 비운 뒤 본문을 작성하십시오.
3. 본문에서 사용한 근거는 반드시 해당 문장 끝에 [번호] 형식으로 인용하십시오.
4. 근거로 공지문을 작성할 수 없으면 정확히 "NO_EVIDENCE"라고만 답하십시오.
5. 정중하고 간결한 한국어 공지문으로 작성하십시오."""


class NoEvidenceError(Exception):
    """근거 문서 없음·인용 검증 실패 — 초안을 만들지 않는다(지어내기 금지, 규칙 1)."""


@dataclass(frozen=True)
class NoticeDraftResult:
    title: str
    body: str
    citations: tuple[Citation, ...]
    confidence: float


async def draft_notice(
    keywords: Sequence[str],
    *,
    llm: LlmClient,
    retriever: Retriever,
    tenant_id: uuid.UUID,
    visibilities: Sequence[str] = ADMIN_VISIBILITIES,
) -> NoticeDraftResult:
    """키워드로 근거 검색→공지문 생성. 근거·인용이 없으면 NoEvidenceError.

    LLM/임베딩 미가용은 LlmError로 전파(api가 503으로 매핑).
    마스킹 실패는 MaskingFailedError로 전파(fail-closed, 규칙 2).
    """
    query = _keywords_text(keywords)
    query_vec = (await llm.embed([query]))[0]
    chunks = await retriever.search(
        query_vec, tenant_id=tenant_id, visibilities=visibilities, top_k=DEFAULT_TOP_K
    )
    evidence = _fit(chunks)
    if not evidence:
        raise NoEvidenceError("근거 문서 없음")

    # 마스킹 게이트(키워드+근거, fail-closed — 규칙 2). 실패 시 예외 전파.
    masked = ensure_masked(f"[근거]\n{build_context_block(evidence)}\n\n[키워드]\n{query}")

    response = await llm.chat(
        [
            {"role": "system", "content": NOTICE_SYSTEM_PROMPT},
            {"role": "user", "content": masked.masked_text},
        ],
        max_tokens=DRAFT_MAX_TOKENS,
    )
    answer = unmask(response.text.strip(), masked.replacements)
    if not answer or NO_EVIDENCE_MARKER in answer:
        raise NoEvidenceError("생성 결과가 근거로 뒷받침되지 않음")

    # 인용 실재 검증 — 근거에 없는 [n]은 환각. 유효 인용 0이면 거절(규칙 1).
    check = verify_citations(answer, evidence)
    if not check.citations:
        raise NoEvidenceError("인용 없는 초안 — 근거 미검증")

    title, body = _split_title_body(answer)
    if not title or not body:
        raise NoEvidenceError("공지문 형식 파싱 실패")

    verdict = assess(
        top_retrieval_score=evidence[0].score,
        citations_valid=check.is_valid,
        invalid_citation_count=len(check.invalid_refs),
    )
    return NoticeDraftResult(
        title=title, body=body, citations=check.citations, confidence=verdict.score
    )


def _keywords_text(keywords: Sequence[str]) -> str:
    return " ".join(k.strip() for k in keywords if k.strip())


def _fit(chunks: Sequence[RetrievedChunk]) -> list[RetrievedChunk]:
    """MIN_SCORE 미달 제거 → 토큰 예산 절단(orchestrator._fit와 동일 규칙)."""
    eligible = [c for c in chunks if c.score >= MIN_SCORE]
    by_id = {str(c.chunk_id): c for c in eligible}
    fitted = fit_chunks(
        [ScoredChunk(id=str(c.chunk_id), content=c.content, score=c.score) for c in eligible],
        budget_tokens=CONTEXT_BUDGET_TOKENS,
    )
    return [by_id[s.id] for s in fitted]


def _split_title_body(text: str) -> tuple[str, str]:
    """첫 비어있지 않은 줄=제목("제목:" 접두 제거), 나머지=본문."""
    lines = text.strip().splitlines()
    title = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip():
            title = line.strip()
            body_start = i + 1
            break
    title = title.removeprefix("제목:").strip()
    body = "\n".join(lines[body_start:]).strip()
    return title, body
