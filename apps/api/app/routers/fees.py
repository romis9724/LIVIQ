"""관리비 — 엑셀 업로드·검증·확정 적재(관리자) + 조회(입주민·관리자) + AI 설명(SSE).

원천은 관리자 엑셀(규칙 5, AI는 설명만). 업로드는 검증·미리보기만 하고 fees에 쓰지 않으며,
apply(MANAGER)가 단일 트랜잭션으로 해당 (tenant, period)를 전체 교체한다(FR-FEE-02).
입주민 조회는 본인 세대 + 입주 승인 이후 월만(FR-FEE-03, docs/06 §2 결정 E).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from ai_core.fee_explain import (
    ExplainCitation,
    ExplainDone,
    ExplainStatus,
    ExplainToken,
    explain_fee,
)
from ai_core.llm.client import LlmClient
from app.deps import (
    RequestContext,
    Storage,
    get_context,
    get_llm,
    get_storage,
    get_tenant_session,
    require_roles,
)
from app.fees_excel import ParsedFeeRow, parse_fee_xlsx
from app.schemas.assistant import AnswerStatus, CitationData, StatusData, StatusStage, TokenData
from app.schemas.fees import (
    AdminFeeListOut,
    AdminFeeRow,
    FeeApplyOut,
    FeeExplainDoneData,
    FeeExplainRequest,
    FeeOut,
    FeePreviewRow,
    FeeRowErrorOut,
    FeeUploadDetailOut,
    FeeUploadOut,
    validate_period,
)
from liviq_db.models import Building, ExcelUpload, Fee, Household, User

router = APIRouter(prefix="/fees", tags=["fees"])
admin_router = APIRouter(prefix="/admin/fees", tags=["fees"])

_ADMIN_ROLES = ("MANAGER",)  # 관리비 전체 소장 전용(H7-2에서 STAFF 제거, docs/04 §4)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 관리비 엑셀 크기 상한
PREVIEW_ROWS = 20  # 업로드 미리보기 행 수(저장 안 함)

HouseholdMap = dict[tuple[str, int, int], uuid.UUID]


# ── 업로드·검증(MANAGER·STAFF) ──────────────────────────────────────────────


@admin_router.post("/uploads", response_model=FeeUploadOut)
async def upload_fees(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    file: Annotated[UploadFile, File()],
    period: Annotated[str, Query()],
) -> FeeUploadOut:
    validate_period(period)
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="빈 파일")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 10MB를 초과")

    parsed = parse_fee_xlsx(data)
    hmap = await _household_map(session, ctx.tenant_id)
    errors = [FeeRowErrorOut(row=e.row, reason=e.reason) for e in parsed.errors]
    valid: list[ParsedFeeRow] = []
    for row in parsed.rows:
        if _match(hmap, row) is None:
            errors.append(FeeRowErrorOut(row=row.row_no, reason="해당 세대 없음"))
        else:
            valid.append(row)

    status = "validated" if valid else "failed"
    upload_id = uuid.uuid4()
    file_key = f"{ctx.tenant_id}/fees/{upload_id}.xlsx"
    await storage.put(file_key, data)
    session.add(
        ExcelUpload(
            id=upload_id,
            tenant_id=ctx.tenant_id,
            type="fee",
            period=period,
            file_key=file_key,
            status=status,
            row_count=len(parsed.rows),
            error_report={"errors": [e.model_dump() for e in errors]} if errors else None,
            uploaded_by=ctx.user_id,
        )
    )
    await session.flush()
    return FeeUploadOut(
        upload_id=upload_id,
        status=status,
        period=period,
        row_count=len(parsed.rows),
        valid_rows=len(valid),
        errors=errors,
        preview=[_preview_row(row) for row in valid[:PREVIEW_ROWS]],
    )


@admin_router.get("/uploads/{upload_id}", response_model=FeeUploadDetailOut)
async def get_upload(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    upload_id: uuid.UUID,
) -> FeeUploadDetailOut:
    upload = await _get_fee_upload(session, ctx.tenant_id, upload_id)
    report = upload.error_report or {}
    return FeeUploadDetailOut(
        upload_id=upload.id,
        type=upload.type,
        period=upload.period,
        status=upload.status,
        row_count=upload.row_count,
        errors=[FeeRowErrorOut(**e) for e in report.get("errors", [])],
    )


# ── 확정 적재(MANAGER만, 전체 교체) ─────────────────────────────────────────


@admin_router.post("/uploads/{upload_id}/apply", response_model=FeeApplyOut)
async def apply_fees(
    ctx: Annotated[RequestContext, Depends(require_roles("MANAGER"))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    storage: Annotated[Storage, Depends(get_storage)],
    upload_id: uuid.UUID,
) -> FeeApplyOut:
    upload = await _get_fee_upload(session, ctx.tenant_id, upload_id)
    if upload.status != "validated":
        raise HTTPException(
            status_code=409, detail="검증 완료(validated) 상태만 확정할 수 있습니다"
        )
    if upload.period is None:
        raise HTTPException(status_code=422, detail="업로드에 대상 월(period)이 없습니다")

    data = await storage.get(upload.file_key)
    parsed = parse_fee_xlsx(data)
    hmap = await _household_map(session, ctx.tenant_id)

    # 단일 트랜잭션(get_tenant_session이 begin) — 해당 월 전체 교체(FR-FEE-02).
    await session.execute(
        delete(Fee).where(Fee.tenant_id == ctx.tenant_id, Fee.period == upload.period)
    )
    applied = 0
    for row in parsed.rows:
        household_id = _match(hmap, row)
        if household_id is None:
            continue
        session.add(
            Fee(
                tenant_id=ctx.tenant_id,
                household_id=household_id,
                period=upload.period,
                breakdown=row.breakdown,
                total_amount=row.total,
                source="excel",
                upload_id=upload.id,
            )
        )
        applied += 1
    upload.status = "applied"
    await session.flush()
    return FeeApplyOut(upload_id=upload.id, status="applied", period=upload.period, applied=applied)


# ── 조회 ────────────────────────────────────────────────────────────────────


@router.get("", response_model=FeeOut)
async def get_my_fees(
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    period: Annotated[str, Query()],
) -> FeeOut:
    validate_period(period)
    approved_month, household_id = await _resident_scope(session, ctx)
    if period < approved_month:  # 승인 이전 월은 비공개(FR-FEE-03) — 빈 응답
        return FeeOut(period=period, breakdown=None, total=None, prev_total=None)

    fee = await _fee_for(session, ctx.tenant_id, household_id, period)
    prev = _prev_period(period)
    prev_total: int | None = None
    if prev >= approved_month:  # 전월도 승인 이후여야 노출(추이용)
        prev_fee = await _fee_for(session, ctx.tenant_id, household_id, prev)
        prev_total = int(prev_fee.total_amount) if prev_fee and prev_fee.total_amount else None
    return FeeOut(
        period=period,
        breakdown=_as_int_breakdown(fee.breakdown) if fee else None,
        total=int(fee.total_amount) if fee and fee.total_amount is not None else None,
        prev_total=prev_total,
    )


@admin_router.get("", response_model=AdminFeeListOut)
async def list_fees(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    period: Annotated[str, Query()],
) -> AdminFeeListOut:
    validate_period(period)
    rows = await session.execute(
        select(
            Fee.household_id, Fee.total_amount, Building.name, Household.floor, Household.unit_no
        )
        .join(Household, Household.id == Fee.household_id)
        .join(Building, Building.id == Household.building_id)
        .where(Fee.tenant_id == ctx.tenant_id, Fee.period == period)
        .order_by(Building.name, Household.floor, Household.unit_no)
    )
    households = [
        AdminFeeRow(
            household_id=hid,
            building_name=name,
            floor=floor,
            unit_no=unit,
            total=int(total or 0),
        )
        for hid, total, name, floor, unit in rows
    ]
    return AdminFeeListOut(
        period=period,
        households=households,
        total_sum=sum(row.total for row in households),
        household_count=len(households),
    )


# ── AI 설명(SSE, 입주민) ─────────────────────────────────────────────────────


@router.post("/explain")
async def explain(
    body: FeeExplainRequest,
    ctx: Annotated[RequestContext, Depends(get_context)],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    llm: Annotated[LlmClient, Depends(get_llm)],
) -> EventSourceResponse:
    approved_month, household_id = await _resident_scope(session, ctx)
    if body.period < approved_month:  # 승인 이전 월 = 조회 불가 → 없음과 동일(404)
        raise HTTPException(status_code=404, detail="해당 월 관리비 없음")
    fee = await _fee_for(session, ctx.tenant_id, household_id, body.period)
    if fee is None or fee.total_amount is None:
        raise HTTPException(status_code=404, detail="해당 월 관리비 없음")

    prev_fee = await _fee_for(session, ctx.tenant_id, household_id, _prev_period(body.period))
    prev_total = int(prev_fee.total_amount) if prev_fee and prev_fee.total_amount else None
    avg = await session.scalar(
        select(func.avg(Fee.total_amount)).where(
            Fee.tenant_id == ctx.tenant_id, Fee.period == body.period
        )
    )
    avg_total = int(avg) if avg is not None else None
    breakdown = _as_int_breakdown(fee.breakdown)
    total = int(fee.total_amount)

    async def stream() -> AsyncIterator[dict[str, str]]:
        async for event in explain_fee(
            llm=llm,
            period=body.period,
            breakdown=breakdown,
            total=total,
            prev_total=prev_total,
            avg_total=avg_total,
        ):
            match event:
                case ExplainStatus(stage=stage):
                    payload = StatusData(stage=cast(StatusStage, stage)).model_dump_json()
                    yield {"event": "status", "data": payload}
                case ExplainToken(text=text):
                    yield {"event": "token", "data": TokenData(text=text).model_dump_json()}
                case ExplainCitation(document_title=title, quote=quote):
                    yield {
                        "event": "citation",
                        "data": CitationData(
                            ref=1, document_id=None, document_title=title, quote=quote
                        ).model_dump_json(),
                    }
                case ExplainDone() as done:
                    yield {
                        "event": "done",
                        "data": FeeExplainDoneData(
                            status=cast(AnswerStatus, done.status),
                            confidence=done.confidence,
                            needs_review=done.needs_review,
                            fallback_reason=done.fallback_reason,
                        ).model_dump_json(),
                    }

    return EventSourceResponse(stream())


# ── 헬퍼 ────────────────────────────────────────────────────────────────────


async def _household_map(session: AsyncSession, tenant_id: uuid.UUID) -> HouseholdMap:
    """(동, 층, 호) → household_id. 행 매칭 N회 쿼리 대신 1회 로드."""
    rows = await session.execute(
        select(Building.name, Household.floor, Household.unit_no, Household.id)
        .join(Building, Building.id == Household.building_id)
        .where(Household.tenant_id == tenant_id)
    )
    return {(name, floor, unit): hid for name, floor, unit, hid in rows}


def _match(hmap: HouseholdMap, row: ParsedFeeRow) -> uuid.UUID | None:
    return hmap.get((row.building_name, row.floor, row.unit_no))


def _preview_row(row: ParsedFeeRow) -> FeePreviewRow:
    return FeePreviewRow(
        building_name=row.building_name,
        floor=row.floor,
        unit_no=row.unit_no,
        breakdown=row.breakdown,
        total=row.total,
    )


async def _get_fee_upload(
    session: AsyncSession, tenant_id: uuid.UUID, upload_id: uuid.UUID
) -> ExcelUpload:
    upload = await session.scalar(
        select(ExcelUpload).where(
            ExcelUpload.id == upload_id,
            ExcelUpload.tenant_id == tenant_id,
            ExcelUpload.type == "fee",
        )
    )
    if upload is None:
        raise HTTPException(status_code=404, detail="업로드를 찾을 수 없음")
    return upload


async def _resident_scope(session: AsyncSession, ctx: RequestContext) -> tuple[str, uuid.UUID]:
    """본인 세대 + 승인 월 반환. 세대 미배정 422, 미승인은 미래 월(조회 전부 차단)."""
    user = await session.scalar(
        select(User).where(User.id == ctx.user_id, User.tenant_id == ctx.tenant_id)
    )
    if user is None or user.household_id is None:
        raise HTTPException(status_code=422, detail="세대가 배정되지 않았습니다")
    # 미승인(approved_at 없음)은 어떤 월도 열리지 않도록 '9999-12' 경계로 차단.
    approved_month = user.approved_at.strftime("%Y-%m") if user.approved_at else "9999-12"
    return approved_month, user.household_id


async def _fee_for(
    session: AsyncSession, tenant_id: uuid.UUID, household_id: uuid.UUID, period: str
) -> Fee | None:
    return await session.scalar(
        select(Fee).where(
            Fee.tenant_id == tenant_id,
            Fee.household_id == household_id,
            Fee.period == period,
        )
    )


def _as_int_breakdown(breakdown: dict[str, Any] | None) -> dict[str, int]:
    if not breakdown:
        return {}
    return {name: int(amount) for name, amount in breakdown.items()}


def _prev_period(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"
