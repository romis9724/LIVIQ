"""notice board — drop notice_drafts, add pinned + notice_attachments (H8-1, ADR-0015)

공지 AI 초안 폐기·일반 게시판 전환. 스키마(add_column·create_table·drop_table)와
RLS·GRANT(op.execute)를 한 마이그레이션에 둔다(RLS/role은 autogenerate 대상 아님 —
c1a2b3d4e5f6 스타일 준수, docs/03 §5).

- notices: status 'retracted'|'superseded' 행을 published+soft delete로 이관(신 상태
  집합 draft|scheduled|published과 정합). status는 DB CHECK 없이 String — 검증은 Pydantic
  Literal이 소유(초기 스키마와 동일 방식 유지)이라 제약 ALTER 불필요.
- notices.pinned 추가(상단 고정).
- notice_drafts DROP(파일럿 초안 데이터 폐기, ADR-0015). 정책·GRANT는 테이블과 함께 소멸.
- notice_attachments CREATE + 표준 tenant 격리 RLS + composite tenant FK(CASCADE).
- 예약 발행 cron(ai-worker)용 worker role 확장: scheduled 공지 cross-tenant SELECT +
  tenant 컨텍스트 하 notices UPDATE·users SELECT·notifications INSERT(발행 전이+알림).

Revision ID: e8b1c4d09a2f
Revises: b2c3d4e5f6a7
Create Date: 2026-07-22 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e8b1c4d09a2f"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT_TENANT = "nullif(current_setting('app.tenant_id', true), '')::uuid"


def _create_notice_attachments() -> None:
    op.create_table(
        "notice_attachments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("notice_id", sa.UUID(), nullable=False),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("content_type", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_notice_attachments_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "notice_id"],
            ["notices.tenant_id", "notices.id"],
            name="fk_notice_attachments_notice",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notice_attachments")),
    )
    op.create_index(
        "ix_notice_attachments_tenant_notice",
        "notice_attachments",
        ["tenant_id", "notice_id"],
        unique=False,
    )
    op.execute("ALTER TABLE notice_attachments ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notice_attachments FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON notice_attachments FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    # 첨부는 생성·조회·삭제만(불변 메타 — UPDATE 없음).
    op.execute("GRANT SELECT, INSERT, DELETE ON notice_attachments TO liviq_app")


def _grant_worker_notice_publish() -> None:
    """예약 발행 cron: worker가 scheduled 공지를 cross-tenant로 스캔 후 tenant 컨텍스트로 전이.

    worker_scheduled_scan(permissive SELECT)은 status='scheduled' 미삭제 행만 cross-tenant로
    노출한다(발행 전 운영자 작성물, PII 없음). 전이(UPDATE)·알림(users SELECT·notifications
    INSERT)은 표준 tenant_isolation을 그대로 받아 tenant SET LOCAL 후에만 성립(docs/03 §5).
    """
    op.execute(
        "CREATE POLICY worker_scheduled_scan ON notices FOR SELECT TO liviq_worker "
        "USING (status = 'scheduled' AND deleted_at IS NULL)"
    )
    op.execute("GRANT SELECT, UPDATE ON notices TO liviq_worker")
    op.execute("GRANT SELECT ON users TO liviq_worker")
    op.execute("GRANT INSERT ON notifications TO liviq_worker")


def upgrade() -> None:
    # retracted|superseded → published + soft delete(신 상태 집합과 정합). CHECK 제약 없음.
    op.execute(
        "UPDATE notices SET status = 'published', deleted_at = now() "
        "WHERE status IN ('retracted', 'superseded')"
    )
    op.add_column(
        "notices",
        sa.Column("pinned", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    # 초안 자산 폐기(정책·GRANT·FK는 테이블과 함께 소멸).
    op.drop_table("notice_drafts")

    _create_notice_attachments()
    _grant_worker_notice_publish()


def downgrade() -> None:
    # worker 확장 원복.
    op.execute("REVOKE INSERT ON notifications FROM liviq_worker")
    op.execute("REVOKE SELECT ON users FROM liviq_worker")
    op.execute("REVOKE SELECT, UPDATE ON notices FROM liviq_worker")
    op.execute("DROP POLICY IF EXISTS worker_scheduled_scan ON notices")

    op.drop_index("ix_notice_attachments_tenant_notice", table_name="notice_attachments")
    op.drop_table("notice_attachments")

    op.drop_column("notices", "pinned")

    # notice_drafts 재생성(구조+RLS) — 이전 마이그레이션(eaf86de665b0) 다운그레이드가 참조.
    op.create_table(
        "notice_drafts",
        sa.Column("notice_id", sa.UUID(), nullable=True),
        sa.Column("prompt_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ai_body", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.UUID(), nullable=True),
        sa.Column("review_status", sa.String(), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "notice_id"],
            ["notices.tenant_id", "notices.id"],
            name="fk_notice_drafts_notice",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reviewed_by"],
            ["users.tenant_id", "users.id"],
            name="fk_notice_drafts_reviewed_by",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_notice_drafts_tenant_id"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notice_drafts")),
    )
    op.execute("ALTER TABLE notice_drafts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notice_drafts FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON notice_drafts FOR ALL "
        f"USING (tenant_id = {_CURRENT_TENANT}) "
        f"WITH CHECK (tenant_id = {_CURRENT_TENANT})"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON notice_drafts TO liviq_app")
