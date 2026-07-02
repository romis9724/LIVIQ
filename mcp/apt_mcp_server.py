# ─────────────────────────────────────────────────────────────────────────────
# 아파트 관리비 도메인 MCP 서버 (stdio)
#
# management_agent.py 가 MultiServerMCPClient 로 이 서버를 띄워 아래 3개 툴을 사용한다.
#   query_ho_fee(ho)        특정 호실 관리비 상세
#   query_average_fee()     전체 합계/평균
#   send_fee_email(ho)      입주민에게 관리비 안내 메일 발송
#
# 데이터원:
#   Sheets  : service-credential.json (서비스 계정) 로 Google Sheets API 직접 호출
#   Gmail   : gmail_mcp_server.py 의 검증된 OAuth 인증(_build_service) 재사용
#
# 실행 (단독 디버그):
#   pip install "mcp[cli]" google-auth google-api-python-client
#   python apt_mcp_server.py
# ─────────────────────────────────────────────────────────────────────────────

import base64
import os
from email.message import EmailMessage
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build as _gbuild
from mcp.server.fastmcp import FastMCP

# 같은 디렉토리의 Gmail 서버에서 인증 로직 재사용 (검증 완료)
from gmail_mcp_server import _build_service as _build_gmail_service, SENDER

# ── 설정 ────────────────────────────────────────────────────────────────────
BASE_DIR             = Path(__file__).resolve().parent
SERVICE_ACCOUNT_PATH = str(BASE_DIR / "service-credential.json")
SPREADSHEET_ID       = os.environ.get(
    "SPREADSHEET_ID", "1XWkE9pyhTiygMcKLU5Yz6rJEqYJp6KHFfl8JxTzDVMQ"
)
SHEET_MGMT     = "관리비"
SHEET_RESIDENT = "주민정보"
SHEETS_SCOPES  = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# 메일 템플릿용 (데이터/환경에 맞게 조정)
BUILDING_NAME  = os.environ.get("BUILDING_NAME", "101동")
BILLING_PERIOD = os.environ.get("BILLING_PERIOD", "이번 달")
OFFICE_PHONE   = os.environ.get("OFFICE_PHONE", "000-0000")

mcp = FastMCP("LocalToolsServer")

# 전역 데이터 (최초 툴 호출 시 1회 로딩)
MGMT_ROWS:     list[dict] = []
RESIDENT_ROWS: list[dict] = []
HO_LIST:       list[str]  = []
_loaded = False


# ── Sheets 헬퍼 ──────────────────────────────────────────────────────────────
def _parse_int(val) -> int:
    """'8,500' 또는 8500 → 정수 변환"""
    try:
        return int(str(val).replace(",", "").strip())
    except Exception:
        return 0


def _find_header_idx(rows: list[list], required: set[str]) -> int:
    """상단 제목/설명 행을 건너뛰고 required 컬럼을 모두 포함하는 헤더 행 탐색."""
    for i, row in enumerate(rows):
        if required <= {str(c).strip() for c in row}:
            return i
    return 0


def _read_sheet(sheet_name: str) -> list[list]:
    """서비스 계정으로 시트 전체 값(2D 배열)을 읽는다."""
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_PATH, scopes=SHEETS_SCOPES
    )
    svc = _gbuild("sheets", "v4", credentials=creds, cache_discovery=False)
    resp = (
        svc.spreadsheets()
        .values()
        .get(spreadsheetId=SPREADSHEET_ID, range=sheet_name)
        .execute()
    )
    return resp.get("values", [])


def _load_data() -> None:
    """두 시트를 읽어 전역 변수에 저장. 실패 시 명확한 예외."""
    global MGMT_ROWS, RESIDENT_ROWS, HO_LIST, _loaded

    rows   = _read_sheet(SHEET_MGMT)
    h_idx  = _find_header_idx(rows, {"구분", "항목"})
    header = [h.strip() for h in rows[h_idx]] if rows else []

    mgmt_rows: list[dict] = []
    current_section = ""
    for row in rows[h_idx + 1:]:
        padded = row + [""] * (len(header) - len(row))
        rec    = dict(zip(header, padded))

        section = rec.get("구분", "").strip()
        if section:
            current_section = section
        rec["구분"] = current_section

        for col in header:
            if col not in ("구분", "항목", "단위"):
                rec[col] = _parse_int(rec.get(col, 0))

        if rec.get("항목", "").strip():
            mgmt_rows.append(rec)

    rows_res   = _read_sheet(SHEET_RESIDENT)
    res_idx    = _find_header_idx(rows_res, {"호", "이메일"})
    res_header = [h.strip() for h in rows_res[res_idx]] if rows_res else []

    resident_rows: list[dict] = []
    for row in rows_res[res_idx + 1:]:
        padded = row + [""] * (len(res_header) - len(row))
        rec    = dict(zip(res_header, padded))
        if rec.get("호", "").strip():
            resident_rows.append({
                "ho":    rec["호"].strip(),
                "name":  rec.get("이름", "").strip(),
                "email": rec.get("이메일", "").strip(),
            })

    MGMT_ROWS     = mgmt_rows
    RESIDENT_ROWS = resident_rows
    HO_LIST       = [k for k in header if k not in ("구분", "항목", "단위", "합계")]
    _loaded       = True


