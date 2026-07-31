"""pg_trgm extension — 유사 민원 검색(word_similarity) 전제 (H17-1, ADR-0024)

`search_similar_inquiries` 도구가 제목+본문을 `word_similarity`로 랭킹한다. 한국어 조사
변화에 ILIKE보다 강하고 임베딩 색인 파이프라인이 필요 없다(ADR-0024 — 임베딩 승격은 품질
부족이 실측될 때).

CREATE EXTENSION은 **owner 롤**이어야 한다 — compose `migrate` 서비스가 owner로 실행한다
(api=liviq_app·worker=liviq_worker는 권한 없음, docs/03 §5.1). 인덱스는 만들지 않는다:
민원 건수가 단지당 수백 규모라 seq scan으로 충분하고, GIN 인덱스는 word_similarity 임계
필터를 그대로 쓰지 못한다(필요해지면 그때 `gin_trgm_ops`).

Revision ID: c6d7e8f9a0b1
Revises: 73ca7f73a44d
Create Date: 2026-08-01 09:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c6d7e8f9a0b1"
down_revision: str | None = "73ca7f73a44d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
