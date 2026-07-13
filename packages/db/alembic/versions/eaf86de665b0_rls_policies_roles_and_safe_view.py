"""rls policies roles and safe view

RLS·role·뷰는 스키마 autogenerate 대상이 아니라 custom migration(op.execute)으로
버전관리한다(docs/03 §5·6, docs/09 §2.1). 초기 스키마(d5422d3f35d5)는 손대지 않는다.

Revision ID: eaf86de665b0
Revises: d5422d3f35d5
Create Date: 2026-07-13 20:54:41.430394
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "eaf86de665b0"
down_revision: str | None = "d5422d3f35d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── 테이블 분류 (docs/03 §5, 순서 결정적 = 재실행 diff 안정) ──────────────
# 표준 tenant 격리(tenant_id = app.tenant_id)를 받는 업무 테이블.
# audit_logs·jobs·outbox_events 포함(격리 정책은 동일, 추가 규율은 별도).
STANDARD_ISOLATION_TABLES = (
    "ai_feedback",
    "audit_logs",
    "buildings",
    "citations",
    "consents",
    "conversations",
    "document_chunks",
    "documents",
    "excel_uploads",
    "facilities",
    "fees",
    "floor_plans",
    "households",
    "incidents",
    "inquiries",
    "inquiry_categories",
    "jobs",
    "maintenance_logs",
    "messages",
    "notice_drafts",
    "notices",
    "notifications",
    "outbox_events",
    "pii_vault",
    "plan_devices",
    "unit_types",
    "user_roles",
    "users",
)
# tenant_id NULL(공용 골든셋) 허용 — 자기 단지 OR 공용만 열람(docs/03 §5 표).
NULLABLE_TENANT_TABLE = "ai_eval_golden"
# 워커가 cross-tenant로 폴링·claim 하는 큐 테이블(도메인 아님).
WORKER_QUEUE_TABLES = ("jobs", "outbox_events")
# append-only — INSERT·SELECT만 GRANT(권한으로 수정·삭제 차단, docs/03 §4.7).
APPEND_ONLY_TABLE = "audit_logs"
# 워커가 tenant 컨텍스트 하에서 반영하는 도메인 테이블(ingest·Neo4j 동기화).
WORKER_DOMAIN_TABLES = (
    "document_chunks",
    "documents",
    "facilities",
    "incidents",
    "maintenance_logs",
    "plan_devices",
)
# RLS enable/force 대상 = tenants(멤버십 인가는 앱 소관) 외 전부.
RLS_TABLES = (*STANDARD_ISOLATION_TABLES, NULLABLE_TENANT_TABLE)

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def _create_roles() -> None:
    """런타임 role 2개 — LOGIN·비밀번호·BYPASSRLS 없음(FORCE RLS로 owner도 격리).

    role은 클러스터 전역이라 IF NOT EXISTS 가드로 멱등 생성. 운영에선 로그인
    유저가 이 role을 상속(GRANT ... TO login_user)해 사용한다(시크릿은 여기 없음).
    """
    for role in ("liviq_app", "liviq_worker"):
        op.execute(
            f"DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}') THEN "
            f"CREATE ROLE {role} NOLOGIN NOBYPASSRLS; "
            f"END IF; END $$;"
        )


def _enable_rls_and_policies() -> None:
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # 표준 격리: 컨텍스트 미설정 시 NULL → 거짓 → 읽기·쓰기 모두 fail-closed.
    for table in STANDARD_ISOLATION_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
            f"USING (tenant_id = {_CURRENT_TENANT}) "
            f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
        )

    # 공용 골든셋: 자기 단지 OR tenant_id IS NULL.
    op.execute(
        f"CREATE POLICY tenant_or_public ON {NULLABLE_TENANT_TABLE} FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT} OR tenant_id IS NULL) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT} OR tenant_id IS NULL)"
    )

    # 워커 전용 cross-tenant 큐 접근(permissive OR — liviq_worker에게만).
    for table in WORKER_QUEUE_TABLES:
        op.execute(
            f"CREATE POLICY worker_queue_access ON {table} FOR ALL "
            f"TO liviq_worker USING (true) WITH CHECK (true)"
        )


def _grants() -> None:
    op.execute("GRANT USAGE ON SCHEMA public TO liviq_app, liviq_worker")

    # liviq_app: 업무 테이블 전 DML. audit_logs·ai_eval_golden·tenants는 예외.
    for table in STANDARD_ISOLATION_TABLES:
        if table == APPEND_ONLY_TABLE:
            op.execute(f"GRANT SELECT, INSERT ON {table} TO liviq_app")
        else:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO liviq_app")
    # 골든셋은 읽기만(작성은 ops 도구·시드 소관), tenants는 멤버십 조회용 읽기.
    op.execute(f"GRANT SELECT ON {NULLABLE_TENANT_TABLE} TO liviq_app")
    op.execute("GRANT SELECT ON tenants TO liviq_app")

    # liviq_worker: 큐 전체 + 도메인은 RLS 하 최소(SELECT/INSERT/UPDATE).
    for table in WORKER_QUEUE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO liviq_worker")
    for table in WORKER_DOMAIN_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO liviq_worker")


def _create_safe_view() -> None:
    """비식별 컬럼 + 검색 해시만 노출(평문·복호화 없음, docs/03 §6).

    security_invoker=true(PG15+): 뷰 소유자가 아니라 호출자 권한·RLS로 평가 →
    뷰가 tenant 격리를 우회하지 못한다.
    """
    op.execute(
        "CREATE VIEW v_users_safe WITH (security_invoker = true) AS "
        "SELECT u.id, u.tenant_id, u.household_id, u.status, u.roster_matched, "
        "p.name_hash, p.phone_hash "
        "FROM users u LEFT JOIN pii_vault p ON p.id = u.pii_ref"
    )
    op.execute("GRANT SELECT ON v_users_safe TO liviq_app")


def upgrade() -> None:
    _create_roles()
    _enable_rls_and_policies()
    _grants()
    _create_safe_view()


def downgrade() -> None:
    # role은 클러스터 전역이라 남긴다(다른 DB가 참조할 수 있음) — 정책·GRANT·뷰만 원복.
    op.execute("DROP VIEW IF EXISTS v_users_safe")

    for table in WORKER_QUEUE_TABLES:
        op.execute(f"DROP POLICY IF EXISTS worker_queue_access ON {table}")
    op.execute(f"DROP POLICY IF EXISTS tenant_or_public ON {NULLABLE_TENANT_TABLE}")
    for table in STANDARD_ISOLATION_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    # GRANT 원복(role은 유지되므로 재upgrade가 깨끗하도록 revoke).
    op.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM liviq_app, liviq_worker")
    op.execute("REVOKE USAGE ON SCHEMA public FROM liviq_app, liviq_worker")
