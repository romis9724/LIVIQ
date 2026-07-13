"""testcontainers 픽스처 — 실 PostgreSQL에 Alembic·RLS를 적용해 검증(docs/09 §4.2).

- 세션: pgvector:pg16 컨테이너 1회 기동 + 전체 마이그레이션(owner 접속).
- 테스트: 각 테스트를 트랜잭션으로 감싸 종료 시 롤백(컨테이너 재기동 없음).
- 시드는 owner(superuser=RLS 우회)로 먼저 넣고, 런타임 검증은 `set_context`로
  `SET LOCAL ROLE liviq_app|liviq_worker` + `app.tenant_id` 설정 후 수행한다
  (owner로 런타임 검증 금지 — superuser는 FORCE RLS도 우회하므로 격리 검증이 무의미).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

_DB_ROOT = Path(__file__).resolve().parent.parent


def _ensure_docker_host() -> None:
    """colima 사용 시 DOCKER_HOST 자동 설정(CI 리눅스 기본 소켓은 그대로 둔다)."""
    if os.environ.get("DOCKER_HOST"):
        return
    colima_sock = Path.home() / ".colima" / "default" / "docker.sock"
    if colima_sock.exists():
        os.environ["DOCKER_HOST"] = f"unix://{colima_sock}"


_ensure_docker_host()
# colima에서 Ryuk 리퍼가 소켓을 못 잡는 경우가 있어 비활성(컨테이너는 컨텍스트 종료 시 정리).
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


def _apply_migrations(dsn: str) -> None:
    os.environ["DATABASE_URL"] = dsn
    from liviq_db.config import get_settings

    get_settings.cache_clear()
    cfg = Config()
    cfg.set_main_option("script_location", str(_DB_ROOT / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        dsn = pg.get_connection_url()
        _apply_migrations(dsn)
        yield dsn


@pytest_asyncio.fixture
async def owner_conn(pg_dsn: str) -> AsyncIterator[AsyncConnection]:
    """owner 커넥션 + 테스트별 트랜잭션(종료 시 롤백). NullPool로 루프 간 커넥션 누수 방지."""
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    async with engine.connect() as conn:
        trans = await conn.begin()
        try:
            yield conn
        finally:
            await trans.rollback()
            await engine.dispose()


async def set_context(conn: AsyncConnection, role: str, tenant_id: uuid.UUID | None = None) -> None:
    """런타임 컨텍스트 진입 — SET LOCAL ROLE + app.tenant_id(트랜잭션 한정).

    tenant_id=None이면 컨텍스트 미설정(fail-closed 검증용).
    set_config(local=true)로 asyncpg의 role/GUC 바인딩 제약을 회피한다.
    """
    await conn.execute(
        text("SELECT set_config('app.tenant_id', :v, true)").bindparams(
            v=str(tenant_id) if tenant_id is not None else ""
        )
    )
    await conn.execute(text(f"SET LOCAL ROLE {role}"))


# ── 2-tenant 합성 시드 (운영 시드와 분리, docs/03 §8) ──────────────────────


@dataclass(frozen=True)
class TenantFixture:
    tenant_id: uuid.UUID
    building_id: uuid.UUID
    household_id: uuid.UUID
    user_id: uuid.UUID
    pii_id: uuid.UUID
    document_id: uuid.UUID
    inquiry_id: uuid.UUID
    audit_id: uuid.UUID
    outbox_id: uuid.UUID
    golden_id: uuid.UUID


@dataclass(frozen=True)
class Seed:
    a: TenantFixture
    b: TenantFixture
    public_golden_id: uuid.UUID


async def _scalar(conn: AsyncConnection, sql: str, **params: object) -> uuid.UUID:
    result = await conn.execute(text(sql).bindparams(**params))
    value = result.scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


async def _seed_tenant(conn: AsyncConnection, label: str) -> TenantFixture:
    tenant_id = await _scalar(
        conn,
        "INSERT INTO tenants(name, status) VALUES(:n, 'active') RETURNING id",
        n=f"tenant-{label}",
    )
    building_id = await _scalar(
        conn,
        "INSERT INTO buildings(tenant_id, name) VALUES(:t, '101') RETURNING id",
        t=tenant_id,
    )
    household_id = await _scalar(
        conn,
        "INSERT INTO households(tenant_id, building_id, floor, unit_no, status) "
        "VALUES(:t, :b, 3, 301, 'active') RETURNING id",
        t=tenant_id,
        b=building_id,
    )
    pii_id = await _scalar(
        conn,
        "INSERT INTO pii_vault(tenant_id, name_hash, phone_hash) VALUES(:t, :nh, :ph) RETURNING id",
        t=tenant_id,
        nh=f"namehash-{label}",
        ph=f"phonehash-{label}",
    )
    user_id = await _scalar(
        conn,
        "INSERT INTO users(tenant_id, household_id, status, pii_ref) "
        "VALUES(:t, :h, 'active', :p) RETURNING id",
        t=tenant_id,
        h=household_id,
        p=pii_id,
    )
    document_id = await _scalar(
        conn,
        "INSERT INTO documents(tenant_id, title, source_type, visibility, "
        "storage_key, content_hash, index_status) "
        "VALUES(:t, 'doc', '규약', 'ALL', 'k', :ch, 'pending') RETURNING id",
        t=tenant_id,
        ch=f"hash-{label}",
    )
    inquiry_id = await _scalar(
        conn,
        "INSERT INTO inquiries(tenant_id, household_id, author_user_id, title, body, status) "
        "VALUES(:t, :h, :u, 'title', 'body', 'received') RETURNING id",
        t=tenant_id,
        h=household_id,
        u=user_id,
    )
    audit_id = await _scalar(
        conn,
        "INSERT INTO audit_logs(tenant_id, action) VALUES(:t, 'login') RETURNING id",
        t=tenant_id,
    )
    outbox_id = await _scalar(
        conn,
        "INSERT INTO outbox_events(tenant_id, aggregate_type, aggregate_id, event_type, "
        "sequence, dedupe_key, status) "
        "VALUES(:t, 'facility', gen_random_uuid(), 'created', 1, :dk, 'pending') RETURNING id",
        t=tenant_id,
        dk=f"dedupe-{label}",
    )
    golden_id = await _scalar(
        conn,
        "INSERT INTO ai_eval_golden(tenant_id, question) VALUES(:t, :q) RETURNING id",
        t=tenant_id,
        q=f"q-{label}",
    )
    return TenantFixture(
        tenant_id=tenant_id,
        building_id=building_id,
        household_id=household_id,
        user_id=user_id,
        pii_id=pii_id,
        document_id=document_id,
        inquiry_id=inquiry_id,
        audit_id=audit_id,
        outbox_id=outbox_id,
        golden_id=golden_id,
    )


@pytest_asyncio.fixture
async def seed(owner_conn: AsyncConnection) -> Seed:
    """owner(superuser=RLS 우회)로 2개 단지 + 공용 골든셋 시드. 트랜잭션 종료 시 롤백."""
    a = await _seed_tenant(owner_conn, "a")
    b = await _seed_tenant(owner_conn, "b")
    public_golden_id = await _scalar(
        owner_conn,
        "INSERT INTO ai_eval_golden(tenant_id, question) VALUES(NULL, 'public') RETURNING id",
    )
    return Seed(a=a, b=b, public_golden_id=public_golden_id)
