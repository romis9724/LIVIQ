"""codes — 공통 코드 레지스트리 CRUD (docs/01 §13 · ADR-0017).

설정 메뉴(MANAGER 전용) + 공지·문서 작성 폼 소비(GET은 STAFF도). 그룹→코드 계층은 parent_id
자기참조이며 순환 방지·같은 그룹 검증을 라우터가 소유한다(DB 깊이 제한 없음, docs/03 §4.10).
하드 삭제 — is_system 그룹·자식 있는 코드는 409. 모든 쿼리는 tenant 컨텍스트 세션 + RLS 이중 방어.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, get_tenant_session, require_roles
from app.schemas.codes import (
    CodeCreateIn,
    CodeGroupCreateIn,
    CodeGroupListOut,
    CodeGroupOut,
    CodeGroupUpdateIn,
    CodeOut,
    CodeUpdateIn,
)
from liviq_db.models import Code, CodeGroup

router = APIRouter(prefix="/admin/code-groups", tags=["codes"])
code_router = APIRouter(prefix="/admin/codes", tags=["codes"])

_READ_ROLES = ("MANAGER", "STAFF")  # 작성 폼 소비 겸용 — STAFF는 조회만
_WRITE_ROLE = require_roles("MANAGER")


def _code_out(code: Code) -> CodeOut:
    return CodeOut.model_validate(code, from_attributes=True)


async def _get_group(session: AsyncSession, tenant_id: uuid.UUID, group_id: uuid.UUID) -> CodeGroup:
    group = await session.scalar(
        select(CodeGroup).where(CodeGroup.id == group_id, CodeGroup.tenant_id == tenant_id)
    )
    if group is None:
        raise HTTPException(status_code=404, detail="코드 그룹을 찾을 수 없음")
    return group


async def _get_code(session: AsyncSession, tenant_id: uuid.UUID, code_id: uuid.UUID) -> Code:
    code = await session.scalar(select(Code).where(Code.id == code_id, Code.tenant_id == tenant_id))
    if code is None:
        raise HTTPException(status_code=404, detail="코드를 찾을 수 없음")
    return code


# ── 그룹 ─────────────────────────────────────────────────────────────────────


@router.get("", response_model=CodeGroupListOut)
async def list_code_groups(
    ctx: Annotated[RequestContext, Depends(require_roles(*_READ_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
) -> CodeGroupListOut:
    """그룹 목록 + 각 그룹의 코드(평면 리스트, parent_id 포함 — 프론트가 트리 구성)."""
    groups = list(
        await session.scalars(
            select(CodeGroup)
            .where(CodeGroup.tenant_id == ctx.tenant_id)
            .order_by(CodeGroup.group_key)
        )
    )
    codes = list(
        await session.scalars(
            select(Code)
            .where(Code.tenant_id == ctx.tenant_id)
            .order_by(Code.group_id, Code.sort_order)
        )
    )
    by_group: dict[uuid.UUID, list[CodeOut]] = {}
    for code in codes:
        by_group.setdefault(code.group_id, []).append(_code_out(code))
    return CodeGroupListOut(
        items=[
            CodeGroupOut(
                id=g.id,
                group_key=g.group_key,
                name=g.name,
                description=g.description,
                is_system=g.is_system,
                codes=by_group.get(g.id, []),
            )
            for g in groups
        ]
    )


@router.post("", response_model=CodeGroupOut, status_code=201)
async def create_code_group(
    ctx: Annotated[RequestContext, Depends(_WRITE_ROLE)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    body: CodeGroupCreateIn,
) -> CodeGroupOut:
    exists = await session.scalar(
        select(CodeGroup.id).where(
            CodeGroup.tenant_id == ctx.tenant_id, CodeGroup.group_key == body.group_key
        )
    )
    if exists is not None:
        raise HTTPException(status_code=409, detail="이미 존재하는 group_key")
    group = CodeGroup(
        tenant_id=ctx.tenant_id,
        group_key=body.group_key,
        name=body.name,
        description=body.description,
    )
    session.add(group)
    await session.flush()
    return CodeGroupOut(
        id=group.id,
        group_key=group.group_key,
        name=group.name,
        description=group.description,
        is_system=group.is_system,
        codes=[],
    )


@router.patch("/{group_id}", response_model=CodeGroupOut)
async def update_code_group(
    ctx: Annotated[RequestContext, Depends(_WRITE_ROLE)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    group_id: uuid.UUID,
    body: CodeGroupUpdateIn,
) -> CodeGroupOut:
    """name·description만 수정(group_key 불변 — is_system 그룹 포함)."""
    group = await _get_group(session, ctx.tenant_id, group_id)
    fields = body.model_fields_set
    if "name" in fields and body.name is not None:
        group.name = body.name
    if "description" in fields:
        group.description = body.description
    await session.flush()
    return CodeGroupOut(
        id=group.id,
        group_key=group.group_key,
        name=group.name,
        description=group.description,
        is_system=group.is_system,
        codes=[],
    )


@router.delete("/{group_id}", status_code=204)
async def delete_code_group(
    ctx: Annotated[RequestContext, Depends(_WRITE_ROLE)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    group_id: uuid.UUID,
) -> Response:
    """하드 삭제 — is_system 그룹은 409, 하위 코드는 FK CASCADE."""
    group = await _get_group(session, ctx.tenant_id, group_id)
    if group.is_system:
        raise HTTPException(status_code=409, detail="시스템 그룹은 삭제할 수 없음")
    await session.delete(group)
    await session.flush()
    return Response(status_code=204)


# ── 코드 ─────────────────────────────────────────────────────────────────────


async def _validate_parent(
    session: AsyncSession, tenant_id: uuid.UUID, group_id: uuid.UUID, parent_id: uuid.UUID
) -> Code:
    """부모 코드는 같은 그룹·같은 tenant여야 한다. 아니면 422."""
    parent = await session.scalar(
        select(Code).where(Code.id == parent_id, Code.tenant_id == tenant_id)
    )
    if parent is None or parent.group_id != group_id:
        raise HTTPException(status_code=422, detail="parent_id는 같은 그룹의 코드여야 함")
    return parent


@code_router.post("", response_model=CodeOut, status_code=201)
async def create_code(
    ctx: Annotated[RequestContext, Depends(_WRITE_ROLE)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    body: CodeCreateIn,
) -> CodeOut:
    await _get_group(session, ctx.tenant_id, body.group_id)
    if body.parent_id is not None:
        await _validate_parent(session, ctx.tenant_id, body.group_id, body.parent_id)
    dup = await session.scalar(
        select(Code.id).where(
            Code.tenant_id == ctx.tenant_id,
            Code.group_id == body.group_id,
            Code.code == body.code,
        )
    )
    if dup is not None:
        raise HTTPException(status_code=409, detail="그룹 내 중복 code")
    code = Code(
        tenant_id=ctx.tenant_id,
        group_id=body.group_id,
        parent_id=body.parent_id,
        code=body.code,
        label=body.label,
        sort_order=body.sort_order,
    )
    session.add(code)
    await session.flush()
    return _code_out(code)


async def _would_cycle(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    group_id: uuid.UUID,
    code_id: uuid.UUID,
    new_parent_id: uuid.UUID,
) -> bool:
    """새 부모에서 parent 체인을 거슬러 올라가 자신에 도달하면 순환(자기참조 포함)."""
    if new_parent_id == code_id:
        return True
    result = await session.execute(
        select(Code.id, Code.parent_id).where(
            Code.tenant_id == tenant_id, Code.group_id == group_id
        )
    )
    parent_of: dict[uuid.UUID, uuid.UUID | None] = {cid: pid for cid, pid in result.all()}
    cursor: uuid.UUID | None = new_parent_id
    seen: set[uuid.UUID] = set()
    while cursor is not None:
        if cursor == code_id:
            return True
        if cursor in seen:  # 기존 데이터에 순환이 있어도 무한루프 방지
            break
        seen.add(cursor)
        cursor = parent_of.get(cursor)
    return False


@code_router.patch("/{code_id}", response_model=CodeOut)
async def update_code(
    ctx: Annotated[RequestContext, Depends(_WRITE_ROLE)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    code_id: uuid.UUID,
    body: CodeUpdateIn,
) -> CodeOut:
    """label·sort_order·active·parent_id 수정. parent_id는 같은 그룹 검증 + 순환 방지(409)."""
    code = await _get_code(session, ctx.tenant_id, code_id)
    fields = body.model_fields_set
    if "parent_id" in fields:
        if body.parent_id is not None:
            await _validate_parent(session, ctx.tenant_id, code.group_id, body.parent_id)
            if await _would_cycle(session, ctx.tenant_id, code.group_id, code_id, body.parent_id):
                raise HTTPException(status_code=409, detail="순환 계층은 허용되지 않음")
        code.parent_id = body.parent_id
    if "label" in fields and body.label is not None:
        code.label = body.label
    if "sort_order" in fields and body.sort_order is not None:
        code.sort_order = body.sort_order
    if "active" in fields and body.active is not None:
        code.active = body.active
    await session.flush()
    return _code_out(code)


@code_router.delete("/{code_id}", status_code=204)
async def delete_code(
    ctx: Annotated[RequestContext, Depends(_WRITE_ROLE)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    code_id: uuid.UUID,
) -> Response:
    """하드 삭제 — 자식이 있으면 409. 도메인(notices·documents) 참조는 FK RESTRICT → 409(H8-6)."""
    code = await _get_code(session, ctx.tenant_id, code_id)
    child_count = await session.scalar(
        select(func.count())
        .select_from(Code)
        .where(Code.tenant_id == ctx.tenant_id, Code.parent_id == code_id)
    )
    if child_count and child_count > 0:
        raise HTTPException(status_code=409, detail="하위 코드가 있어 삭제할 수 없음")
    # SAVEPOINT로 감싸 FK RESTRICT 위반(IntegrityError) 시 트랜잭션 전체를 잃지 않고 409로 전환.
    try:
        async with session.begin_nested():
            await session.delete(code)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="사용 중인 코드는 삭제할 수 없음") from exc
    return Response(status_code=204)
