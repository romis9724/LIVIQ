"""incidents.caused_by_incident_id — 다단계 인과 self-FK (GraphRAG G1a, SEED-PLAN §1).

컬럼 존재·nullable·자기참조·tenant 스코프를 실 PostgreSQL로 검증한다. composite FK라
같은 단지의 incident만 원인으로 가리킬 수 있어야 하고(규칙 3 격리), 다른 단지 incident를
가리키면 DB가 거부해야 한다.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from conftest import Seed
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

_DB_ROOT = Path(__file__).resolve().parent.parent
# a3b4c5d6e7f8(incident_caused_by)의 down_revision — 왕복 대상 하한.
_CAUSED_BY_PARENT = "f1a2b3c4d5e6"


async def _insert_facility(conn: AsyncConnection, tenant_id: uuid.UUID) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO facilities(tenant_id, name, status) "
            "VALUES(:t, '부스터펌프', 'normal') RETURNING id"
        ).bindparams(t=tenant_id)
    )
    return result.scalar_one()


async def _insert_incident(
    conn: AsyncConnection,
    tenant_id: uuid.UUID,
    facility_id: uuid.UUID,
    *,
    caused_by: uuid.UUID | None = None,
) -> uuid.UUID:
    result = await conn.execute(
        text(
            "INSERT INTO incidents(tenant_id, facility_id, symptom, caused_by_incident_id) "
            "VALUES(:t, :f, '진동 증가', :c) RETURNING id"
        ).bindparams(t=tenant_id, f=facility_id, c=caused_by)
    )
    return result.scalar_one()


async def test_caused_by_links_same_tenant_incident(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """같은 단지 incident를 원인으로 가리키는 self-FK가 성립한다."""
    facility = await _insert_facility(owner_conn, seed.a.tenant_id)
    cause = await _insert_incident(owner_conn, seed.a.tenant_id, facility)
    effect = await _insert_incident(owner_conn, seed.a.tenant_id, facility, caused_by=cause)

    linked = await owner_conn.scalar(
        text("SELECT caused_by_incident_id FROM incidents WHERE id = :i").bindparams(i=effect)
    )
    assert linked == cause


async def test_caused_by_defaults_null(owner_conn: AsyncConnection, seed: Seed) -> None:
    """선행 원인 없는 단독 장애는 caused_by_incident_id=NULL(nullable 근거)."""
    facility = await _insert_facility(owner_conn, seed.a.tenant_id)
    incident = await _insert_incident(owner_conn, seed.a.tenant_id, facility)

    linked = await owner_conn.scalar(
        text("SELECT caused_by_incident_id FROM incidents WHERE id = :i").bindparams(i=incident)
    )
    assert linked is None


async def test_caused_by_cross_tenant_is_rejected(owner_conn: AsyncConnection, seed: Seed) -> None:
    """다른 단지 incident를 원인으로 가리키면 composite FK가 거부한다(규칙 3 격리)."""
    facility_a = await _insert_facility(owner_conn, seed.a.tenant_id)
    cause_a = await _insert_incident(owner_conn, seed.a.tenant_id, facility_a)
    facility_b = await _insert_facility(owner_conn, seed.b.tenant_id)

    with pytest.raises(IntegrityError):  # savepoint로 바깥 트랜잭션(롤백 픽스처)은 보존
        async with owner_conn.begin_nested():
            await _insert_incident(owner_conn, seed.b.tenant_id, facility_b, caused_by=cause_a)


async def _caused_by_column_exists(dsn: str) -> bool:
    engine = create_async_engine(dsn, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            return bool(
                await conn.scalar(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'incidents' "
                        "AND column_name = 'caused_by_incident_id'"
                    )
                )
            )
    finally:
        await engine.dispose()


def test_caused_by_migration_roundtrip(pg_dsn: str) -> None:
    """downgrade → upgrade 왕복. 세션 공용 DB라 반드시 head로 되돌린다."""
    os.environ["DATABASE_URL"] = pg_dsn
    cfg = Config()
    cfg.set_main_option("script_location", str(_DB_ROOT / "alembic"))
    try:
        command.downgrade(cfg, _CAUSED_BY_PARENT)
        assert not asyncio.run(_caused_by_column_exists(pg_dsn))
    finally:
        command.upgrade(cfg, "head")
    assert asyncio.run(_caused_by_column_exists(pg_dsn))
