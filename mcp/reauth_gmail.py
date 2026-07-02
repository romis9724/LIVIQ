# ─────────────────────────────────────────────────────────────────────────────
# Gmail 토큰 재발급 유틸
#
# tokens.json 의 refresh_token 이 만료/취소(invalid_grant)됐을 때 실행한다.
# 기존 tokens.json 의 client_id/client_secret 으로 OAuth 동의를 다시 받아
# 새 tokens.json 을 저장한다. (브라우저가 1회 열린다)
#
#   pip install google-auth-oauthlib
#   python reauth_gmail.py
#
# 사전 조건:
#   - GCP > API 및 서비스 > OAuth 동의 화면의 "테스트 사용자"에 sllm14628@gmail.com 등록
#   - (권장) 7일 만료를 피하려면 동의 화면을 "프로덕션"으로 게시
# ─────────────────────────────────────────────────────────────────────────────

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

BASE_DIR   = Path(__file__).resolve().parent
TOKEN_PATH = BASE_DIR / "tokens.json"

# 발송에 필요한 최소 scope (필요 시 추가)
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> None:
    if not TOKEN_PATH.exists():
        raise FileNotFoundError(f"tokens.json 없음: {TOKEN_PATH}")

    old = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    client_id     = old.get("client_id")
    client_secret = old.get("client_secret")
    if not (client_id and client_secret):
        raise RuntimeError("tokens.json 에 client_id/client_secret 이 없습니다.")

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    # access_type=offline + prompt=consent 로 refresh_token 재발급을 보장
    creds = flow.run_local_server(
        port=0, access_type="offline", prompt="consent"
    )  # 브라우저로 동의 → 콜백 수신

    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    print(f"✅ 새 tokens.json 저장 완료: {TOKEN_PATH}")
    print(f"   scopes: {creds.scopes}")
    print(f"   refresh_token 발급됨: {bool(creds.refresh_token)}")


if __name__ == "__main__":
    main()
