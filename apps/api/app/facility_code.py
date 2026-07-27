"""시설 코드번호 부여 — `{계통약어}-{위치약어}-{연번}` (H14-2).

규칙 자체는 liviq_db.facility_systems의 순수 함수(마이그레이션 백필과 공유)이고,
여기서는 단지 안에서 다음 연번을 뽑는 조회만 한다. 부여는 서버 전용 — 입력 스키마에
code가 없어 사용자가 만들거나 고칠 수 없다. 동시 생성 레이스의 최종 방어는 DB의
`uq_facilities_tenant_code`다(호출부가 IntegrityError를 받아 재시도).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.facility_systems import facility_code_prefix, next_facility_code
from liviq_db.models import Facility


async def assign_facility_code(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    type_: str | None,
    location: str | None,
) -> str:
    """단지 안에서 다음 시설 코드. 삭제된 시설의 코드도 세어 연번을 재사용하지 않는다."""
    prefix = facility_code_prefix(type_, location)
    rows = await session.scalars(
        select(Facility.code).where(
            Facility.tenant_id == tenant_id,
            Facility.code.startswith(f"{prefix}-"),
        )
    )
    return next_facility_code(prefix, [code for code in rows if code])
