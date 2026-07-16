"""pii 봉투 암호화 서비스 단위/통합 (ADR-0010).

암복호 왕복·DEK 격리·해시 정규화는 순수 단위. get_dek(멱등·생성·저장 unwrap)은 실 PG.
개인정보 경로라 CRITICAL — KEK 길이/base64 검증(fail-closed)까지 확인한다.
"""

from __future__ import annotations

import base64
import uuid

import pytest
from app.pii import PiiCrypto
from cryptography.exceptions import InvalidTag
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Tenant, TenantKey

_KEK = base64.b64encode(b"k" * 32).decode()
_NAME = "홍길동"


# ── KEK 검증(fail-closed) ─────────────────────────────────────────────────


def test_invalid_kek_length_rejected() -> None:
    with pytest.raises(ValueError, match="32byte"):
        PiiCrypto(base64.b64encode(b"short").decode())


def test_invalid_kek_base64_rejected() -> None:
    with pytest.raises(ValueError, match="base64"):
        PiiCrypto("not valid base64 !!!")


# ── 암복호 왕복 + DEK 격리 ────────────────────────────────────────────────


def test_encrypt_decrypt_roundtrip() -> None:
    crypto = PiiCrypto(_KEK)
    dek = b"d" * 32

    blob = crypto.encrypt(dek, _NAME)

    assert blob != _NAME.encode("utf-8"), "평문이 그대로 저장됨"
    assert crypto.decrypt(dek, blob) == _NAME


def test_encrypt_uses_random_nonce() -> None:
    """같은 평문·DEK라도 nonce가 달라 암호문이 매번 다르다."""
    crypto = PiiCrypto(_KEK)
    dek = b"d" * 32

    assert crypto.encrypt(dek, _NAME) != crypto.encrypt(dek, _NAME)


def test_decrypt_with_wrong_dek_fails() -> None:
    crypto = PiiCrypto(_KEK)
    blob = crypto.encrypt(b"a" * 32, "010-1234-5678")

    with pytest.raises(InvalidTag):
        crypto.decrypt(b"b" * 32, blob)


# ── 검색 해시: 정규화 + 결정성 ───────────────────────────────────────────


def test_hmac_hash_normalizes_whitespace() -> None:
    crypto = PiiCrypto(_KEK)

    assert crypto.hmac_hash(" 홍길동 ") == crypto.hmac_hash(_NAME)


def test_hmac_hash_is_deterministic() -> None:
    crypto = PiiCrypto(_KEK)

    assert crypto.hmac_hash(_NAME) == crypto.hmac_hash(_NAME)


def test_hmac_hash_differs_for_different_values() -> None:
    crypto = PiiCrypto(_KEK)

    assert crypto.hmac_hash(_NAME) != crypto.hmac_hash("김철수")


# ── get_dek: 생성·멱등·저장 후 unwrap (실 PG) ────────────────────────────


async def _seed_tenant(session: AsyncSession) -> uuid.UUID:
    tenant_id = uuid.uuid4()
    session.add(Tenant(id=tenant_id, name="단지", status="active"))
    await session.flush()
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    return tenant_id


async def test_get_dek_creates_key_when_absent(db_session: AsyncSession) -> None:
    tenant_id = await _seed_tenant(db_session)
    crypto = PiiCrypto(_KEK)

    dek = await crypto.get_dek(db_session, tenant_id)

    assert len(dek) == 32
    count = await db_session.scalar(
        select(func.count()).select_from(TenantKey).where(TenantKey.tenant_id == tenant_id)
    )
    assert count == 1, "DEK가 tenant_keys에 저장되지 않음"


async def test_get_dek_is_idempotent(db_session: AsyncSession) -> None:
    """두 번째 호출은 새 키를 만들지 않고 저장된 DEK를 재반환."""
    tenant_id = await _seed_tenant(db_session)
    crypto = PiiCrypto(_KEK)

    first = await crypto.get_dek(db_session, tenant_id)
    second = await crypto.get_dek(db_session, tenant_id)

    assert first == second
    count = await db_session.scalar(
        select(func.count()).select_from(TenantKey).where(TenantKey.tenant_id == tenant_id)
    )
    assert count == 1, "get_dek이 중복 키를 생성함"


async def test_stored_dek_decrypts_previously_encrypted(db_session: AsyncSession) -> None:
    """저장된 DEK를 unwrap해 이전 암호문을 복호 — wrap/unwrap 왕복이 DB 경유로 성립."""
    tenant_id = await _seed_tenant(db_session)
    crypto = PiiCrypto(_KEK)

    dek = await crypto.get_dek(db_session, tenant_id)
    blob = crypto.encrypt(dek, _NAME)
    reloaded = await crypto.get_dek(db_session, tenant_id)

    assert crypto.decrypt(reloaded, blob) == _NAME
