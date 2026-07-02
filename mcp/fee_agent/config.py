"""설정 · 자격증명 경로 · MCP 서버 파라미터 · LLM 팩토리.

자격증명(service-credential.json · tokens.json)은 mcp/ 디렉토리에 있으며
.gitignore로 차단된다 — 절대 커밋·로그 출력 금지.
"""

import os
import sys
from pathlib import Path

from mcp import StdioServerParameters

# ── 스프레드시트 ─────────────────────────────────────────────────────────────
SPREADSHEET_ID = "1XWkE9pyhTiygMcKLU5Yz6rJEqYJp6KHFfl8JxTzDVMQ"
SHEET_MGMT = "관리비"
SHEET_RESIDENT = "주민정보"

# ── 메일 템플릿용 (데이터/환경에 맞게 조정) ──────────────────────────────────
BUILDING_NAME = os.environ.get("BUILDING_NAME", "101동")
BILLING_PERIOD = os.environ.get("BILLING_PERIOD", "이번 달")
OFFICE_PHONE = os.environ.get("OFFICE_PHONE", "000-0000")

# ── 자격증명 경로 (mcp/ 디렉토리 = 이 패키지의 부모) ─────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
SERVICE_ACCOUNT_PATH = str(BASE_DIR / "service-credential.json")
GMAIL_TOKEN_PATH = str(BASE_DIR / "tokens.json")
GMAIL_SERVER_PATH = str(BASE_DIR / "gmail_mcp_server.py")

# ── Google Sheets MCP 서버 (xing5/mcp-google-sheets, 서비스 계정 인증) ───────
#   PATH/HOME 가 필요하므로 os.environ 을 상속한 뒤 자격증명만 덧붙인다.
SHEETS_MCP = StdioServerParameters(
    command="uvx",
    args=["mcp-google-sheets@latest"],
    env={**os.environ, "SERVICE_ACCOUNT_PATH": SERVICE_ACCOUNT_PATH},
)

# ── 로컬 Gmail MCP 서버 (tokens.json OAuth) ──────────────────────────────────
GMAIL_MCP = StdioServerParameters(
    command=sys.executable,
    args=[GMAIL_SERVER_PATH],
    env={**os.environ, "MCP_GMAIL_TOKEN_PATH": GMAIL_TOKEN_PATH},
)


def build_llm():
    """Ollama 로컬 LLM. 보유 태그에 맞게 OLLAMA_MODEL 로 변경 가능."""
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=os.environ.get("OLLAMA_MODEL", "gemma4:e4b"),
        temperature=0,
    )
