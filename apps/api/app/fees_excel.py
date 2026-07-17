"""관리비 엑셀 파싱 — 순수 로직(DB 없음, docs/09 §8.2 H2-5 컬럼 계약).

헤더 = `동, 층, 호` + 이후 열 전부 항목명(breakdown 키). 합계는 서버 계산.
금액은 KRW 원 단위 정수(음수·비숫자 거절). 세대 매칭은 라우터(DB) 소관.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from fastapi import HTTPException
from openpyxl import load_workbook

FIXED_HEADER = ("동", "층", "호")


@dataclass(frozen=True)
class FeeRowError:
    row: int  # 엑셀 행 번호(헤더=1, 데이터 첫 행=2)
    reason: str


@dataclass(frozen=True)
class ParsedFeeRow:
    row_no: int
    building_name: str
    floor: int
    unit_no: int
    breakdown: dict[str, int]  # 항목명 → 금액(원 단위 정수)
    total: int


@dataclass(frozen=True)
class FeeParseResult:
    items: list[str]  # 항목명 열(헤더 순서)
    rows: list[ParsedFeeRow]
    errors: list[FeeRowError]


def parse_fee_xlsx(data: bytes) -> FeeParseResult:
    """xlsx 첫 시트 파싱. 헤더 오류는 422, 행 단위 값 오류는 errors에 축적."""
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl은 다양한 예외 — 손상 파일은 422
        raise HTTPException(status_code=422, detail="엑셀 파일을 읽을 수 없습니다") from exc
    try:
        sheet = workbook.worksheets[0]
        row_iter = sheet.iter_rows(values_only=True)
        items = _parse_header(next(row_iter, None))
        rows: list[ParsedFeeRow] = []
        errors: list[FeeRowError] = []
        for offset, cells in enumerate(row_iter):
            row_no = offset + 2  # 헤더=1
            if cells is None or all(c is None for c in cells[:3]):
                continue  # 빈 행 건너뜀
            parsed = _parse_row(row_no, cells, items)
            if isinstance(parsed, FeeRowError):
                errors.append(parsed)
            else:
                rows.append(parsed)
        return FeeParseResult(items=items, rows=rows, errors=errors)
    finally:
        workbook.close()


def _parse_header(raw: tuple[object, ...] | None) -> list[str]:
    if raw is None:
        raise HTTPException(status_code=422, detail="빈 시트")
    header = [str(c).strip() if c is not None else "" for c in raw]
    while header and header[-1] == "":  # 후행 빈 열 제거(엑셀 잔여 컬럼)
        header.pop()
    if len(header) < 4 or tuple(header[:3]) != FIXED_HEADER:
        raise HTTPException(status_code=422, detail="헤더는 동,층,호 + 항목명 열이어야 합니다")
    items = header[3:]
    if any(not name for name in items):
        raise HTTPException(status_code=422, detail="빈 항목명 열이 있습니다")
    if len(set(items)) != len(items):
        raise HTTPException(status_code=422, detail="중복 항목명 열이 있습니다")
    return items


def _parse_row(
    row_no: int, cells: tuple[object, ...], items: list[str]
) -> ParsedFeeRow | FeeRowError:
    building = cells[0]
    if building is None or not str(building).strip():
        return FeeRowError(row=row_no, reason="동 누락")
    floor = _to_int(cells[1] if len(cells) > 1 else None)
    unit = _to_int(cells[2] if len(cells) > 2 else None)
    if floor is None or unit is None:
        return FeeRowError(row=row_no, reason="층·호는 정수여야 합니다")
    breakdown: dict[str, int] = {}
    for idx, name in enumerate(items):
        cell = cells[3 + idx] if len(cells) > 3 + idx else None
        amount = _to_amount(cell)
        if amount is None:
            return FeeRowError(row=row_no, reason=f"{name}: 0 이상 정수 금액이어야 합니다")
        breakdown[name] = amount
    return ParsedFeeRow(
        row_no=row_no,
        building_name=str(building).strip(),
        floor=floor,
        unit_no=unit,
        breakdown=breakdown,
        total=sum(breakdown.values()),
    )


def _to_int(cell: object) -> int | None:
    """층·호 정수 변환. bool은 거절(엑셀 TRUE/FALSE 오입력 방지)."""
    if isinstance(cell, bool):
        return None
    if isinstance(cell, int):
        return cell
    if isinstance(cell, float) and cell.is_integer():
        return int(cell)
    return None


def _to_amount(cell: object) -> int | None:
    """금액 = 0 이상 원 단위 정수. 음수·비숫자·소수는 거절."""
    value = _to_int(cell)
    if value is None or value < 0:
        return None
    return value
