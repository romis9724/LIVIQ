"""onboarding — 동의→성함·생년월일·동호 제출 + 명부 자동 대조 (ADR-0014, docs/04 §2).

가입(status='registered') 사용자만 제출한다. tenant는 세션에 이미 담겨 있고(가입 시 확정),
라우터가 같은 트랜잭션에서 app.tenant_id를 설정해 명부 대조·프로필 반영을 정상 격리 경로로
수행한다(docs/03 §4.1·§5). 만 14세 미만은 차단(docs/06 §6).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_onboarding_session, set_session_cookie
from app.pii import PiiCrypto, get_pii_crypto
from app.schemas.onboarding import (
    CONSENT_POLICY_VERSION,
    REQUIRED_CONSENT_PURPOSES,
    ProfileIn,
    ProfileOut,
)
from app.session import SessionData, SessionStore, get_session_store
from liviq_db.models import (
    Building,
    Consent,
    Household,
    Notification,
    PiiVault,
    User,
    UserRole,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])

MIN_SIGNUP_AGE = 14  # 만 14세 미만 가입 차단(법정대리인 동의 체계 미보유, docs/06 §6)


def _age_on(birth_date: datetime.date, today: datetime.date) -> int:
    """만 나이 — 생일이 지났는지로 보정."""
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


@router.post("/profile", response_model=ProfileOut)
async def submit_profile(
    body: ProfileIn,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_onboarding_session)],
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    crypto: Annotated[PiiCrypto, Depends(get_pii_crypto)],
    liviq_session: Annotated[str | None, Cookie()] = None,
) -> ProfileOut:
    auth = await _require_registered_session(session_store, liviq_session)
    _validate_consents(body)
    if _age_on(body.birth_date, datetime.date.today()) < MIN_SIGNUP_AGE:
        raise HTTPException(status_code=422, detail="만 14세 미만은 가입할 수 없습니다")

    tenant_id = uuid.UUID(auth.tenant_id)
    user_id = uuid.UUID(auth.user_id)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    household_id = await _resolve_household(session, tenant_id, body)

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None or user.status != "registered":  # 재제출·경합 방어
        raise HTTPException(status_code=409, detail="이미 가입 처리된 계정")

    name_hash = crypto.hmac_hash(body.name)
    birth_hash = crypto.hmac_hash(body.birth_date.isoformat())
    await _store_profile_pii(session, crypto, tenant_id, user, body, name_hash, birth_hash)
    roster_matched = await _consume_roster_match(
        session, tenant_id, household_id, user_id, name_hash, birth_hash
    )
    user.household_id = household_id
    user.roster_matched = roster_matched
    user.status = "pending"  # 승인 대기(역할은 승인 시 부여, docs/06 §2)

    _record_consents(session, tenant_id, user.id, body)
    await _notify_managers(session, tenant_id, user.id)
    await session.flush()

    # 세션 상태 갱신: registered → pending. 즉시 revoke 후 재발급(ADR-0011).
    if liviq_session:
        await session_store.revoke(liviq_session)
    new_sid = await session_store.create(str(tenant_id), str(user.id), [], status="pending")
    set_session_cookie(response, new_sid)
    return ProfileOut(user_id=user.id, status="pending", roster_matched=roster_matched)


async def _require_registered_session(
    session_store: SessionStore, liviq_session: str | None
) -> SessionData:
    if not liviq_session:
        raise HTTPException(status_code=401, detail="인증 필요 — 세션 없음")
    data = await session_store.get(liviq_session)
    if data is None:
        raise HTTPException(status_code=401, detail="세션 만료 또는 무효")
    if data.status != "registered":  # 이미 온보딩 완료(pending+) 또는 부적절 상태
        raise HTTPException(status_code=409, detail="이미 가입 처리된 계정")
    return data


def _validate_consents(body: ProfileIn) -> None:
    granted = {c.purpose for c in body.consents if c.granted}
    missing = REQUIRED_CONSENT_PURPOSES - granted
    if missing:
        raise HTTPException(status_code=422, detail=f"필수 동의 누락: {', '.join(sorted(missing))}")


async def _resolve_household(
    session: AsyncSession, tenant_id: uuid.UUID, body: ProfileIn
) -> uuid.UUID:
    household_id = await session.scalar(
        select(Household.id)
        .join(Building, Building.id == Household.building_id)
        .where(
            Household.tenant_id == tenant_id,
            Building.name == body.building_name,
            Household.floor == body.floor,
            Household.unit_no == body.unit_no,
        )
    )
    if household_id is None:
        raise HTTPException(status_code=422, detail="해당 세대를 찾을 수 없습니다")
    return household_id


async def _store_profile_pii(
    session: AsyncSession,
    crypto: PiiCrypto,
    tenant_id: uuid.UUID,
    user: User,
    body: ProfileIn,
    name_hash: str,
    birth_hash: str,
) -> None:
    """가입 시 만든 pii_vault(email_enc)에 성함·생년월일을 채운다(행 신설 아님)."""
    dek = await crypto.get_dek(session, tenant_id)
    vault: PiiVault | None = None
    if user.pii_ref is not None:
        vault = await session.scalar(select(PiiVault).where(PiiVault.id == user.pii_ref))
    if vault is None:  # pragma: no cover — 가입이 항상 vault를 만든다(방어)
        vault = PiiVault(tenant_id=tenant_id, key_version=1)
        session.add(vault)
        await session.flush()
        user.pii_ref = vault.id
    vault.name_enc = crypto.encrypt(dek, body.name)
    vault.birth_date_enc = crypto.encrypt(dek, body.birth_date.isoformat())
    vault.name_hash = name_hash
    vault.birth_date_hash = birth_hash


async def _consume_roster_match(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    household_id: uuid.UUID,
    user_id: uuid.UUID,
    name_hash: str,
    birth_hash: str,
) -> bool:
    """명부 사전등록 행과 자동 대조(성함+생일+동·호). 일치 시 그 행을 soft delete(행 이동 금지)."""
    matched = await session.scalar(
        select(User)
        .join(PiiVault, PiiVault.id == User.pii_ref)
        .where(
            User.tenant_id == tenant_id,
            User.status == "pre_registered",
            User.household_id == household_id,
            User.login_id.is_(None),
            User.id != user_id,
            User.deleted_at.is_(None),
            PiiVault.name_hash == name_hash,
            PiiVault.birth_date_hash == birth_hash,
        )
    )
    if matched is None:
        return False
    matched.deleted_at = datetime.datetime.now(datetime.UTC)  # 사전등록 행 소진
    return True


def _record_consents(
    session: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID, body: ProfileIn
) -> None:
    now = datetime.datetime.now(datetime.UTC)
    for consent in body.consents:
        session.add(
            Consent(
                tenant_id=tenant_id,
                user_id=user_id,
                purpose=consent.purpose,
                granted=consent.granted,
                granted_at=now if consent.granted else None,
                policy_version=CONSENT_POLICY_VERSION,
            )
        )


async def _notify_managers(
    session: AsyncSession, tenant_id: uuid.UUID, applicant_id: uuid.UUID
) -> None:
    """대기 알림을 소장(MANAGER) 전원에게 생성(외부 발송 아님 — 인앱, docs/03 §4.4)."""
    manager_ids = await session.scalars(
        select(UserRole.user_id).where(UserRole.tenant_id == tenant_id, UserRole.role == "MANAGER")
    )
    for manager_id in manager_ids:
        session.add(
            Notification(
                tenant_id=tenant_id,
                user_id=manager_id,
                type="approval",
                title="새 가입 신청",
                link=f"/admin/approvals?user_id={applicant_id}",
            )
        )
