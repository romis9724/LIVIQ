"""예약 공지 발행 cron — scheduled_at 도달 공지를 published로 전이 + 알림 (H8-1, ADR-0015).

`ai-worker`가 1분 주기로 `status='scheduled' AND scheduled_at<=now() AND deleted_at IS NULL`
공지를 cross-tenant로 스캔한다(worker role의 worker_scheduled_scan 정책 — docs/03 §5). 각
공지는 그 `tenant_id`로 `SET LOCAL app.tenant_id` 후 published 전이·알림 생성(BYPASSRLS
없이 RLS를 그대로 받는다 — graph-sync 선례). 서로 다른 tenant를 한 트랜잭션에서 처리하므로
tenant 전환 전 반드시 flush해 이전 tenant 컨텍스트로 쓰기를 확정한다.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from sqlalchemy import select, text

from liviq_db.models import Notice, Notification, User

BATCH_SIZE = 200


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


async def _notify_active_users(session: Any, tenant_id: Any, notice: Notice) -> None:
    """단지 전 active 사용자에게 인앱 알림 생성(외부 자동발송 아님, ADR-0012).

    원본: apps/api/app/routers/notices.py::_notify_notice_published.
    패키지 경계(api app 미임포트)로 최소 중복 — 로직 변경 시 두 곳을 함께 갱신(ADR-0015).
    """
    user_ids = await session.scalars(
        select(User.id).where(User.tenant_id == tenant_id, User.status == "active")
    )
    for user_id in user_ids:
        session.add(
            Notification(
                tenant_id=tenant_id,
                user_id=user_id,
                type="notice",
                title=notice.title,
                link=f"/notices/{notice.id}",
            )
        )


async def publish_due_notices(ctx: dict[str, Any]) -> dict[str, int]:
    """도달한 예약 공지를 발행 + 대상자 알림. arq cron(1분)이 호출."""
    session_factory = ctx["session_factory"]
    now = _now()
    ingest_targets: list[tuple[uuid.UUID, uuid.UUID]] = []

    async with session_factory() as session, session.begin():
        # worker_scheduled_scan 정책으로 tenant 컨텍스트 없이 scheduled 공지만 cross-tenant 스캔.
        due = (
            await session.scalars(
                select(Notice)
                .where(
                    Notice.status == "scheduled",
                    Notice.scheduled_at <= now,
                    Notice.deleted_at.is_(None),
                )
                .order_by(Notice.tenant_id, Notice.scheduled_at)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()

        for notice in due:
            # 도메인 쓰기는 해당 tenant 컨텍스트로 — 전환 전 이전 tenant 쓰기를 flush로 확정.
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(
                    t=str(notice.tenant_id)
                )
            )
            notice.status = "published"
            notice.published_at = now
            await _notify_active_users(session, notice.tenant_id, notice)
            await session.flush()
            ingest_targets.append((notice.id, notice.tenant_id))

    # 발행 커밋 후 벡터화 인제스트를 enqueue한다(H8-3) — 발행이 커밋된 뒤여야 잡이 published
    # 공지를 읽는다. arq는 ctx["redis"]로 풀을 주입(테스트 ctx엔 없을 수 있음 → fail-open).
    redis = ctx.get("redis")
    if redis is not None:
        for notice_id, tenant_id in ingest_targets:
            await redis.enqueue_job("ingest_notice_task", str(notice_id), str(tenant_id))

    return {"published": len(ingest_targets)}
