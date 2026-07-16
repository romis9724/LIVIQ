"""roster — 명부 엑셀 업로드 + 사전등록 diff 병합 (docs/01 §13, docs/03 §4.1, docs/11 §3.4).

MANAGER 전용. 컬럼 성함|생년월일|동|층|호(헤더 1행). 행 검증 실패는 error_report에 축적하고
나머지는 적용한다. diff 병합 키=(name_hash, birth_date_hash, household_id):
신규는 pre_registered 생성, 명부에서 사라진 pre_registered는 inactive 표시(자동 삭제 금지),
이미 가입(active 등)한 세대는 불변.
"""

from __future__ import annotations

import datetime
import io
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openpyxl import load_workbook
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import RequestContext, Storage, get_storage, get_tenant_session, require_roles
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.roster import RosterRowError, RosterUploadOut
from liviq_db.models import Building, ExcelUpload, Household, PiiVault, User

router = APIRouter(prefix="/admin/roster", tags=["roster"])

EXPECTED_HEADER = ("성함", "생년월일", "동", "층", "호")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 명부 엑셀 크기 상한


class RosterRowIn(BaseModel):
    """엑셀 한 행 — 경계 검증(docs 규칙 4). 동은 문자열(예: '101'), 층·호는 정수."""

    name: str = Field(min_length=1, max_length=64)
    birth_date: datetime.date
    building_name: str = Field(min_length=1, max_length=64)
    floor: int
    unit_no: int


@router.post("/upload", response_model=RosterUploadOut)
async def upload_roster(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    file: Annotated[UploadFile, File()],
) -> RosterUploadOut:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 10MB를 초과")

    parsed, errors = _parse_rows(data)

    dek = await crypto.get_dek(session, ctx.tenant_id)
    existing = await _load_pre_registered(session, ctx.tenant_id)
    seen: set[tuple[str, str, uuid.UUID]] = set()
    applied = 0
    for row_no, row in parsed:
        household_id = await _lookup_household(session, ctx.tenant_id, row)
        if household_id is None:
            errors.append(RosterRowError(row=row_no, reason="해당 세대 없음"))
            continue
        key = (
            crypto.hmac_hash(row.name),
            crypto.hmac_hash(row.birth_date.isoformat()),
            household_id,
        )
        seen.add(key)
        if key in existing:
            continue  # 이미 사전등록됨 — 불변
        _create_pre_registered(session, crypto, dek, ctx.tenant_id, household_id, row, key)
        applied += 1

    marked_inactive = _mark_stale_inactive(existing, seen)

    upload_id = uuid.uuid4()
    file_key = f"{ctx.tenant_id}/roster/{upload_id}.xlsx"
    await storage.put(file_key, data)
    session.add(
        ExcelUpload(
            id=upload_id,
            tenant_id=ctx.tenant_id,
            type="roster",
            file_key=file_key,
            status="applied",
            row_count=len(parsed),
            error_report={"errors": [e.model_dump() for e in errors]} if errors else None,
            uploaded_by=ctx.user_id,
        )
    )
    await session.flush()
    return RosterUploadOut(
        upload_id=upload_id, applied=applied, marked_inactive=marked_inactive, errors=errors
    )


def _parse_rows(data: bytes) -> tuple[list[tuple[int, RosterRowIn]], list[RosterRowError]]:
    """xlsx 첫 시트 파싱. 헤더 검증 후 데이터 행을 Pydantic으로 검증."""
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl은 다양한 예외 — 손상 파일은 422
        raise HTTPException(status_code=422, detail="엑셀 파일을 읽을 수 없습니다") from exc
    sheet = workbook.worksheets[0]
    rows = sheet.iter_rows(values_only=True)
    header = next(rows, None)
    if (
        header is None
        or tuple(str(c).strip() if c is not None else "" for c in header[:5]) != EXPECTED_HEADER
    ):
        workbook.close()
        raise HTTPException(
            status_code=422, detail=f"헤더는 {'|'.join(EXPECTED_HEADER)} 여야 합니다"
        )

    parsed: list[tuple[int, RosterRowIn]] = []
    errors: list[RosterRowError] = []
    for offset, cells in enumerate(rows):
        row_no = offset + 2  # 헤더=1
        if cells is None or all(c is None for c in cells[:5]):
            continue  # 빈 행 건너뜀
        try:
            parsed.append((row_no, _row_from_cells(cells)))
        except ValidationError as exc:
            errors.append(RosterRowError(row=row_no, reason=_first_error(exc)))
    workbook.close()
    return parsed, errors


def _row_from_cells(cells: tuple[object, ...]) -> RosterRowIn:
    name, birth, building, floor, unit = cells[:5]
    return RosterRowIn(
        name=str(name).strip() if name is not None else "",
        birth_date=birth,  # type: ignore[arg-type]  # Pydantic이 date/datetime/문자열 강제
        building_name=str(building).strip() if building is not None else "",
        floor=floor,  # type: ignore[arg-type]
        unit_no=unit,  # type: ignore[arg-type]
    )


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    field = ".".join(str(p) for p in err["loc"]) or "행"
    return f"{field}: {err['msg']}"


async def _load_pre_registered(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[tuple[str, str, uuid.UUID], User]:
    rows = await session.execute(
        select(User, PiiVault.name_hash, PiiVault.birth_date_hash)
        .join(PiiVault, PiiVault.id == User.pii_ref)
        .where(
            User.tenant_id == tenant_id,
            User.status == "pre_registered",
            User.deleted_at.is_(None),
        )
    )
    result: dict[tuple[str, str, uuid.UUID], User] = {}
    for user, name_hash, birth_hash in rows:
        if name_hash and birth_hash and user.household_id:
            result[(name_hash, birth_hash, user.household_id)] = user
    return result


async def _lookup_household(
    session: AsyncSession, tenant_id: uuid.UUID, row: RosterRowIn
) -> uuid.UUID | None:
    return await session.scalar(
        select(Household.id)
        .join(Building, Building.id == Household.building_id)
        .where(
            Household.tenant_id == tenant_id,
            Building.name == row.building_name,
            Household.floor == row.floor,
            Household.unit_no == row.unit_no,
        )
    )


def _create_pre_registered(
    session: AsyncSession,
    crypto: PiiCrypto,
    dek: bytes,
    tenant_id: uuid.UUID,
    household_id: uuid.UUID,
    row: RosterRowIn,
    key: tuple[str, str, uuid.UUID],
) -> None:
    name_hash, birth_hash, _ = key
    vault_id = uuid.uuid4()
    session.add(
        PiiVault(
            id=vault_id,
            tenant_id=tenant_id,
            name_enc=crypto.encrypt(dek, row.name),
            birth_date_enc=crypto.encrypt(dek, row.birth_date.isoformat()),
            name_hash=name_hash,
            birth_date_hash=birth_hash,
            key_version=1,
        )
    )
    session.add(
        User(
            tenant_id=tenant_id,
            household_id=household_id,
            login_id=None,
            status="pre_registered",
            roster_matched=False,
            pii_ref=vault_id,
        )
    )


def _mark_stale_inactive(
    existing: dict[tuple[str, str, uuid.UUID], User],
    seen: set[tuple[str, str, uuid.UUID]],
) -> int:
    """명부에서 사라진 pre_registered 행 = inactive(전출 추정, 자동 삭제 금지)."""
    marked = 0
    for key, user in existing.items():
        if key not in seen:
            user.status = "inactive"
            marked += 1
    return marked
