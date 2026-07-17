"""민원 키워드 분류 — 우선순위 판정·카테고리 제안(순수 함수, LLM 아님, docs/03 §4.4).

AI가 상태를 바꾸지 않는다(규칙 6·8) — 여기 결과는 `ai_priority`·`ai_suggested_category_id`
제안 컬럼에만 채워지고, 배정·상태 전이는 사람 액션 엔드포인트만 수행한다.
키워드 테이블은 결정적(운영 튜닝 대상) — 자연어 분류는 백로그.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

# 즉시 위험 — 안전·긴급 대응 필요(누수·화재·가스 등). 상단 상수로 튜닝 가능.
URGENT_KEYWORDS = (
    "누수",
    "화재",
    "정전",
    "가스",
    "붕괴",
    "감전",
    "폭발",
    "침수",
    "엘리베이터 갇힘",
    "승강기 갇힘",
    "갇혔",
)
# 일반 생활민원 — 통상 처리(소음·주차·하자 등).
NORMAL_KEYWORDS = (
    "소음",
    "주차",
    "하자",
    "누전",
    "고장",
    "수리",
    "냄새",
    "벌레",
    "층간",
)

Priority = str  # urgent|normal|low


@dataclass(frozen=True)
class Classification:
    priority: Priority
    suggested_category_id: uuid.UUID | None


def classify_inquiry(
    title: str,
    body: str,
    categories: Sequence[tuple[uuid.UUID, str]],
) -> Classification:
    """제목+본문 키워드로 우선순위·제안 카테고리를 판정.

    - urgent 키워드 포함 → urgent, 일반 키워드 포함 → normal, 그 외 → low.
    - categories(id, name) 중 이름이 텍스트에 포함되는 첫 매치를 제안 카테고리로.
    """
    text = f"{title} {body}"
    if any(kw in text for kw in URGENT_KEYWORDS):
        priority = "urgent"
    elif any(kw in text for kw in NORMAL_KEYWORDS):
        priority = "normal"
    else:
        priority = "low"
    suggested = next((cid for cid, name in categories if name and name in text), None)
    return Classification(priority=priority, suggested_category_id=suggested)
