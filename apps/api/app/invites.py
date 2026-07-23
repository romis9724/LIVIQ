"""초대 계정 생성 서비스 — SYS_ADMIN→소장·소장→직원 공통 경로 (H7-2, ADR-0014).

초대는 대상 tenant에 user 행을 먼저 만든다(auth_tokens FK 필요) — status='invited',
비밀번호 미설정(password_hash NULL), login_id=이메일 keyed HMAC, 평문 이메일은
pii_vault.email_enc 암호화. invite 토큰(7일)을 발급하고 수락 링크를 메일로 보낸다.

전역 이메일 중복 검사는 tenant 확정 전이라 auth_lookup 세션을 받는다(signup 패턴 재사용) —
검사 후 대상 tenant_id로 app.tenant_id를 전환해 정상 격리 경로로 쓴다.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_tokens
from app.config import get_settings
from app.mail import Mailer
from app.pii import PiiCrypto
from app.routers.auth import _normalize_email
from liviq_db.models import PiiVault, User, UserRole


async def create_invite(
    *,
    session: AsyncSession,
    crypto: PiiCrypto,
    mailer: Mailer,
    tenant_id: uuid.UUID,
    email: str,
    role: str,
    name: str | None = None,
) -> uuid.UUID:
    """대상 tenant에 초대 user(status='invited') + role + invite 토큰 생성 후 메일. user_id 반환.

    전역 이메일 중복이면 409. 발송 실패는 예외 전파 → 트랜잭션 롤백(초대 미완 계정을 남기지
    않는다, signup과 동일). 호출부는 auth_lookup 세션(전역 SELECT on)을 넘겨야 한다.

    name이 주어지면 pii_vault.name_enc에 함께 암호화 저장한다(직원 초대 — 목록 식별용).
    중복 이메일은 위에서 409로 걸러지므로 vault는 항상 새로 만든다(기존 행 갱신 경로 없음).
    """
    email_norm = _normalize_email(email)
    email_hash = crypto.hmac_hash(email_norm)

    # 전역 중복 — auth_lookup permissive SELECT(파일럿 단일 단지 이메일 유니크).
    if (
        await session.scalar(
            select(User.id).where(User.login_id == email_hash, User.deleted_at.is_(None))
        )
        is not None
    ):
        raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다")

    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    dek = await crypto.get_dek(session, tenant_id)
    vault = PiiVault(
        tenant_id=tenant_id,
        email_enc=crypto.encrypt(dek, email_norm),
        name_enc=crypto.encrypt(dek, name) if name else None,
        key_version=1,
    )
    session.add(vault)
    await session.flush()
    user = User(
        tenant_id=tenant_id,
        login_id=email_hash,
        status="invited",  # 초대 발송·수락 전(수락 시 password 설정·active 전환)
        pii_ref=vault.id,
    )
    session.add(user)
    await session.flush()
    session.add(UserRole(tenant_id=tenant_id, user_id=user.id, role=role))
    await session.flush()

    raw = await auth_tokens.issue(session, tenant_id, user.id, "invite", auth_tokens.INVITE_TTL)
    link = f"{get_settings().web_admin_base_url}/invite?token={raw}"
    await run_in_threadpool(
        mailer.send,
        email_norm,
        "[LIVIQ] 계정 초대",
        f"아래 링크에서 비밀번호를 설정해 계정을 활성화하세요(7일 유효):\n{link}",
    )
    return user.id
