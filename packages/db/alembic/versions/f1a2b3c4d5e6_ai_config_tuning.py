"""ai_backend_config 확장 — 임베딩 백엔드 + RAG 튜닝 노브 (H15-3)

전부 NULL 허용 = env/코드 기본값 폴백(기존 배포 동작 무변화, docs/03 §4.7). 임베딩·
chunk_max_tokens는 위험 노브(기존 벡터와 불일치) — 반영은 명시적 재색인으로 완성한다.

`liviq_worker`에 SELECT를 준다 — ai-worker 인제스트가 활성 임베딩 설정·청킹 상한을
잡 단위로 읽어야 하기 때문(쓰기는 api(`liviq_app`)만, docs/03 §5.1).

Revision ID: f1a2b3c4d5e6
Revises: e9f0a1b2c3d4
Create Date: 2026-07-28 14:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e9f0a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_backend_config"

_COLUMNS: tuple[tuple[str, sa.types.TypeEngine[object]], ...] = (
    ("embedding_base_url", sa.Text()),
    ("embedding_model", sa.Text()),
    ("embedding_api_key", sa.Text()),
    ("chunk_max_tokens", sa.Integer()),
    ("retrieval_top_k", sa.Integer()),
    ("llm_max_output_tokens", sa.Integer()),
    ("llm_timeout_s", sa.Float()),
    ("tool_confidence", sa.Float()),
    ("answer_cache_ttl_s", sa.Integer()),
)


def upgrade() -> None:
    for name, type_ in _COLUMNS:
        op.add_column(_TABLE, sa.Column(name, type_, nullable=True))
    op.execute(f"GRANT SELECT ON {_TABLE} TO liviq_worker")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ON {_TABLE} FROM liviq_worker")
    for name, _type in reversed(_COLUMNS):
        op.drop_column(_TABLE, name)
