"""outbox → Neo4j graph-sync (docs/03 §4.9, docs/11 §3.5·§4).

`ai-worker`가 `outbox_events`(status=pending)를 순차 claim(`FOR UPDATE SKIP LOCKED`,
워커 role은 큐 테이블만 cross-tenant — docs/03 §5)해 payload 스냅샷만으로 Neo4j에 MERGE한다.
그래프 반영은 typed query 레이어(raw Cypher 금지)와 `last_applied_version` 역전 방지로 멱등.

- Incident는 symptom(+resolution)을 **`ensure_masked` 후 임베딩**(규칙 2). 마스킹 실패 시
  임베딩을 생략하고 노드만 반영(동기화는 완료, 벡터 검색에서만 제외).
- 임베딩 엔드포인트 미가용(LlmUnavailableError)은 인프라 오류 → 예외 전파(트랜잭션 롤백,
  arq 재시도). 그 외 실패는 attempts++, MAX_ATTEMPTS 초과 시 status=failed(DLQ).
"""

from __future__ import annotations

import datetime
import logging
from typing import Any

from sqlalchemy import select

from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient, LlmUnavailableError
from ai_core.masking.gate import MaskingFailedError, ensure_masked
from liviq_db.models import OutboxEvent

logger = logging.getLogger(__name__)

BATCH_SIZE = 100
MAX_ATTEMPTS = 5


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def sync_outbox_task(ctx: dict[str, Any]) -> dict[str, int]:
    """pending outbox 배치를 Neo4j에 반영. arq cron(15초)이 호출."""
    session_factory = ctx["session_factory"]
    graph: GraphClient = ctx["graph"]
    llm: LlmClient = ctx["llm"]

    processed = 0
    failed = 0
    async with session_factory() as session, session.begin():
        # 워커 role은 큐 테이블 cross-tenant(policy worker_queue_access) — tenant SET LOCAL 없이
        # 전 tenant claim. 같은 aggregate는 sequence 오름차순으로 처리(역전 방지 보강).
        rows = (
            await session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.status == "pending")
                .order_by(
                    OutboxEvent.created_at,
                    OutboxEvent.aggregate_id,
                    OutboxEvent.sequence,
                )
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()

        for event in rows:
            try:
                await _apply_event(graph, llm, event)
            except LlmUnavailableError:
                # 인프라 오류 — 트랜잭션 롤백 후 arq 재시도(attempts 미증가)
                raise
            except Exception as exc:  # noqa: BLE001 — 개별 이벤트 실패 격리(DLQ 경로)
                event.attempts += 1
                if event.attempts >= MAX_ATTEMPTS:
                    event.status = "failed"
                    logger.error(
                        "graph-sync DLQ: event=%s type=%s attempts=%s err=%s",
                        event.id,
                        event.aggregate_type,
                        event.attempts,
                        exc,
                    )
                    failed += 1
                else:
                    logger.warning(
                        "graph-sync 재시도 예정: event=%s attempts=%s err=%s",
                        event.id,
                        event.attempts,
                        exc,
                    )
                continue
            event.status = "processed"
            event.processed_at = _now()
            processed += 1

    return {"processed": processed, "failed": failed}


async def _apply_event(graph: GraphClient, llm: LlmClient, event: OutboxEvent) -> None:
    """이벤트 1건을 typed merge로 그래프에 반영. payload는 _json_safe 직렬화된 스냅샷."""
    payload: dict[str, Any] = event.payload or {}
    tenant = str(event.tenant_id)
    pg_id = str(event.aggregate_id)
    version = event.sequence

    if event.aggregate_type == "facility":
        await graph.merge_facility(tenant_id=tenant, pg_id=pg_id, props=payload, version=version)
    elif event.aggregate_type == "incident":
        embedding = await _incident_embedding(llm, payload)
        await graph.merge_incident(
            tenant_id=tenant,
            pg_id=pg_id,
            facility_id=str(payload["facility_id"]),
            props=payload,
            version=version,
            embedding=embedding,
        )
    elif event.aggregate_type == "maintenance_log":
        await graph.merge_maintenance(
            tenant_id=tenant,
            pg_id=pg_id,
            facility_id=str(payload["facility_id"]),
            props=payload,
            version=version,
            parts=payload.get("parts"),
        )
    else:
        raise ValueError(f"알 수 없는 aggregate_type: {event.aggregate_type}")


async def _incident_embedding(llm: LlmClient, payload: dict[str, Any]) -> list[float] | None:
    """장애 텍스트 임베딩. 마스킹 실패 시 None(노드만 반영, 검색 제외 — 규칙 2)."""
    parts = [payload.get("symptom"), payload.get("resolution")]
    text = "\n".join(p for p in parts if p)
    if not text.strip():
        return None
    try:
        masked = ensure_masked(text)
    except MaskingFailedError:
        logger.warning("graph-sync 임베딩 생략(마스킹 실패) — 노드만 반영")
        return None
    vectors = await llm.embed([masked.masked_text])
    return vectors[0] if vectors else None
