"""예약 공지 발행 cron — 도달 공지 published 전이 + 알림, 미도달/삭제 제외 (H8-1, ADR-0015).

실 PG(testcontainers)에서 publish_due_notices를 직접 호출한다. 실행마다 tenant를 정리해
cross-tenant 스캔이 이전 테스트 잔재를 집지 않게 한다.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ai_worker.notices_publish import publish_due_notices
from liviq_db.models import Notice, Notification, Tenant, User


def _factory(pg_dsn: str) -> tuple[Any, async_sessionmaker[Any]]:
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_scheduled(
    factory: async_sessionmaker[Any],
    *,
    scheduled_at: datetime.datetime,
    deleted: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    """tenant + active 사용자 2명 + scheduled 공지 1건. (tenant_id, notice_id) 반환."""
    now = datetime.datetime.now(datetime.UTC)
    async with factory() as s, s.begin():
        tenant = Tenant(name="t", status="active")
        s.add(tenant)
        await s.flush()
        s.add(User(tenant_id=tenant.id, status="active"))
        s.add(User(tenant_id=tenant.id, status="active"))
        notice = Notice(
            tenant_id=tenant.id,
            title="예약 공지",
            body="본문",
            status="scheduled",
            pinned=False,
            audience="ALL",
            scheduled_at=scheduled_at,
            deleted_at=now if deleted else None,
        )
        s.add(notice)
        await s.flush()
        return tenant.id, notice.id


async def _cleanup(factory: async_sessionmaker[Any], tenant_id: uuid.UUID) -> None:
    async with factory() as s, s.begin():
        tenant = await s.get(Tenant, tenant_id)
        if tenant is not None:
            await s.delete(tenant)  # cascade → notices·users·notifications


async def _fetch(factory: async_sessionmaker[Any], notice_id: uuid.UUID) -> Notice:
    async with factory() as s:
        notice = await s.get(Notice, notice_id)
        assert notice is not None
        return notice


async def _notif_count(factory: async_sessionmaker[Any], tenant_id: uuid.UUID) -> int:
    async with factory() as s:
        value = await s.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.tenant_id == tenant_id, Notification.type == "notice")
        )
        return int(value or 0)


async def test_due_notice_published_and_notifies(pg_dsn: str) -> None:
    engine, factory = _factory(pg_dsn)
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    tenant_id, notice_id = await _seed_scheduled(factory, scheduled_at=past)
    try:
        result = await publish_due_notices({"session_factory": factory})
        assert result["published"] >= 1

        notice = await _fetch(factory, notice_id)
        assert notice.status == "published"
        assert notice.published_at is not None
        assert await _notif_count(factory, tenant_id) == 2  # active 사용자 2명
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()


async def test_future_notice_excluded(pg_dsn: str) -> None:
    engine, factory = _factory(pg_dsn)
    future = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=1)
    tenant_id, notice_id = await _seed_scheduled(factory, scheduled_at=future)
    try:
        await publish_due_notices({"session_factory": factory})
        notice = await _fetch(factory, notice_id)
        assert notice.status == "scheduled"  # 미도달 → 불변
        assert await _notif_count(factory, tenant_id) == 0
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()


async def test_deleted_due_notice_excluded(pg_dsn: str) -> None:
    engine, factory = _factory(pg_dsn)
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    tenant_id, notice_id = await _seed_scheduled(factory, scheduled_at=past, deleted=True)
    try:
        await publish_due_notices({"session_factory": factory})
        notice = await _fetch(factory, notice_id)
        assert notice.status == "scheduled"  # soft delete → 제외
        assert await _notif_count(factory, tenant_id) == 0
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()


class _RecordingRedis:
    """arq redis 대역 — enqueue_job 호출만 기록(발행→인제스트 연결 검증, H8-3)."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[Any, ...]]] = []

    async def enqueue_job(self, task: str, *args: Any) -> None:
        self.jobs.append((task, args))


async def test_due_publish_enqueues_ingest(pg_dsn: str) -> None:
    engine, factory = _factory(pg_dsn)
    past = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=1)
    tenant_id, notice_id = await _seed_scheduled(factory, scheduled_at=past)
    redis = _RecordingRedis()
    try:
        result = await publish_due_notices({"session_factory": factory, "redis": redis})
        assert result["published"] >= 1
        # 발행된 공지마다 벡터화 인제스트가 enqueue된다(cron→ingest 연결).
        assert ("ingest_notice_task", (str(notice_id), str(tenant_id))) in redis.jobs
    finally:
        await _cleanup(factory, tenant_id)
        await engine.dispose()
