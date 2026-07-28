"""ai_backend_config — LLM 생성 백엔드 런타임 설정(전역 단일 행) (H15-1)

SYS_ADMIN이 UI로 저장한 접속 정보(base URL·모델·API 키·reasoning effort)를 api가 요청
단위로 읽어 반영한다 — 재시작 불필요. 행이 없으면 env `LLM_*` 폴백이라 기존 배포는 이
마이그레이션만으로 동작이 바뀌지 않는다(docs/03 §4.7).

테넌트 데이터가 아니므로 `tenant_id`·RLS 없음 — 방어선은 GRANT와 라우터 역할 가드다.
`liviq_app`에 SELECT·INSERT·UPDATE만 준다(단일 행 upsert — DELETE 개념 없음).
`liviq_worker`는 생성 LLM을 쓰지 않아 GRANT 대상이 아니다.

Revision ID: e9f0a1b2c3d4
Revises: c5d6e7f8a9b0
Create Date: 2026-07-28 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9f0a1b2c3d4"
down_revision: str | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_backend_config"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("reasoning_effort", sa.Text(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("id = 1", name=f"ck_{_TABLE}_single_row"),
        sa.PrimaryKeyConstraint("id", name=f"pk_{_TABLE}"),
    )
    # updated_at 자동 갱신 — initial_schema의 공용 트리거 함수 재사용(docs/03 §3).
    op.execute(
        f"CREATE TRIGGER trg_{_TABLE}_updated_at BEFORE UPDATE ON {_TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {_TABLE} TO liviq_app")


def downgrade() -> None:
    op.drop_table(_TABLE)  # 트리거·GRANT는 테이블과 함께 소멸
