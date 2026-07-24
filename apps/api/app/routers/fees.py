"""관리비 — 단지 총액 트리 업로드·세대수 균등분배(관리자) + 조회(입주민·관리자) + AI 설명(SSE).

원천은 관리자 엑셀(규칙 5, AI는 설명만). 업로드는 총액 트리를 검증·미리보기만 하고,
apply(MANAGER)가 세대수(574)로 **코드가** 균등분배해 fees에 적재한다(AI 미개입 → 규칙 5 준수).
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
from app.fees_excel import divide_fee_tree, parse_fee_total_xlsx
from app.schemas.assistant import AnswerStatus, CitationData, StatusData, StatusStage, TokenData
from app.schemas.fees import (
    AdminFeeDetailOut,
    AdminFeeListOut,
    AdminFeeRow,
    BreakdownRow,
    FeeApplyOut,
    FeeExplainDoneData,
    FeeExplainRequest,
    FeeOut,
    FeeUploadDetailOut,
    FeeUploadOut,
    validate_period,
)
from liviq_db.models import Building, ExcelUpload, Fee, Household, User

router = APIRouter(prefix="/fees", tags=["fees"])
admin_router = APIRouter(prefix="/admin/fees", tags=["fees"])

_ADMIN_ROLES = ("MANAGER",)  # 관리비 전체 소장 전용(H7-2에서 STAFF 제거, docs/04 §4)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 관리비 엑셀 크기 상한
PREVIEW_MAX_LEVEL = 1  # 업로드 미리보기 노출 트리 레벨(대분류·중분류)
EXPLAIN_MAX_LEVEL = 1  # AI 설명 프롬프트에 넣을 트리 레벨(상위 항목만 — 토큰 절감)

HOUSEHOLD_DIVISOR = 574  # 분배 세대수(단지 확정 상수, H8-7 — DB 세대 수와 무관한 비즈니스 상수)
TOTAL_ROW_NAME = "합계"  # 트리 합계행 항목명 — total_amount 소스
SUMMARY_ROOT_NAMES = ("공용관리비", "개별사용료", "장기수선충당금 월부과액")


# ── 업로드·검증(MANAGER) ─────────────────────────────────────────────────────


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

    rows = parse_fee_total_xlsx(data)
    divided = divide_fee_tree(rows, HOUSEHOLD_DIVISOR)

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
            status="validated",
            row_count=len(divided),
            uploaded_by=ctx.user_id,
        )
    )
    await session.flush()
    return FeeUploadOut(
        upload_id=upload_id,
        status="validated",
        period=period,
        row_count=len(divided),
        total=_total_from_breakdown(divided),
        preview=[BreakdownRow(**row) for row in divided if row["level"] <= PREVIEW_MAX_LEVEL],
    )


@admin_router.get("/uploads/{upload_id}", response_model=FeeUploadDetailOut)
async def get_upload(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    upload_id: uuid.UUID,
) -> FeeUploadDetailOut:
    upload = await _get_fee_upload(session, ctx.tenant_id, upload_id)
    return FeeUploadDetailOut(
        upload_id=upload.id,
        type=upload.type,
        period=upload.period,
        status=upload.status,
        row_count=upload.row_count,
    )


# ── 확정 적재(MANAGER만, 전 세대 균등 적재) ─────────────────────────────────


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
    rows = parse_fee_total_xlsx(data)
    divided = divide_fee_tree(rows, HOUSEHOLD_DIVISOR)
    total = _total_from_breakdown(divided)

    household_ids = list(
        await session.scalars(select(Household.id).where(Household.tenant_id == ctx.tenant_id))
    )
    # 단일 트랜잭션(get_tenant_session이 begin) — 해당 월 전 세대 교체(재적용 멱등).
    # 세대당 동일 divided 트리·총액(574 균등분배, 코드 계산 — AI 미개입, 규칙 5).
    await session.execute(
        delete(Fee).where(Fee.tenant_id == ctx.tenant_id, Fee.period == upload.period)
    )
    session.add_all(
        [
            Fee(
                tenant_id=ctx.tenant_id,
                household_id=hid,
                period=upload.period,
                breakdown=divided,
                total_amount=total,
                source="excel",
                upload_id=upload.id,
            )
            for hid in household_ids
        ]
    )
    upload.status = "applied"
    await session.flush()
    return FeeApplyOut(
        upload_id=upload.id, status="applied", period=upload.period, applied=len(household_ids)
    )


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
        breakdown=_breakdown_rows(fee.breakdown) if fee else None,
        total=int(fee.total_amount) if fee and fee.total_amount is not None else None,
        prev_total=prev_total,
    )


@admin_router.get("", response_model=AdminFeeListOut)
async def list_fees(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    period: Annotated[str, Query()],
    building: Annotated[str | None, Query()] = None,
    unit: Annotated[int | None, Query()] = None,
) -> AdminFeeListOut:
    validate_period(period)
    stmt = (
        select(
            Fee.household_id, Fee.total_amount, Building.name, Household.floor, Household.unit_no
        )
        .join(Household, Household.id == Fee.household_id)
        .join(Building, Building.id == Household.building_id)
        .where(Fee.tenant_id == ctx.tenant_id, Fee.period == period)
    )
    if building and building.strip():
        stmt = stmt.where(Building.name.ilike(f"%{building.strip()}%"))
    if unit is not None:
        stmt = stmt.where(Household.unit_no == unit)
    stmt = stmt.order_by(Building.name, Household.floor, Household.unit_no)
    rows = await session.execute(stmt)
    households = [
        AdminFeeRow(
            household_id=hid,
            building_name=name,
            floor=floor,
            unit_no=unit_no,
            total=int(total or 0),
        )
        for hid, total, name, floor, unit_no in rows
    ]
    return AdminFeeListOut(
        period=period,
        households=households,
        total_sum=sum(row.total for row in households),
        household_count=len(households),
    )


@admin_router.get("/{household_id}", response_model=AdminFeeDetailOut)
async def get_fee_detail(
    ctx: Annotated[RequestContext, Depends(require_roles(*_ADMIN_ROLES))],
    session: Annotated[AsyncSession, Depends(get_tenant_session)],
    household_id: uuid.UUID,
    period: Annotated[str, Query()],
) -> AdminFeeDetailOut:
    validate_period(period)
    row = (
        await session.execute(
            select(Fee, Building.name, Household.floor, Household.unit_no)
            .join(Household, Household.id == Fee.household_id)
            .join(Building, Building.id == Household.building_id)
            .where(
                Fee.tenant_id == ctx.tenant_id,
                Fee.household_id == household_id,
                Fee.period == period,
            )
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="해당 세대·월 관리비 없음")
    fee, name, floor, unit_no = row
    return AdminFeeDetailOut(
        period=period,
        building_name=name,
        floor=floor,
        unit_no=unit_no,
        breakdown=_breakdown_rows(fee.breakdown),
        total=int(fee.total_amount) if fee.total_amount is not None else 0,
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
    # 상위 레벨만 dict로 축약해 프롬프트 전달(토큰 절감). fee_explain은 dict[str,int]를 받는다.
    breakdown = _breakdown_dict(fee.breakdown, EXPLAIN_MAX_LEVEL)
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


def _breakdown_rows(breakdown: list[dict[str, Any]] | None) -> list[BreakdownRow]:
    """저장된 트리 리스트 → BreakdownRow 리스트(순서 보존)."""
    if not breakdown:
        return []
    return [
        BreakdownRow(name=str(r["name"]), level=int(r["level"]), amount=int(r["amount"]))
        for r in breakdown
    ]


def _breakdown_dict(breakdown: list[dict[str, Any]] | None, max_level: int) -> dict[str, int]:
    """상위 레벨(<=max_level) 항목만 name→amount dict(AI 설명 프롬프트용)."""
    rows = _breakdown_rows(breakdown)
    return {row.name: row.amount for row in rows if row.level <= max_level}


def _total_from_breakdown(divided: list[dict[str, Any]]) -> int:
    """합계행(name=='합계') 금액. 없으면 대분류(공용·개별·장충) 합."""
    for row in divided:
        if row["name"] == TOTAL_ROW_NAME:
            return int(row["amount"])
    return sum(int(row["amount"]) for row in divided if row["name"] in SUMMARY_ROOT_NAMES)


def _prev_period(period: str) -> str:
    year, month = int(period[:4]), int(period[5:7])
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"
