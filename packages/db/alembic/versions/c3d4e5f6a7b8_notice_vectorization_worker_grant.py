"""notice vectorization — worker SELECT on notice_attachments

H8-3 (ADR-0015 개정 노트): published 공지 본문+파싱 가능 첨부를 content_chunks(source_type=
notice)로 인제스트한다. 워커가 tenant 컨텍스트에서 첨부 파싱을 위해 notice_attachments를 읽어야
하므로 SELECT를 GRANT한다(content_chunks 쓰기 GRANT는 d7e8f9a0b1c2에서 기존). 스키마 변경 없음
— 표준 tenant_isolation 정책은 e8b1c4d09a2f에서 이미 적용됨.

Revision ID: c3d4e5f6a7b8
Revises: e8b1c4d09a2f
Create Date: 2026-07-22 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "e8b1c4d09a2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT SELECT ON notice_attachments TO liviq_worker")


def downgrade() -> None:
    op.execute("REVOKE SELECT ON notice_attachments FROM liviq_worker")
