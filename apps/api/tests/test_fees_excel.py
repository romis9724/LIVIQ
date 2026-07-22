"""관리비 총액 트리 파싱·분배 단위 — 들여쓰기 레벨·음수·헤더 스킵·분배 검산(DB 없음)."""

from __future__ import annotations

import io

import pytest
from app.fees_excel import FeeTreeRow, divide_fee_tree, parse_fee_total_xlsx
from fastapi import HTTPException
from openpyxl import Workbook

_HEADER = ("분류", "우리단지총액")


def _xlsx(rows: list[tuple[object, ...]], *, header: tuple[object, ...] | None = _HEADER) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    if header is not None:
        sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parses_indent_levels() -> None:
    # Arrange — 들여쓰기 2칸당 depth 1
    data = _xlsx(
        [
            ("공용관리비", 46762861),
            ("  일반관리비", 24210020),
            ("    인건비", 22634390),
            ("      급여", 15621280),
        ]
    )
    # Act
    rows = parse_fee_total_xlsx(data)
    # Assert
    assert rows == [
        FeeTreeRow(level=0, name="공용관리비", amount=46762861),
        FeeTreeRow(level=1, name="일반관리비", amount=24210020),
        FeeTreeRow(level=2, name="인건비", amount=22634390),
        FeeTreeRow(level=3, name="급여", amount=15621280),
    ]


def test_negative_amount_allowed() -> None:
    rows = parse_fee_total_xlsx(_xlsx([("    수도 공용", -156720)]))
    assert rows[0].amount == -156720
    assert rows[0].level == 2


def test_header_row_skipped() -> None:
    rows = parse_fee_total_xlsx(_xlsx([("공용관리비", 100)]))
    assert [r.name for r in rows] == ["공용관리비"]  # '분류' 헤더 제외


def test_blank_name_rows_skipped() -> None:
    rows = parse_fee_total_xlsx(_xlsx([("공용관리비", 100), (None, None), ("", 0), ("청소비", 50)]))
    assert [r.name for r in rows] == ["공용관리비", "청소비"]


def test_non_numeric_amount_is_422() -> None:
    with pytest.raises(HTTPException) as exc:
        parse_fee_total_xlsx(_xlsx([("공용관리비", "많음")]))
    assert exc.value.status_code == 422


def test_empty_tree_is_422() -> None:
    with pytest.raises(HTTPException) as exc:
        parse_fee_total_xlsx(_xlsx([], header=_HEADER))
    assert exc.value.status_code == 422


def test_corrupt_file_is_422() -> None:
    with pytest.raises(HTTPException) as exc:
        parse_fee_total_xlsx(b"not-an-xlsx")
    assert exc.value.status_code == 422


def test_divide_rounds_half_up_and_keeps_order() -> None:
    # Arrange
    rows = [
        FeeTreeRow(level=0, name="공용관리비", amount=46762861),
        FeeTreeRow(level=1, name="일반관리비", amount=24210020),
        FeeTreeRow(level=1, name="청소비", amount=7250220),
        FeeTreeRow(level=1, name="경비비", amount=7065750),
        FeeTreeRow(level=0, name="개별사용료", amount=47700530),
        FeeTreeRow(level=1, name="난방비", amount=7808640),
        FeeTreeRow(level=1, name="전기료", amount=18325510),
        FeeTreeRow(level=1, name="수도료", amount=9894860),
        FeeTreeRow(level=0, name="장기수선충당금 월부과액", amount=6905380),
        FeeTreeRow(level=0, name="합계", amount=101368771),
    ]
    # Act
    result = divide_fee_tree(rows, 574)
    # Assert — Advisor 검산값(574 기준)
    by_name = {r["name"]: r["amount"] for r in result}
    assert by_name["공용관리비"] == 81468
    assert by_name["일반관리비"] == 42178
    assert by_name["청소비"] == 12631
    assert by_name["경비비"] == 12310
    assert by_name["개별사용료"] == 83102
    assert by_name["난방비"] == 13604
    assert by_name["전기료"] == 31926
    assert by_name["수도료"] == 17238
    assert by_name["장기수선충당금 월부과액"] == 12030
    assert by_name["합계"] == 176601
    # 순서 보존
    assert [r["name"] for r in result] == [r.name for r in rows]
    # 각 행에 name·level·amount
    assert result[0] == {"name": "공용관리비", "level": 0, "amount": 81468}


def test_divide_negative_round() -> None:
    result = divide_fee_tree([FeeTreeRow(level=2, name="수도 공용", amount=-156720)], 574)
    assert result[0]["amount"] == -273  # -156720/574 = -273.03 → -273


def test_divide_zero_households_raises() -> None:
    with pytest.raises(ValueError):
        divide_fee_tree([FeeTreeRow(level=0, name="합계", amount=100)], 0)
