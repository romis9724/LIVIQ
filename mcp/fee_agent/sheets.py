"""Google Sheets MCP 데이터 로딩·파싱, 호실별 내역 생성."""

import asyncio
import json

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from .config import SHEETS_MCP, SPREADSHEET_ID, SHEET_MGMT, SHEET_RESIDENT
from .store import FeeStore


def _parse_int(val) -> int:
    """'8,500' 또는 8500 → 정수 변환"""
    try:
        return int(str(val).replace(",", "").strip())
    except Exception:
        return 0


def _extract_values(result) -> list[list]:
    """mcp-google-sheets get_sheet_data 응답에서 2D 값 배열만 추출.

    include_grid_data=False 응답 형태:
        {"spreadsheetId": ..., "valueRanges": [{"range": ..., "values": [[...]]}]}
    이전 형태(values 직접/리스트)도 방어적으로 허용한다.
    """
    text = result.content[0].text if result.content else ""

    # MCP 툴 에러는 isError=True + 평문 텍스트로 온다 (JSON 아님)
    if getattr(result, "isError", False):
        raise RuntimeError(f"Sheets MCP 오류: {text}")

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        raise RuntimeError(f"Sheets 응답 파싱 실패: {text[:200]}") from e

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        ranges = payload.get("valueRanges")
        if ranges:
            return ranges[0].get("values", [])
        return payload.get("values", [])
    return []


def _find_header_idx(rows: list[list], required: set[str]) -> int:
    """헤더 행 인덱스 탐색. 시트 상단에 제목/설명 행이 있어도 견디도록,
    required 컬럼명을 모두 포함하는 첫 행을 헤더로 본다 (없으면 0)."""
    for i, row in enumerate(rows):
        cells = {str(c).strip() for c in row}
        if required <= cells:
            return i
    return 0


def load_sheet_data(store: FeeStore) -> None:
    """두 시트를 읽어 store 에 저장 (단일 할당 — 부분 실패 시 중복 방지)."""

    async def _load():
        async with stdio_client(SHEETS_MCP) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                r_mgmt = await session.call_tool(
                    "get_sheet_data",
                    {"spreadsheet_id": SPREADSHEET_ID, "sheet": SHEET_MGMT},
                )
                r_res = await session.call_tool(
                    "get_sheet_data",
                    {"spreadsheet_id": SPREADSHEET_ID, "sheet": SHEET_RESIDENT},
                )
                return r_mgmt, r_res

    r_mgmt, r_res = asyncio.run(_load())

    # ── 관리비 시트 파싱 (로컬 변수 → 마지막에 한 번만 할당) ──────────
    #   상단에 제목/기준일 행이 있을 수 있어 '구분'+'항목' 헤더 행을 동적 탐색.
    rows = _extract_values(r_mgmt)
    h_idx = _find_header_idx(rows, {"구분", "항목"})
    header = [h.strip() for h in rows[h_idx]] if rows else []

    mgmt_rows: list[dict] = []
    current_section = ""
    for row in rows[h_idx + 1:]:
        padded = row + [""] * (len(header) - len(row))
        rec = dict(zip(header, padded))

        section = rec.get("구분", "").strip()
        if section:
            current_section = section
        rec["구분"] = current_section

        for col in header:
            if col not in ("구분", "항목", "단위"):
                rec[col] = _parse_int(rec.get(col, 0))

        if rec.get("항목", "").strip():
            mgmt_rows.append(rec)

    # ── 주민정보 시트 파싱 ──────────────────────────────────────────
    rows_res = _extract_values(r_res)
    res_idx = _find_header_idx(rows_res, {"호", "이메일"})
    res_header = [h.strip() for h in rows_res[res_idx]] if rows_res else []

    resident_rows: list[dict] = []
    for row in rows_res[res_idx + 1:]:
        padded = row + [""] * (len(res_header) - len(row))
        rec = dict(zip(res_header, padded))
        if rec.get("호", "").strip():
            resident_rows.append({
                "ho": rec["호"].strip(),
                "name": rec.get("이름", "").strip(),
                "email": rec.get("이메일", "").strip(),
            })

    store.mgmt_rows = mgmt_rows
    store.resident_rows = resident_rows
    store.ho_list = [k for k in header if k not in ("구분", "항목", "단위", "합계")]


def build_detail(store: FeeStore, ho: str) -> str:
    """특정 호실의 관리비 내역 텍스트 생성"""
    if ho not in store.ho_list:
        return f"{ho} 데이터 없음"

    lines = [f"[{ho} 관리비 내역]", f"{'항목':<15} {'금액':>10}원", "-" * 30]
    cur_sec = ""
    total = 0

    for row in store.mgmt_rows:
        sec = row.get("구분", "")
        item = row.get("항목", "").strip()
        fee = row.get(ho, 0) or 0

        if sec != cur_sec:
            cur_sec = sec
            lines.append(f"\n▶ {cur_sec}")

        if item:
            lines.append(f"  {item:<13} {fee:>10,}원")
            total += fee

    lines += ["-" * 30, f"{'합  계':<15} {total:>10,}원"]
    return "\n".join(lines)
