"""단지 생성 시 기본 공통 코드 시드 (H8-4, ADR-0017, 규칙 8 — 액션은 코드가 실행).

시드 값은 liviq_db.codes_seed.DEFAULT_CODE_GROUPS 단일 출처(기존 단지용 마이그레이션 시드와 공유).
tenant 컨텍스트를 새 단지로 설정한 뒤 삽입하므로 표준 RLS(WITH CHECK) 경로를 그대로 통과한다.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.codes_seed import DEFAULT_CODE_GROUPS
from liviq_db.models import Code, CodeGroup


async def seed_default_codes(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """새 단지에 시스템 코드 그룹(is_system)과 기본 코드를 삽입한다."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    for group in DEFAULT_CODE_GROUPS:
        code_group = CodeGroup(
            tenant_id=tenant_id, group_key=group.group_key, name=group.name, is_system=True
        )
        session.add(code_group)
        await session.flush()
        for order, code in enumerate(group.codes):
            session.add(
                Code(
                    tenant_id=tenant_id,
                    group_id=code_group.id,
                    code=code.code,
                    label=code.label,
                    sort_order=order,
                )
            )
    await session.flush()