def _ensure_loaded() -> None:
    if not _loaded:
        _load_data()


def _build_detail(ho: str) -> str:
    """특정 호실의 관리비 내역 텍스트 생성"""
    if ho not in HO_LIST:
        return f"{ho} 데이터 없음"

    lines   = [f"[{ho} 관리비 내역]", f"{'항목':<15} {'금액':>10}원", "-" * 30]
    cur_sec = ""
    total   = 0

    for row in MGMT_ROWS:
        sec  = row.get("구분", "")
        item = row.get("항목", "").strip()
        fee  = row.get(ho, 0) or 0

        if sec != cur_sec:
            cur_sec = sec
            lines.append(f"\n▶ {cur_sec}")

        if item:
            lines.append(f"  {item:<13} {fee:>10,}원")
            total += fee

    lines += ["-" * 30, f"{'합  계':<15} {total:>10,}원"]
    return "\n".join(lines)


def _send_email(to: str, subject: str, body: str) -> str:
    """gmail_mcp_server 의 OAuth 인증을 재사용해 메일 발송."""
    message = EmailMessage()
    message.set_content(body)
    message["To"] = to
    message["Subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = _build_gmail_service()
    sent = service.users().messages().send(userId=SENDER, body={"raw": raw}).execute()
    return f"발송 완료 (id={sent.get('id')})"


# ── MCP 툴 ────────────────────────────────────────────────────────────────────
@mcp.tool()
def query_ho_fee(ho: str) -> str:
    """
    특정 호실의 관리비 상세 내역을 조회합니다.
    예시 입력: "101호" 또는 "102호"
    관리비 시트에서 항목별 금액과 합계를 반환합니다.
    """
    _ensure_loaded()
    ho = ho.strip()
    if not ho.endswith("호"):
        ho = ho + "호"

    result = _build_detail(ho)
    print(f"[query_ho_fee 툴 작동] 호실: {ho}")
    return result


@mcp.tool()
def query_average_fee(dummy: str = "") -> str:
    """
    전체 호실의 관리비 합계와 평균을 계산하여 반환합니다.
    입력값은 무시해도 됩니다.
    """
    _ensure_loaded()
    totals = {ho: sum(row.get(ho, 0) or 0 for row in MGMT_ROWS) for ho in HO_LIST}
    avg    = sum(totals.values()) / len(totals) if totals else 0

    lines = ["[전체 관리비 현황]"]
    for ho, fee in sorted(totals.items()):
        lines.append(f"  {ho}: {fee:,}원")
    lines.append(f"\n평균 관리비: {avg:,.0f}원")

    result = "\n".join(lines)
    print(f"[query_average_fee 툴 작동] 평균: {avg:,.0f}원")
    return result


@mcp.tool()
def send_fee_email(ho: str) -> str:
    """
    특정 호실 입주민에게 관리비 안내 메일을 발송합니다.
    주민정보 시트에서 이름과 이메일을 조회한 뒤 Gmail 로 전송합니다.
    예시 입력: "101호"
    """
    _ensure_loaded()
    ho = ho.strip()
    if not ho.endswith("호"):
        ho = ho + "호"

    resident = next((r for r in RESIDENT_ROWS if r["ho"] == ho), None)
    if not resident:
        return f"❌ {ho} 주민정보 없음"

    name   = resident["name"]
    email  = resident["email"]
    detail = _build_detail(ho)

    subject = f"[관리비 안내] {ho} {name} 님의 {BILLING_PERIOD} 관리비"
    body = (
        f"{name} 님 안녕하세요.\n\n"
        f"{BUILDING_NAME} {ho} {BILLING_PERIOD} 관리비 안내드립니다.\n\n"
        f"{detail}\n\n"
        f"납부 기한 내에 납부해 주시기 바랍니다.\n"
        f"문의: 관리사무소 ☎ {OFFICE_PHONE}\n\n"
        f"감사합니다.\n관리사무소 드림"
    )

    print(f"[send_fee_email 툴 작동] {ho} → {name} ({email})")
    try:
        send_result = _send_email(to=email, subject=subject, body=body)
        return f"✅ {name} ({email}) 메일 발송 완료\n결과: {send_result}"
    except Exception as e:
        return f"❌ 메일 발송 실패: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
