"""실접속 롤 격리 검증 (H10-2 — docs/03 §5.1) — **CRITICAL 게이트**.

[`test_rls.py`](test_rls.py)는 owner 커넥션 + `SET LOCAL ROLE`로 **정책**을 검증한다. 정책이 맞아도
런타임이 owner(superuser)로 접속하면 2층은 죽는다(H10-1 스모크 실측) — 그 배선 회귀는 `SET ROLE`
경로로는 잡히지 않는다. 그래서 여기서는 `liviq_app`·`liviq_worker`로 **실제 접속**해 확인한다.

다른 커넥션에서 보여야 하므로 시드를 **커밋**한다(롤백 픽스처인 `owner_conn`과 다르다) — 테스트마다
넣고 지운다. 런타임 커넥션은 커밋하지 않으므로 컨텍스트 종료 시 롤백된다.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from liviq_db.runtime_roles import (
    RUNTIME_ROLE_ENV,
    RuntimeRoleError,
    assert_isolation_probe,
    assert_no_rls_bypass,
    converge_and_verify,
)

pytestmark = pytest.mark.integration

# 테스트 컨테이너 전용 비밀번호 — 컨테이너와 함께 폐기된다.
_PASSWORDS = {"liviq_app": "test-app-pw", "liviq_worker": "test-worker-pw"}


@pytest_asyncio.fixture
async def owner_engine(pg_dsn: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def seed_ids(owner_engine: AsyncEngine) -> AsyncIterator[tuple[uuid.UUID, uuid.UUID]]:
    """2개 tenant의 **커밋된** 최소 시드(tenant + building + household + user). 종료 시 삭제."""
    ids: list[uuid.UUID] = []
    async with owner_engine.begin() as conn:
        for label in ("rt-a", "rt-b"):
            tenant_id = await conn.scalar(
                text(
                    "INSERT INTO tenants(name, status) VALUES(:n, 'active') RETURNING id"
                ).bindparams(n=label)
            )
            building_id = await conn.scalar(
                text(
                    "INSERT INTO buildings(tenant_id, name) VALUES(:t, '101') RETURNING id"
                ).bindparams(t=tenant_id)
            )
            household_id = await conn.scalar(
                text(
                    "INSERT INTO households(tenant_id, building_id, floor, unit_no, status) "
                    "VALUES(:t, :b, 3, 301, 'active') RETURNING id"
                ).bindparams(t=tenant_id, b=building_id)
            )
            # users 행은 격리 프로브(PROBE_TABLE) 대상이라 함께 넣는다 — 없으면 baseline 0으로
            # 프로브가 건너뛰어져 검증이 공허해진다.
            await conn.execute(
                text(
                    "INSERT INTO users(tenant_id, household_id, status) VALUES(:t, :h, 'active')"
                ).bindparams(t=tenant_id, h=household_id)
            )
            ids.append(tenant_id)
    try:
        yield ids[0], ids[1]
    finally:
        async with owner_engine.begin() as conn:
            # 잠금 대기로 무한 정지하지 않게 상한을 둔다 — 런타임 커넥션이 먼저 닫히지 않으면
            # 이 DELETE가 FK 잠금을 기다린다(아래 app_conn 주석). 실패로 드러나야 한다.
            await conn.execute(text("SET LOCAL lock_timeout = '10s'"))
            await conn.execute(text("DELETE FROM tenants WHERE id = ANY(:ids)").bindparams(ids=ids))


@pytest_asyncio.fixture
async def runtime_urls(pg_dsn: str) -> AsyncIterator[dict[str, str]]:
    """실제 수렴 스크립트를 돌려 런타임 롤에 LOGIN을 부여하고 접속 URL을 돌려준다.

    `converge_and_verify`가 롤 속성·격리 프로브 검증까지 수행하므로, 이 픽스처가 성립한다는 것
    자체가 배포 스텝(§5.1)이 그린이라는 뜻이다.
    """
    base = make_url(pg_dsn)
    urls = {
        role: str(base.set(username=role, password=password))
        for role, password in _PASSWORDS.items()
    }
    previous = {key: os.environ.get(key) for key in RUNTIME_ROLE_ENV.values()}
    for role, env_key in RUNTIME_ROLE_ENV.items():
        os.environ[env_key] = urls[role]
    try:
        assert await converge_and_verify() == list(RUNTIME_ROLE_ENV)
        yield urls
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# 런타임 커넥션 픽스처는 `seed_ids`를 **의존으로 받는다** — 실행 순서가 아니라 정리 순서 때문이다.
# 런타임 커넥션이 살아 있는 동안 tenants 행에 FK 잠금(FOR KEY SHARE)이 걸리므로, 시드 삭제가
# 먼저 돌면 그 DELETE가 잠금 대기로 멈춘다(실측: 테스트가 무한 대기). 의존을 주면 커넥션이
# 먼저 닫히고(롤백=잠금 해제) 그 다음 삭제가 돈다.
@pytest_asyncio.fixture
async def app_conn(
    runtime_urls: dict[str, str], seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> AsyncIterator[AsyncConnection]:
    """`liviq_app` 실접속. 커밋하지 않으므로 종료 시 롤백."""
    engine = create_async_engine(runtime_urls["liviq_app"], poolclass=NullPool)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


@pytest_asyncio.fixture
async def worker_conn(
    runtime_urls: dict[str, str], seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(runtime_urls["liviq_worker"], poolclass=NullPool)
    async with engine.connect() as conn:
        yield conn
    await engine.dispose()


async def _set_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> None:
    await conn.execute(
        text("SELECT set_config('app.tenant_id', :v, false)").bindparams(v=str(tenant_id))
    )


# ── 접속 롤 속성 ───────────────────────────────────────────────────────────


async def test_app_role_has_no_rls_bypass(app_conn: AsyncConnection) -> None:
    """2층 성립의 필요조건 — 접속 롤이 superuser·BYPASSRLS가 아니다."""
    await assert_no_rls_bypass(app_conn)


async def test_worker_role_has_no_rls_bypass(worker_conn: AsyncConnection) -> None:
    await assert_no_rls_bypass(worker_conn)


async def test_owner_connection_is_rejected(
    owner_engine: AsyncEngine, seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """owner(superuser) 접속은 롤 검사·프로브 양쪽에서 거부 — 배포 회귀 탐지 경로.

    프로브가 의미를 가지려면 실제 행이 있어야 하므로 커밋된 시드를 함께 쓴다.
    """
    async with owner_engine.connect() as conn:
        with pytest.raises(RuntimeRoleError, match="RLS를 우회"):
            await assert_no_rls_bypass(conn)
        with pytest.raises(RuntimeRoleError, match="컨텍스트 없이"):
            await assert_isolation_probe(conn, baseline_rows=1)


async def test_isolation_probe_skips_empty_db(app_conn: AsyncConnection) -> None:
    """baseline 0(빈 DB)에서는 프로브가 무의미하므로 통과 — 롤 속성 검사가 게이트."""
    await assert_isolation_probe(app_conn, baseline_rows=0)


# ── 실접속 롤의 tenant 격리 ────────────────────────────────────────────────


async def test_app_sees_nothing_without_tenant_context(
    app_conn: AsyncConnection, seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """컨텍스트 미설정 = fail-closed. 시드는 커밋돼 있으므로 owner라면 보였을 것."""
    assert await app_conn.scalar(text("SELECT count(*) FROM households")) == 0


async def test_app_sees_only_own_tenant(
    app_conn: AsyncConnection, seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    tenant_a, tenant_b = seed_ids
    await _set_tenant(app_conn, tenant_a)
    rows = (await app_conn.execute(text("SELECT tenant_id FROM households"))).scalars().all()
    assert set(rows) == {tenant_a}
    assert tenant_b not in rows


async def test_app_cannot_write_into_other_tenant(
    app_conn: AsyncConnection, seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """WITH CHECK — 컨텍스트 밖 tenant로 쓰기 불가(실접속 롤에서 확인)."""
    tenant_a, tenant_b = seed_ids
    await _set_tenant(app_conn, tenant_a)
    building_a = await app_conn.scalar(text("SELECT id FROM buildings"))
    assert building_a is not None  # A의 동만 보인다
    with pytest.raises(DBAPIError):
        await app_conn.execute(
            text(
                "INSERT INTO households(tenant_id, building_id, floor, unit_no, status) "
                "VALUES(:t, :b, 9, 901, 'active')"
            ).bindparams(t=tenant_b, b=building_a)
        )


async def test_app_can_manage_tenants(app_conn: AsyncConnection) -> None:
    """`tenants` INSERT·UPDATE·DELETE GRANT(마이그레이션 f1a9c3e5b7d2) — SYS_ADMIN 단지 관리 경로.

    `tenants`는 RLS 예외라 권한만이 방어선이고, owner 접속에선 누락이 드러나지 않는다. DELETE는
    라이브 여정에서 빈 단지 삭제가 `permission denied`로 깨져서 뒤늦게 추가했다 — 그래서 여기서
    3연산을 모두 건다.
    """
    tenant_id = await app_conn.scalar(
        text("INSERT INTO tenants(name, status) VALUES('rt-grant', 'active') RETURNING id")
    )
    await app_conn.execute(
        text("UPDATE tenants SET status = 'inactive' WHERE id = :i").bindparams(i=tenant_id)
    )
    assert (
        await app_conn.scalar(
            text("SELECT status FROM tenants WHERE id = :i").bindparams(i=tenant_id)
        )
        == "inactive"
    )
    # 빈 단지 삭제(`DELETE /admin/tenants/{id}`) — 계정이 있는 단지는 라우터가 409로 막는다.
    await app_conn.execute(text("DELETE FROM tenants WHERE id = :i").bindparams(i=tenant_id))
    assert (
        await app_conn.scalar(
            text("SELECT count(*) FROM tenants WHERE id = :i").bindparams(i=tenant_id)
        )
        == 0
    )


# ── 워커 롤: 큐만 cross-tenant ─────────────────────────────────────────────


async def test_worker_reads_queue_cross_tenant(
    worker_conn: AsyncConnection, seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """`worker_queue_access` 정책이 **실접속 롤**에도 적용된다(정책 `TO liviq_worker`)."""
    tenant_a, tenant_b = seed_ids
    for index, tenant_id in enumerate((tenant_a, tenant_b)):
        await worker_conn.execute(
            text(
                "INSERT INTO outbox_events"
                "(tenant_id, aggregate_type, aggregate_id, event_type, sequence, "
                " dedupe_key, payload, status) "
                "VALUES(:t, 'facility', gen_random_uuid(), 'rt.probe', 1, :k, '{}'::jsonb, "
                "'pending')"
            ).bindparams(t=tenant_id, k=f"rt-probe-{index}")
        )
    rows = (
        (
            await worker_conn.execute(
                text("SELECT tenant_id FROM outbox_events WHERE event_type = 'rt.probe'")
            )
        )
        .scalars()
        .all()
    )
    assert set(rows) == {tenant_a, tenant_b}


async def test_worker_domain_needs_tenant_context(
    worker_conn: AsyncConnection, seed_ids: tuple[uuid.UUID, uuid.UUID]
) -> None:
    """도메인 테이블은 큐와 다르다 — 컨텍스트 없이는 0행."""
    assert await worker_conn.scalar(text("SELECT count(*) FROM documents")) == 0
