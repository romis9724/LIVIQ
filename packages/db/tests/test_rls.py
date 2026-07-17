"""RLS CRITICAL 스위트 — 실 PostgreSQL에서 tenant 격리·fail-closed·권한을 증명(docs/03 §5·6).

owner(superuser)로 시드 후 `set_context`로 런타임 role 전환해 검증한다.
실패를 기대하는 쿼리는 SAVEPOINT로 감싸 바깥 트랜잭션을 살려둔다.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from conftest import Seed, set_context
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

pytestmark = pytest.mark.integration


async def _count(conn: AsyncConnection, table: str) -> int:
    value = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
    return int(value)


async def _assert_denied(
    conn: AsyncConnection,
    action: Callable[[], Awaitable[object]],
    *,
    expected: type[Exception] = DBAPIError,
) -> None:
    """SAVEPOINT로 감싸 실패를 기대 — 바깥 트랜잭션은 계속 사용 가능하게 롤백."""
    savepoint = await conn.begin_nested()
    try:
        with pytest.raises(expected):
            await action()
    finally:
        await savepoint.rollback()


# ── tenant 격리: 읽기 ──────────────────────────────────────────────────────


async def test_tenant_a_reads_only_own_documents(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn, "documents") == 1
    row = (
        await owner_conn.execute(
            text("SELECT id FROM documents WHERE id = :i").bindparams(i=seed.b.document_id)
        )
    ).first()
    assert row is None, "B 단지 문서가 A 컨텍스트에서 노출됨(격리 실패)"


async def test_tenant_a_reads_only_own_inquiries(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn, "inquiries") == 1
    row = (
        await owner_conn.execute(
            text("SELECT id FROM inquiries WHERE id = :i").bindparams(i=seed.b.inquiry_id)
        )
    ).first()
    assert row is None, "B 단지 민원이 A 컨텍스트에서 노출됨(격리 실패)"


# ── tenant 격리: 쓰기(WITH CHECK) ─────────────────────────────────────────


async def test_insert_with_other_tenant_id_is_rejected(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    async def insert_b_document() -> object:
        return await owner_conn.execute(
            text(
                "INSERT INTO documents(tenant_id, title, source_type, visibility, "
                "storage_key, content_hash, index_status) "
                "VALUES(:t, 'x', '규약', 'ALL', 'k', 'other', 'pending')"
            ).bindparams(t=seed.b.tenant_id)
        )

    await _assert_denied(owner_conn, insert_b_document)


# ── fail-closed: 컨텍스트 미설정 ──────────────────────────────────────────


async def test_no_context_reads_zero_rows(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", tenant_id=None)

    assert await _count(owner_conn, "documents") == 0
    assert await _count(owner_conn, "inquiries") == 0


async def test_no_context_insert_is_rejected(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", tenant_id=None)

    async def insert_a_document() -> object:
        return await owner_conn.execute(
            text(
                "INSERT INTO documents(tenant_id, title, source_type, visibility, "
                "storage_key, content_hash, index_status) "
                "VALUES(:t, 'x', '규약', 'ALL', 'k', 'nocontext', 'pending')"
            ).bindparams(t=seed.a.tenant_id)
        )

    await _assert_denied(owner_conn, insert_a_document)


# ── composite FK cross-tenant 차단 ────────────────────────────────────────


async def test_composite_fk_blocks_cross_tenant_parent(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """A 컨텍스트에서 B 소속 세대를 참조하는 민원 INSERT → composite FK 위반."""
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    async def insert_child_referencing_b() -> object:
        return await owner_conn.execute(
            text(
                "INSERT INTO inquiries"
                "(tenant_id, household_id, author_user_id, title, body, status) "
                "VALUES(:t, :h, :u, 't', 'b', 'received')"
            ).bindparams(t=seed.a.tenant_id, h=seed.b.household_id, u=seed.a.user_id)
        )

    await _assert_denied(owner_conn, insert_child_referencing_b, expected=IntegrityError)


# ── audit_logs append-only(권한으로 강제) ─────────────────────────────────


async def test_audit_logs_update_denied(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    async def update_audit() -> object:
        return await owner_conn.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :i").bindparams(
                i=seed.a.audit_id
            )
        )

    await _assert_denied(owner_conn, update_audit)


async def test_audit_logs_delete_denied(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    async def delete_audit() -> object:
        return await owner_conn.execute(
            text("DELETE FROM audit_logs WHERE id = :i").bindparams(i=seed.a.audit_id)
        )

    await _assert_denied(owner_conn, delete_audit)


async def test_audit_logs_insert_allowed(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    result = await owner_conn.execute(
        text("INSERT INTO audit_logs(tenant_id, action) VALUES(:t, 'note')").bindparams(
            t=seed.a.tenant_id
        )
    )
    assert result.rowcount == 1


# ── 워커 role: 큐 cross-tenant, 도메인은 컨텍스트 필요 ────────────────────


async def test_worker_reads_queue_without_context(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_worker", tenant_id=None)

    assert await _count(owner_conn, "outbox_events") == 2, "워커는 큐를 cross-tenant로 폴링"


async def test_worker_can_claim_queue_event(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_worker", tenant_id=None)

    result = await owner_conn.execute(
        text("UPDATE outbox_events SET status = 'processed' WHERE id = :i").bindparams(
            i=seed.a.outbox_id
        )
    )
    assert result.rowcount == 1


async def test_worker_domain_table_blocked_without_context(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    await set_context(owner_conn, "liviq_worker", tenant_id=None)

    # 컨텍스트 없으면 도메인 테이블은 fail-closed(행 0).
    assert await _count(owner_conn, "documents") == 0

    async def insert_document() -> object:
        return await owner_conn.execute(
            text(
                "INSERT INTO documents(tenant_id, title, source_type, visibility, "
                "storage_key, content_hash, index_status) "
                "VALUES(:t, 'x', '규약', 'ALL', 'k', 'worker', 'pending')"
            ).bindparams(t=seed.a.tenant_id)
        )

    await _assert_denied(owner_conn, insert_document)


# ── ai_eval_golden: 공용 + 자기 단지만 ────────────────────────────────────


async def test_golden_reads_public_and_own_only(owner_conn: AsyncConnection, seed: Seed) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    visible = {
        r[0] for r in (await owner_conn.execute(text("SELECT id FROM ai_eval_golden"))).all()
    }
    assert seed.public_golden_id in visible, "공용(NULL) 골든셋이 안 읽힘"
    assert seed.a.golden_id in visible, "자기 단지 골든셋이 안 읽힘"
    assert seed.b.golden_id not in visible, "타 단지 골든셋이 노출됨(격리 실패)"


# ── v_users_safe 뷰: 비식별 컬럼만 + tenant 격리 ─────────────────────────


async def test_v_users_safe_exposes_no_plaintext_pii(
    owner_conn: AsyncConnection,
) -> None:
    columns = {
        r[0]
        for r in (
            await owner_conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'v_users_safe'"
                )
            )
        ).all()
    }
    assert columns == {
        "id",
        "tenant_id",
        "household_id",
        "status",
        "roster_matched",
        "name_hash",
        "phone_hash",
    }
    assert not any("enc" in c for c in columns), "암호화 원문 컬럼이 뷰에 노출됨"


async def test_v_users_safe_enforces_tenant_isolation(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    rows = (await owner_conn.execute(text("SELECT id, name_hash FROM v_users_safe"))).all()
    assert len(rows) == 1, "security_invoker 뷰가 tenant 격리를 우회함"
    assert rows[0][0] == seed.a.user_id


# ── users auth_lookup 정책: 콜백 전역 조회(SELECT 전용, docs/03 §5) ────────


async def _set_auth_lookup(conn: AsyncConnection, role: str) -> None:
    """auth_lookup 플래그 ON + role 전환(tenant 미설정 — 전역 조회 컨텍스트)."""
    await conn.execute(text("SELECT set_config('app.auth_lookup', 'on', true)"))
    await conn.execute(text(f"SET LOCAL ROLE {role}"))


async def test_users_lookup_denied_without_auth_lookup_flag(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """플래그 없이 tenant 컨텍스트도 없으면 users 조회 0행(fail-closed)."""
    await set_context(owner_conn, "liviq_app", tenant_id=None)

    assert await _count(owner_conn, "users") == 0


async def test_users_lookup_visible_with_auth_lookup_flag(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """auth_lookup='on'이면 tenant 무관 전역 SELECT(콜백 login_id 조회)."""
    await _set_auth_lookup(owner_conn, "liviq_app")

    assert await _count(owner_conn, "users") == 2, "auth_lookup 플래그로 전역 조회가 안 됨"


async def test_auth_lookup_flag_does_not_enable_writes(
    owner_conn: AsyncConnection, seed: Seed
) -> None:
    """auth_lookup은 FOR SELECT — 플래그가 있어도 쓰기는 불가(CRITICAL)."""
    await _set_auth_lookup(owner_conn, "liviq_app")

    async def insert_user() -> object:
        return await owner_conn.execute(
            text("INSERT INTO users(tenant_id, status) VALUES(:t, 'active')").bindparams(
                t=seed.a.tenant_id
            )
        )

    # INSERT는 tenant_isolation WITH CHECK만 평가(tenant 미설정) → RLS 위반.
    await _assert_denied(owner_conn, insert_user)

    # UPDATE는 tenant_isolation USING만 평가(tenant 미설정) → 대상 행 0(쓰기 불가).
    result = await owner_conn.execute(
        text("UPDATE users SET status = 'tampered' WHERE id = :i").bindparams(i=seed.a.user_id)
    )
    assert result.rowcount == 0, "auth_lookup 플래그로 UPDATE가 새어나감"


# ── tenant_keys: DEK 격리 + append-only(권한으로 강제, ADR-0010) ──────────


async def _seed_tenant_key(conn: AsyncConnection, tenant_id: object, label: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO tenant_keys(tenant_id, key_version, dek_wrapped) VALUES(:t, 1, :d)"
        ).bindparams(t=tenant_id, d=f"wrapped-{label}".encode())
    )


async def test_tenant_keys_isolation(owner_conn: AsyncConnection, seed: Seed) -> None:
    """단지 A는 자기 DEK만 — B의 키는 안 보인다(격리)."""
    await _seed_tenant_key(owner_conn, seed.a.tenant_id, "a")
    await _seed_tenant_key(owner_conn, seed.b.tenant_id, "b")
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn, "tenant_keys") == 1, "타 단지 DEK가 노출됨(격리 실패)"


async def test_tenant_keys_update_denied(owner_conn: AsyncConnection, seed: Seed) -> None:
    """키는 append-only — liviq_app에 UPDATE 권한 없음(회전은 새 버전 INSERT)."""
    await _seed_tenant_key(owner_conn, seed.a.tenant_id, "a")
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    async def update_key() -> object:
        return await owner_conn.execute(
            text("UPDATE tenant_keys SET key_version = 2 WHERE tenant_id = :t").bindparams(
                t=seed.a.tenant_id
            )
        )

    await _assert_denied(owner_conn, update_key)


async def test_tenant_keys_delete_denied(owner_conn: AsyncConnection, seed: Seed) -> None:
    """키 삭제 금지 — 복호 불능 방지(liviq_app에 DELETE 권한 없음)."""
    await _seed_tenant_key(owner_conn, seed.a.tenant_id, "a")
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    async def delete_key() -> object:
        return await owner_conn.execute(
            text("DELETE FROM tenant_keys WHERE tenant_id = :t").bindparams(t=seed.a.tenant_id)
        )

    await _assert_denied(owner_conn, delete_key)


async def test_tenant_keys_insert_allowed(owner_conn: AsyncConnection, seed: Seed) -> None:
    """자기 단지 키 INSERT는 허용(회전 = 새 버전 append)."""
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    result = await owner_conn.execute(
        text(
            "INSERT INTO tenant_keys(tenant_id, key_version, dek_wrapped) VALUES(:t, 1, :d)"
        ).bindparams(t=seed.a.tenant_id, d=b"wrapped-app")
    )
    assert result.rowcount == 1


# ── inquiry_events: tenant 격리 + append-only(권한으로 강제, docs/03 §4.4) ──


async def _seed_inquiry_event(conn: AsyncConnection, tf: object) -> None:
    fixture = tf  # TenantFixture — tenant_id·inquiry_id 사용
    await conn.execute(
        text(
            "INSERT INTO inquiry_events(tenant_id, inquiry_id, type, payload) "
            "VALUES(:t, :i, 'created', '{}'::jsonb)"
        ).bindparams(t=fixture.tenant_id, i=fixture.inquiry_id)  # type: ignore[attr-defined]
    )


async def test_inquiry_events_tenant_isolation(owner_conn: AsyncConnection, seed: Seed) -> None:
    """A는 자기 민원 타임라인만 — B의 이벤트는 안 보인다(격리)."""
    await _seed_inquiry_event(owner_conn, seed.a)
    await _seed_inquiry_event(owner_conn, seed.b)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    assert await _count(owner_conn, "inquiry_events") == 1, "타 단지 민원 이벤트가 노출됨"


async def test_inquiry_events_update_denied(owner_conn: AsyncConnection, seed: Seed) -> None:
    """타임라인은 append-only — liviq_app에 UPDATE 권한 없음(§4.4)."""
    await _seed_inquiry_event(owner_conn, seed.a)
    await set_context(owner_conn, "liviq_app", seed.a.tenant_id)

    async def update_event() -> object:
        return await owner_conn.execute(
            text("UPDATE inquiry_events SET type = 'tampered' WHERE tenant_id = :t").bindparams(
                t=seed.a.tenant_id
            )
        )

    await _assert_denied(owner_conn, update_event)
