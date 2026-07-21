"""비밀번호 해시·검증 — Argon2id (ADR-0014).

평문·복호가능 형태 저장 금지. 정책은 복잡도 규칙 대신 길이 기준(최소 10자, NIST 계열).
argon2-cffi의 기본 파라미터(Argon2id)를 그대로 쓴다 — 파일럿 보정 여지.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 10

_hasher = PasswordHasher()
# 사용자 부재 시 타이밍을 맞추기 위한 더미 해시(계정 존재 여부 노출 방지, ADR-0014).
_DUMMY_HASH = _hasher.hash("timing-equalizer-not-a-real-password")


def hash_password(password: str) -> str:
    """Argon2id 해시. 반환값에 알고리즘·파라미터·솔트가 포함된다(`$argon2id$...`)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """해시 대조. 불일치·손상 해시는 예외를 흡수해 False로(로그인 판정 단순화)."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return False


def dummy_verify() -> None:
    """사용자 부재 경로에서 verify와 동등한 시간을 소모(타이밍 공격 완화)."""
    verify_password(_DUMMY_HASH, "x")


def needs_rehash(password_hash: str) -> bool:
    """파라미터가 상향돼 재해시가 필요한지 — 로그인 성공 시 판정에 사용."""
    return _hasher.check_needs_rehash(password_hash)
