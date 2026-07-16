"""Google OAuth 2.0 + PKCE 어댑터 (docs/06 §2, ADR-0011).

콜백은 api가 PKCE로 처리하고 신원 확인(sub·email)에만 쓴다 — 구글 access/refresh
토큰은 저장하지 않는다(세션 확립 후 즉시 폐기). 외부 IdP는 어댑터 인터페이스 뒤로.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException

from app.config import get_settings

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPE = "openid email"


@dataclass(frozen=True)
class OAuthIdentity:
    sub: str
    email: str | None


class OAuthProvider(Protocol):
    def authorize_url(self, state: str, code_challenge: str) -> str: ...

    async def exchange(self, code: str, code_verifier: str) -> OAuthIdentity: ...


def generate_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge) — S256. verifier는 콜백까지 서버 보관."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def _decode_id_token(id_token: str) -> dict[str, str]:
    """id_token payload(JWT 중간 세그먼트) 파싱. 토큰 엔드포인트(HTTPS)가 직접 반환한
    검증된 응답이므로 서명 재검증 없이 sub·email만 읽는다(중간자 없는 채널)."""
    payload_b64 = id_token.split(".")[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


class GoogleOAuth:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._transport = transport

    def authorize_url(self, state: str, code_challenge: str) -> str:
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": _SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{_AUTH_URL}?{urlencode(params)}"

    async def exchange(self, code: str, code_verifier: str) -> OAuthIdentity:
        data = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
            "code_verifier": code_verifier,
        }
        async with httpx.AsyncClient(transport=self._transport, timeout=10.0) as client:
            resp = await client.post(_TOKEN_URL, data=data)
            resp.raise_for_status()
            payload = _decode_id_token(resp.json()["id_token"])
        # 구글 토큰은 여기서 폐기 — 저장하지 않는다(ADR-0011).
        return OAuthIdentity(sub=payload["sub"], email=payload.get("email"))


def get_oauth_provider() -> OAuthProvider:
    """OAuth 프로바이더 의존성 — 미설정 시 503(로그인만 비활성, 부팅은 성공)."""
    s = get_settings()
    if not (
        s.google_oauth_client_id and s.google_oauth_client_secret and s.google_oauth_redirect_uri
    ):
        raise HTTPException(status_code=503, detail="OAuth 미설정")
    return GoogleOAuth(
        s.google_oauth_client_id,
        s.google_oauth_client_secret,
        s.google_oauth_redirect_uri,
    )
