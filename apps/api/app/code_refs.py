"""공지·문서 분류 코드 참조 검증 (H8-6, ADR-0017, 규칙 3).

도메인 테이블(notices·documents)이 참조하는 category_code_id가 같은 tenant의 지정 그룹
(NOTICE_CATEGORY·DOC_CATEGORY) 코드인지, target_buildings가 같은 tenant 동인지 검증한다.
composite FK가 cross-tenant를 DB에서 차단하지만, 잘못된 그룹·미존재 코드는 앱이 422로 먼저 거른다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Building, Code, CodeGroup


async def validate_category_code(
    session: AsyncSession, tenant_id: uuid.UUID, code_id: uuid.UUID, group_key: str
) -> None:
    """category_code_id가 같은 tenant·지정 그룹 코드인지 확인. 아니면 422."""
    exists = await session.scalar(
        select(Code.id)
        .join(CodeGroup, (Code.group_id == CodeGroup.id) & (Code.tenant_id == CodeGroup.tenant_id))
        .where(
            Code.id == code_id,
            Code.tenant_id == tenant_id,
            CodeGroup.group_key == group_key,
        )
    )
    if exists is None:
        raise HTTPException(status_code=422, detail=f"{group_key} 그룹의 코드가 아님")


async def validate_target_buildings(
    session: AsyncSession, tenant_id: uuid.UUID, building_ids: Sequence[uuid.UUID]
) -> None:
    """target_buildings가 모두 같은 tenant의 동인지 확인. 하나라도 아니면 422."""
    if not building_ids:
        return
    unique_ids = set(building_ids)
    found = set(
        await session.scalars(
            select(Building.id).where(Building.tenant_id == tenant_id, Building.id.in_(unique_ids))
        )
    )
    if found != unique_ids:
        raise HTTPException(status_code=422, detail="target_buildings에 알 수 없는 동이 있음")
