"""관리비 엑셀 파싱 단위 — 헤더 검증·금액 오류·항목 매핑(DB 없음)."""

from __future__ import annotations

import io

import pytest
from app.fees_excel import parse_fee_xlsx
from fastapi import HTTPException
from openpyxl import Workbook

_HEADER = ("동", "층", "호", "일반관리비", "청소비")


def _xlsx(rows: list[tuple[object, ...]], *, header: tuple[str, ...] = _HEADER) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parses_items_and_computes_total() -> None:
    result = parse_fee_xlsx(_xlsx([("101", 3, 301, 100000, 20000)]))
    assert result.items == ["일반관리비", "청소비"]
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.building_name == "101"
    assert row.floor == 3
    assert row.unit_no == 301
    assert row.breakdown == {"일반관리비": 100000, "청소비": 20000}
    assert row.total == 120000
    assert result.errors == []


def test_negative_amount_is_row_error() -> None:
    result = parse_fee_xlsx(_xlsx([("101", 3, 301, -1, 20000)]))
    assert result.rows == []
    assert len(result.errors) == 1
    assert result.errors[0].row == 2


def test_non_numeric_amount_is_row_error() -> None:
    result = parse_fee_xlsx(_xlsx([("101", 3, 301, "많음", 20000)]))
    assert len(result.errors) == 1


def test_bad_floor_is_row_error() -> None:
    result = parse_fee_xlsx(_xlsx([("101", "삼층", 301, 100, 10)]))
    assert len(result.errors) == 1
    assert "층" in result.errors[0].reason


def test_wrong_fixed_header_rejected() -> None:
    with pytest.raises(HTTPException) as exc:
        parse_fee_xlsx(_xlsx([("101", 3, 301, 100)], header=("호수", "층", "호", "관리비")))
    assert exc.value.status_code == 422


def test_no_item_columns_rejected() -> None:
    with pytest.raises(HTTPException):
        parse_fee_xlsx(_xlsx([("101", 3, 301)], header=("동", "층", "호")))


def test_blank_rows_skipped() -> None:
    result = parse_fee_xlsx(
        _xlsx([("101", 3, 301, 100, 10), (None, None, None, None, None), ("101", 5, 501, 200, 20)])
    )
    assert len(result.rows) == 2
