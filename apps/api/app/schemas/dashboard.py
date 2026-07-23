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


class ActionQueueStats(BaseModel):
    """오늘 할 일 — 기간 무관 현재 상태 open 카운트(대시보드 최상단). tenant 격리(규칙 3)."""

    approvals_pending: int  # 가입 승인 대기(User.status=pending)
    inquiries_unassigned: int  # 미배정 민원(status=received)
    inquiries_in_progress: int  # 처리중 민원(status=in_progress)
    notices_draft: int  # 임시저장 공지(status=draft)
    notices_scheduled: int  # 예약 발행 예정 공지(status=scheduled)


class CacheStats(BaseModel):
    hits: int
    misses: int
    hit_rate: float | None  # hits/(hits+misses), 합 0이면 null


class BudgetStats(BaseModel):
    """단지 일일 토큰 예산 대비 사용량(H4-4, NFR-COST-01). 경고만 — 차단 없음."""

    enabled: bool  # 예산 설정 여부(budget > 0)
    budget: int  # 일일 상한(토큰). 비활성이면 0
    used_today: int  # 오늘(UTC) assistant 입출력 토큰 합계
    exceeded: bool  # enabled and used_today > budget


class DashboardStatsOut(BaseModel):
    days: int
    actions: ActionQueueStats  # 오늘 할 일(기간 무관 open 카운트)
    ai: AiStats
    cache: CacheStats
    budget: BudgetStats
    inquiries: dict[str, int]  # 상태(received|assigned|in_progress|done)별 카운트(기간 내 생성)
    facilities: dict[str, int]  # 상태(normal|check|fault|risk)별 카운트(전체 스냅샷)
