"""운영 대시보드 집계 계약 (docs/01 §13, docs/09 §8.5 H4-3, FR-ADM-06).

MANAGER 전용 통계 — 별도 집계 테이블·뷰 없이 SQL 즉석 집계(파일럿 규모).
비율은 0~1 분수(프런트가 %로 환산). 분모 0이면 null(프런트는 "—" 표기).
"""

from __future__ import annotations

from pydantic import BaseModel


class AiStats(BaseModel):
    query_count: int  # 기간 내 assistant 메시지 수
    avg_token_input: float | None  # null 제외 평균(없으면 null)
    avg_token_output: float | None
    answer_rate: float | None  # status=answered 비율
    fallback_rate: float | None  # status=fallback 비율
    needs_review_rate: float | None  # 검수 플래그(대기·완료 포함) 비율


class CacheStats(BaseModel):
    hits: int
    misses: int
    hit_rate: float | None  # hits/(hits+misses), 합 0이면 null


class DashboardStatsOut(BaseModel):
    days: int
    ai: AiStats
    cache: CacheStats
    inquiries: dict[str, int]  # 상태(received|assigned|in_progress|done)별 카운트(기간 내 생성)
    facilities: dict[str, int]  # 상태(normal|check|fault|risk)별 카운트(전체 스냅샷)
