"""graph-sync 태스크 — 배치 처리·상태 전이·DLQ·임베딩/마스킹 (docs/03 §4.9).

그래프 내부 동작(MERGE·격리·벡터 인덱스)은 ai-core test_graph에서 실 Neo4j로 검증한다.
여기서는 태스크 오케스트레이션(claim→typed merge→상태 전이·재시도·임베딩 배선)을 본다 —
GraphClient는 호출을 기록/실패하는 스텁으로 대체(빠른 단위 경계).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ai_core.llm.client import LlmClient
from ai_worker.graph_sync import sync_outbox_task
from liviq_db.models import OutboxEvent, Tenant

_DIM = 1024


class SpyGraph:
    """merge 호출을 기록하는 GraphClient 스텁."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def merge_facility(self, **kw: Any) -> None:
        self.calls.append({"kind": "facility", **kw})

    async def merge_incident(self, **kw: Any) -> None:
        self.calls.append({"kind": "incident", **kw})

    async def merge_maintenance(self, **kw: Any) -> None:
        self.calls.append({"kind": "maintenance", **kw})


class FailingGraph:
    async def merge_facility(self, **kw: Any) -> None:
        raise RuntimeError("Neo4j 쓰기 실패")

    async def merge_incident(self, **kw: Any) -> None:
        raise RuntimeError("Neo4j 쓰기 실패")

    async def merge_maintenance(self, **kw: Any) -> None:
        raise RuntimeError("Neo4j 쓰기 실패")


class SpyLlm:
    def __init__(self) -> None:
        self.embed_calls: list[list[str]] = []

    async def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [[0.01] * _DIM for _ in texts]


def _outbox(
    tenant_id: uuid.UUID,
    *,
    aggregate_type: str,
    payload: dict[str, Any],
    attempts: int = 0,
    status: str = "pending",
) -> OutboxEvent:
    agg_id = uuid.uuid4()
    return OutboxEvent(
        tenant_id=tenant_id,
        aggregate_type=aggregate_type,
        aggregate_id=agg_id,
        event_type="created",
        sequence=1,
        dedupe_key=f"{aggregate_type}:{agg_id}:1",
        payload=payload,
        status=status,
        attempts=attempts,
    )


async def _seed(factory: async_sessionmaker[Any], events_for: Any) -> uuid.UUID:
    async with factory() as s, s.begin():
        tenant = Tenant(name="t", status="active")
        s.add(tenant)
        await s.flush()
        for ev in events_for(tenant.id):
            s.add(ev)
        return tenant.id


async def _cleanup(factory: async_sessionmaker[Any], tenant_id: uuid.UUID) -> None:
    async with factory() as s, s.begin():
        tenant = await s.get(Tenant, tenant_id)
        if tenant is not None:
            await s.delete(tenant)


def _factory(pg_dsn: str) -> tuple[Any, async_sessionmaker[Any]]:
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _statuses(factory: async_sessionmaker[Any], tenant_id: uuid.UUID) -> list[str]:
    async with factory() as c:
        rows = await c.scalars(select(OutboxEvent.status).where(OutboxEvent.tenant_id == tenant_id))
        return list(rows)


async def test_pending_batch_processed_and_reflected(pg_dsn: str, fake_llm: LlmClient) -> None:
    engine, factory = _factory(pg_dsn)
    fac_id = uuid.uuid4()

    def events(tid: uuid.UUID) -> list[OutboxEvent]:
        fac = _outbox(tid, aggregate_type="facility", payload={"name": "펌프", "status": "normal"})
        fac.aggregate_id = fac_id
        fac.dedupe_key = f"facility:{fac_id}:1"
        inc = _outbox(
            tid,
            aggregate_type="incident",
            payload={"facility_id": str(fac_id), "symptom": "소음"},
        )
        return [fac, inc]

    tenant_id = await _seed(factory, events)
    graph = SpyGraph()
    ctx = {"session_factory": factory, "graph": graph, "llm": fake_llm}
    try:
        result = await sync_outbox_task(ctx)
        assert result["processed"] >= 2
        assert set(await _statuses(factory, tenant_id)) == {"processed"}

        kinds = {c["kind"] for c in graph.calls}
        assert kinds == {"facility", "incident"}
        incident_call = next(c for c in graph.calls if c["kind"] == "incident")
        assert incident_call["embedding"] is not None
        assert len(incident_call["embedding"]) == _DIM
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()


async def test_failed_event_increments_attempts_then_dlq(pg_dsn: str, fake_llm: LlmClient) -> None:
    engine, factory = _factory(pg_dsn)

    def events(tid: uuid.UUID) -> list[OutboxEvent]:
        return [
            # 4회 실패한 이력 → 이번 실패로 5회 = DLQ(failed)
            _outbox(tid, aggregate_type="facility", payload={"name": "a"}, attempts=4),
            # 신규 → 1회 실패, 아직 pending 유지
            _outbox(tid, aggregate_type="facility", payload={"name": "b"}, attempts=0),
        ]

    tenant_id = await _seed(factory, events)
    ctx = {"session_factory": factory, "graph": FailingGraph(), "llm": fake_llm}
    try:
        result = await sync_outbox_task(ctx)
        assert result["failed"] == 1
        assert sorted(await _statuses(factory, tenant_id)) == ["failed", "pending"]
        async with factory() as c:
            attempts = sorted(
                (
                    await c.scalars(
                        select(OutboxEvent.attempts).where(OutboxEvent.tenant_id == tenant_id)
                    )
                ).all()
            )
        assert attempts == [1, 5]
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()


async def test_incident_embedding_invoked(pg_dsn: str) -> None:
    engine, factory = _factory(pg_dsn)

    def events(tid: uuid.UUID) -> list[OutboxEvent]:
        return [
            _outbox(
                tid,
                aggregate_type="incident",
                payload={"facility_id": str(uuid.uuid4()), "symptom": "누수", "resolution": "교체"},
            )
        ]

    tenant_id = await _seed(factory, events)
    spy_llm = SpyLlm()
    graph = SpyGraph()
    ctx = {"session_factory": factory, "graph": graph, "llm": spy_llm}
    try:
        await sync_outbox_task(ctx)
        assert len(spy_llm.embed_calls) == 1
        assert graph.calls[0]["embedding"] is not None
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()


async def test_masking_failure_skips_embedding_but_reflects_node(
    pg_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ai_core.masking.gate import MaskingFailedError

    def _raise(_text: str) -> Any:
        raise MaskingFailedError("잔존 PII")

    monkeypatch.setattr("ai_worker.graph_sync.ensure_masked", _raise)

    engine, factory = _factory(pg_dsn)

    def events(tid: uuid.UUID) -> list[OutboxEvent]:
        return [
            _outbox(
                tid,
                aggregate_type="incident",
                payload={"facility_id": str(uuid.uuid4()), "symptom": "홍길동 010-1234-5678"},
            )
        ]

    tenant_id = await _seed(factory, events)
    spy_llm = SpyLlm()
    graph = SpyGraph()
    ctx = {"session_factory": factory, "graph": graph, "llm": spy_llm}
    try:
        await sync_outbox_task(ctx)
        # 마스킹 실패 → 임베딩 생략, 노드는 반영, 이벤트는 processed
        assert spy_llm.embed_calls == []
        assert graph.calls[0]["embedding"] is None
        assert await _statuses(factory, tenant_id) == ["processed"]
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()
