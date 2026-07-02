# ─────────────────────────────────────────────────────────────────────────────
# 로컬 Gmail MCP 서버 (stdio)
#
# tokens.json (Python google-auth `Credentials.to_json()` 형식)을 그대로 읽어
# Gmail API 로 메일을 발송하는 최소 MCP 서버.
#
#   필요 필드: token · refresh_token · token_uri · client_id · client_secret · scopes
#   token 이 만료돼도 refresh_token 으로 자동 갱신 후 파일에 다시 저장한다.
#
# 노출 툴: send_email(to, subject, body, cc?, bcc?)
#
# 실행 (management_agent.py 가 stdio 로 자동 기동):
#   pip install "mcp[cli]" google-auth google-api-python-client
#   python gmail_mcp_server.py
#
# 환경변수:
#   MCP_GMAIL_TOKEN_PATH  토큰 파일 경로 (기본: 이 파일과 같은 디렉토리의 tokens.json)
#   MCP_GMAIL_SENDER      발신자 주소 (기본: "me" = 인증된 계정)
# ─────────────────────────────────────────────────────────────────────────────

import base64
import json
import os
from email.message import EmailMessage
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from mcp.server.fastmcp import FastMCP

# ── 설정 ────────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).resolve().parent
TOKEN_PATH = Path(os.environ.get("MCP_GMAIL_TOKEN_PATH", BASE_DIR / "tokens.json"))
SENDER     = os.environ.get("MCP_GMAIL_SENDER", "me")

mcp = FastMCP("LIVIQ Gmail MCP")


def _load_credentials() -> Credentials:
    """tokens.json 로드 → 만료 시 refresh_token 으로 갱신 후 재저장."""
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"토큰 파일 없음: {TOKEN_PATH}")

    token_data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    creds = Credentials.from_authorized_user_info(token_data)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # 갱신된 access token 을 파일에 다시 저장 (다음 실행 재사용)
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "토큰이 유효하지 않고 refresh_token 으로 갱신할 수 없습니다. "
                "OAuth 동의를 다시 받아 tokens.json 을 재발급하세요."
            )
    return creds


def _build_service():
    return build("gmail", "v1", credentials=_load_credentials(), cache_discovery=False)


@mcp.tool()
def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> str:
    """
    Gmail 로 메일을 발송합니다.

    Args:
        to: 수신자 이메일 주소
        subject: 메일 제목
        body: 메일 본문 (plain text)
        cc: 참조 (선택)
        bcc: 숨은 참조 (선택)
    """
    message = EmailMessage()
    message.set_content(body)
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service = _build_service()
    sent = service.users().messages().send(userId=SENDER, body={"raw": raw}).execute()
    return f"발송 완료 (id={sent.get('id')})"


if __name__ == "__main__":
    mcp.run()
