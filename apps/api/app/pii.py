"""pii_vault 봉투 암호화 서비스 — KEK(env) + per-tenant DEK, AES-256-GCM (ADR-0010).

- KEK: env `PII_MASTER_KEY`(32byte base64). 기동 시 길이 검증(아니면 ValueError).
- DEK: 단지별 32byte 랜덤. KEK로 감싸(wrap) tenant_keys에 append-only 저장.
- 레코드 암호화: DEK로 AES-256-GCM. blob = nonce(12) + ciphertext(태그 포함).
- 검색 해시: KEK에서 HKDF로 파생한 키로 HMAC-SHA256(정규화 후, 평문 저장 금지, §6).

복호화·해시는 이 서비스만 수행한다(docs/06 §4.1). tenant_keys 조회는 RLS 하에서
동작하므로 호출부는 반드시 app.tenant_id가 설정된 세션을 넘겨야 한다(§5).
"""

from __future__ import annotations

import base64
import binascii
import hmac
import os
import unicodedata
import uuid

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from liviq_db.models import TenantKey

_KEY_BYTES = 32  # AES-256 / DEK 길이
_NONCE_BYTES = 12  # GCM 표준 nonce
_HMAC_INFO = b"pii-hmac"  # HKDF context — 해시 키를 KEK와 도메인 분리


class PiiCrypto:
    """봉투 암호화·검색 해시 서비스. KEK는 생성자에서 1회 검증."""

    def __init__(self, master_key_b64: str) -> None:
        try:
            kek = base64.b64decode(master_key_b64, validate=True)
        except binascii.Error as exc:
            raise ValueError("PII_MASTER_KEY는 base64여야 합니다") from exc
        if len(kek) != _KEY_BYTES:
            raise ValueError(f"PII_MASTER_KEY는 {_KEY_BYTES}byte여야 합니다(현재 {len(kek)})")
        self._kek = kek
        self._hmac_key = HKDF(
            algorithm=SHA256(), length=_KEY_BYTES, salt=None, info=_HMAC_INFO
        ).derive(kek)

    def hmac_hash(self, value: str) -> str:
        """정규화(NFC + 공백 제거) 후 keyed HMAC-SHA256. hex 반환(결정적)."""
        normalized = unicodedata.normalize("NFC", value).strip()
        return hmac.new(self._hmac_key, normalized.encode("utf-8"), "sha256").hexdigest()

    def encrypt(self, dek: bytes, plaintext: str) -> bytes:
        """DEK로 AES-256-GCM. blob = nonce(12) + ciphertext."""
        nonce = os.urandom(_NONCE_BYTES)
        ct = AESGCM(dek).encrypt(nonce, plaintext.encode("utf-8"), None)
        return nonce + ct

    def decrypt(self, dek: bytes, blob: bytes) -> str:
        """blob 복호 → 평문. DEK 불일치·변조 시 InvalidTag."""
        nonce, ct = blob[:_NONCE_BYTES], blob[_NONCE_BYTES:]
        return AESGCM(dek).decrypt(nonce, ct, None).decode("utf-8")

    async def get_dek(self, session: AsyncSession, tenant_id: uuid.UUID) -> bytes:
        """단지 최신 DEK를 unwrap해 반환. 없으면 생성·wrap·INSERT(key_version=1).

        호출부는 app.tenant_id가 설정된 세션을 넘겨야 한다(RLS·§5). 멱등 —
        기존 키가 있으면 같은 DEK를 재반환.
        """
        wrapped = await session.scalar(
            select(TenantKey.dek_wrapped)
            .where(TenantKey.tenant_id == tenant_id)
            .order_by(TenantKey.key_version.desc())
            .limit(1)
        )
        if wrapped is not None:
            return self._unwrap(wrapped)
        # ponytail: 최초 생성 시 동시성 없음(단일 단지 파일럿). 경쟁 발생하면
        # UNIQUE(tenant_id, key_version) 위반으로 드러남 — 그때 재시도 배선.
        dek = os.urandom(_KEY_BYTES)
        session.add(TenantKey(tenant_id=tenant_id, key_version=1, dek_wrapped=self._wrap(dek)))
        await session.flush()
        return dek

    def _wrap(self, dek: bytes) -> bytes:
        nonce = os.urandom(_NONCE_BYTES)
        return nonce + AESGCM(self._kek).encrypt(nonce, dek, None)

    def _unwrap(self, wrapped: bytes) -> bytes:
        nonce, ct = wrapped[:_NONCE_BYTES], wrapped[_NONCE_BYTES:]
        return AESGCM(self._kek).decrypt(nonce, ct, None)


def get_pii_crypto() -> PiiCrypto:  # pragma: no cover — env 배선(테스트는 직접 생성)
    return PiiCrypto(get_settings().pii_master_key)
