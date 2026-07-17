"""outbox 기록 헬퍼 — 도메인 쓰기와 같은 트랜잭션에서 outbox_events를 원자 기록.

이중 쓰기 금지(docs/03 §4.9, docs/11 §3.5): 시설 도메인 행과 outbox 이벤트는 한 트랜잭션에서
함께 커밋된다. graph-sync 워커(H3-2)는 도메인 테이블 접근 권한이 없어 payload 스냅샷만으로
Neo4j에 MERGE하므로(docs/03 §5), payload에는 그래프 반영에 필요한 행 스냅샷 전부를 담는다.

sequence는 aggregate_id별 단조 증가(첫 이벤트=1), dedupe_key는 전역 UNIQUE라 중복 이벤트를
DB가 거부한다 — 충돌 시 IntegrityError가 요청 실패로 전파되는 게 올바른 동작(중복 차단).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import OutboxEvent


def _json_safe(value: Any) -> Any:
    """JSONB 저장을 위해 UUID→str·datetime→isoformat로 재귀 직렬화."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


async def record_outbox(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """호출한 도메인 쓰기와 같은 세션(트랜잭션)에서 outbox_events 한 행을 추가한다."""
    current_max = await session.scalar(
        select(func.max(OutboxEvent.sequence)).where(
            OutboxEvent.tenant_id == tenant_id,
            OutboxEvent.aggregate_id == aggregate_id,
        )
    )
    sequence = (current_max or 0) + 1
    session.add(
        OutboxEvent(
            tenant_id=tenant_id,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            event_type=event_type,
            sequence=sequence,
            dedupe_key=f"{aggregate_type}:{aggregate_id}:{sequence}",
            payload=_json_safe(payload),
            status="pending",
            attempts=0,
        )
    )
    await session.flush()
