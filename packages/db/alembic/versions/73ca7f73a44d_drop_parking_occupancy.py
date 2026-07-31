"""parking_occupancy 폐기 — 점유는 parking_vehicles 컬럼으로 일원화 (H16, ADR-0023 개정)

같은 점유 기능이 두 갈래로 구현돼 head가 둘이 됐다: a4b5c6d7e8f9(별도 테이블)와
b4c5d6e7f8a9(parking_vehicles.spot_no·entry_at). H16 형태를 채택하고 여기서 합류한다.

DROP은 **IF EXISTS**여야 한다 — 두 갈래가 적용된 DB가 비대칭이기 때문이다: 개발서버는
a4b5를 적용해 테이블이 있고, 로컬·신규 DB는 이 merge까지 한 번에 올라오며 a4b5가
만든 직후 다시 지운다(정책·GRANT·제약은 테이블과 함께 소멸).

downgrade는 테이블을 되살리지 않는다(pass) — 폐기된 설계라 되돌릴 대상이 없고,
스키마를 복구해도 쓰는 코드(모델·라우터·시더)가 이미 없다. a4b5 리비전 파일 자체는
개발서버 히스토리라 남겨둔다.

Revision ID: 73ca7f73a44d
Revises: a4b5c6d7e8f9, b4c5d6e7f8a9
Create Date: 2026-07-31 15:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "73ca7f73a44d"
down_revision: tuple[str, str] = ("a4b5c6d7e8f9", "b4c5d6e7f8a9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS parking_occupancy")


def downgrade() -> None:
    pass  # 폐기 설계 — 재생성하지 않는다(위 doc 참조)
