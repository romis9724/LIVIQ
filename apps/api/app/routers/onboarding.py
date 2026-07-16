"""onboarding — 초대코드→동의→성함·생년월일·동호 제출 + 명부 자동 대조 (docs/04 §2).

온보딩 세션(users 행 없는 신규 로그인)만 제출 가능. 초대코드로 tenant를 확정한 뒤
같은 트랜잭션에서 app.tenant_id를 설정해 명부 대조·계정 생성을 정상 격리 경로로 수행한다
(docs/03 §4.1·§5, docs/11 §3.4). 만 14세 미만은 차단(docs/06 §6).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from sqlalchemy import func, select, text
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
    Tenant,
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
    auth = await _require_onboarding_session(session_store, liviq_session)
    _validate_consents(body)
    if _age_on(body.birth_date, datetime.date.today()) < MIN_SIGNUP_AGE:
        raise HTTPException(status_code=422, detail="만 14세 미만은 가입할 수 없습니다")

    tenant_id = await _resolve_tenant(session, body.invite_code)
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )
    household_id = await _resolve_household(session, tenant_id, body)

    name_hash = crypto.hmac_hash(body.name)
    birth_hash = crypto.hmac_hash(body.birth_date.isoformat())
    user, roster_matched = await _match_or_create_user(
        session, crypto, tenant_id, household_id, body, auth.google_sub, name_hash, birth_hash
    )
    _record_consents(session, tenant_id, user.id, body)
    await _notify_managers(session, tenant_id, user.id)
    await session.flush()

    # 세션 승격: 온보딩 세션 폐기 → pending user 세션(역할은 승인 시 부여, docs/06 §2).
    if liviq_session:
        await session_store.revoke(liviq_session)
    new_sid = await session_store.create(str(tenant_id), str(user.id), [], status="pending")
    set_session_cookie(response, new_sid)
    return ProfileOut(user_id=user.id, status="pending", roster_matched=roster_matched)


async def _require_onboarding_session(
    session_store: SessionStore, liviq_session: str | None
) -> SessionData:
    if not liviq_session:
        raise HTTPException(status_code=401, detail="인증 필요 — 세션 없음")
    data = await session_store.get(liviq_session)
    if data is None:
        raise HTTPException(status_code=401, detail="세션 만료 또는 무효")
    if data.kind != "onboarding":  # 이미 가입 완료된 계정의 재제출
        raise HTTPException(status_code=409, detail="이미 가입 처리된 계정")
    if not data.google_sub:
        raise HTTPException(status_code=401, detail="온보딩 세션 손상")
    return data


def _validate_consents(body: ProfileIn) -> None:
    granted = {c.purpose for c in body.consents if c.granted}
    missing = REQUIRED_CONSENT_PURPOSES - granted
    if missing:
        raise HTTPException(status_code=422, detail=f"필수 동의 누락: {', '.join(sorted(missing))}")


async def _resolve_tenant(session: AsyncSession, invite_code: str) -> uuid.UUID:
    """초대코드로 tenant 확정(대소문자 무시). settings['invite_code']가 저장처(전용 컬럼 YAGNI)."""
    tenant_id = await session.scalar(
        select(Tenant.id).where(
            func.lower(Tenant.settings["invite_code"].astext) == invite_code.strip().lower()
        )
    )
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="초대코드가 유효하지 않습니다")
    return tenant_id


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


async def _match_or_create_user(
    session: AsyncSession,
    crypto: PiiCrypto,
    tenant_id: uuid.UUID,
    household_id: uuid.UUID,
    body: ProfileIn,
    google_sub: str | None,
    name_hash: str,
    birth_hash: str,
) -> tuple[User, bool]:
    """명부 사전등록 행과 자동 대조(성함+생일+동·호). 일치 시 그 행 승격, 아니면 신규."""
    matched = await session.scalar(
        select(User)
        .join(PiiVault, PiiVault.id == User.pii_ref)
        .where(
            User.tenant_id == tenant_id,
            User.status == "pre_registered",
            User.household_id == household_id,
            User.login_id.is_(None),
            PiiVault.name_hash == name_hash,
            PiiVault.birth_date_hash == birth_hash,
        )
    )
    if matched is not None:
        matched.login_id = google_sub
        matched.roster_matched = True
        matched.status = "pending"
        await session.flush()
        return matched, True

    dek = await crypto.get_dek(session, tenant_id)
    vault = PiiVault(
        tenant_id=tenant_id,
        name_enc=crypto.encrypt(dek, body.name),
        birth_date_enc=crypto.encrypt(dek, body.birth_date.isoformat()),
        name_hash=name_hash,
        birth_date_hash=birth_hash,
        key_version=1,
    )
    session.add(vault)
    await session.flush()
    user = User(
        tenant_id=tenant_id,
        household_id=household_id,
        login_id=google_sub,
        status="pending",
        roster_matched=False,
        pii_ref=vault.id,
    )
    session.add(user)
    await session.flush()
    return user, False


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
