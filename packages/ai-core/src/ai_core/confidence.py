"""신뢰도 산출·폴백 판정 (docs/01 §6 — 입력: 검색 점수·인용 검증 결과).

임계값은 파일럿 보정 대상(초기값). 임계 미만 = 사용자에겐 폴백 안내 +
messages.review_status=needs_review로 검수 큐(규칙 6).
"""

from __future__ import annotations

from dataclasses import dataclass

# 초기 가중치·임계값 — 파일럿 데이터로 보정한다(docs/01 §6)
RETRIEVAL_WEIGHT = 0.6
CITATION_WEIGHT = 0.4
FALLBACK_THRESHOLD = 0.45  # 미만이면 답변 대신 담당자 연결 폴백
REVIEW_THRESHOLD = 0.65  # 미만이면 답변은 내보내되 검수 큐 등록


@dataclass(frozen=True)
class ConfidenceVerdict:
    score: float
    should_fallback: bool
    needs_review: bool


def assess(
    *,
    top_retrieval_score: float,
    citations_valid: bool,
    invalid_citation_count: int,
) -> ConfidenceVerdict:
    """검색 품질 + 인용 검증 결과로 신뢰도 산출.

    무효 인용(존재하지 않는 근거 번호)은 환각 신호 — 건당 감점.
    """
    citation_score = 1.0 if citations_valid else 0.0
    citation_score -= 0.2 * invalid_citation_count
    citation_score = max(0.0, citation_score)

    raw = RETRIEVAL_WEIGHT * max(0.0, min(1.0, top_retrieval_score))
    raw += CITATION_WEIGHT * citation_score
    score = round(raw, 3)
    return ConfidenceVerdict(
        score=score,
        should_fallback=score < FALLBACK_THRESHOLD,
        needs_review=score < REVIEW_THRESHOLD,
    )
