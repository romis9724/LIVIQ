"""v2 eval 계정 시드 (dev, 멱등). draft_cases.py의 하드코딩 UUID를 그대로 upsert.

seed_demo._upsert_active_account 패턴 복제 — email+EVAL_PASSWORD+검증·승인·세대바인딩.
FACILITY 역할 계정은 없음(draft 한계 그대로 — FACILITY 케이스는 MANAGER 바인딩).
컨테이너(ai-worker) 안에서 owner DATABASE_URL로 실행. 출력에 users.json 매핑을 찍는다.
"""

import asyncio
import datetime
import json
import uuid

from app.password import hash_password
from app.pii import PiiCrypto, get_pii_crypto
from app.routers.auth import _normalize_email
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import PiiVault, User, UserRole

TID = uuid.UUID("11111111-1111-1111-1111-111111111111")
EVAL_PASSWORD = "liviq-eval-1234!"  # noqa: S105 — 로컬 합성 eval 계정(운영 시드 아님)
# 승인일은 최초 관리비 기간보다 앞서야 한다 — get_fees가 period>=approved_at로 거른다(FR-FEE-03).
# 오늘 승인하면 과거 관리비가 전부 걸러져 관리비 케이스가 오폴백한다.
APPROVED_AT = datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)

# (uuid, role, household_ref|None, email, name) — draft_cases.py 하드코딩과 1:1
MGR = (
    "46f87feb-94bc-4c5c-a768-89366e8737f6",
    "MANAGER",
    None,
    "eval-mgr@example.com",
    "평가관리자",
)
RES = [
    ("88aa6f7a-ca24-467f-b931-122fe574d7a8", "401-201"),
    ("28989e29-e703-4228-b696-10ae0eb034aa", "401-1203"),
    ("1220d57f-2e29-4eaf-b253-4de728a5ecea", "403-201"),
    ("6cc08221-1359-49f1-a80e-9869e41773e6", "402-802"),
    ("2c62e75d-1db9-45ea-946b-a44b190bb916", "401-2303"),
    ("2d711840-78ca-42be-9711-77d73c588a6e", "403-1002"),
    ("4370e4d1-5887-400d-a9d1-ebc3cf2aaace", "405-1303"),
    ("117f0ee5-9cd0-4e73-aca7-8a5d85a919fe", "404-403"),
    ("a034c6b2-d31d-485b-878c-f902a3b74f7a", "405-301"),
    ("457c5006-a8fc-45c0-bd61-e6f363b8103f", "404-1502"),
]

ACCOUNTS = [MGR] + [
    (u, "RESIDENT", hh, f"eval-res-{hh}@example.com", f"평가주민{hh}") for u, hh in RES
]


async def _resolve_household(session: AsyncSession, href: str) -> uuid.UUID | None:
    building, _, unit_no = href.partition("-")
    row = await session.execute(
        text(
            "SELECT h.id FROM households h JOIN buildings b ON b.id=h.building_id"
            " WHERE h.tenant_id=CAST(:t AS uuid) AND b.name=:b AND h.unit_no::text=:u"
        ).bindparams(t=str(TID), b=building, u=unit_no)
    )
    return row.scalar()


async def _upsert(
    session: AsyncSession,
    crypto: PiiCrypto,
    dek: bytes,
    uid: str,
    role: str,
    href: str | None,
    email: str,
    name: str,
) -> str:
    email = _normalize_email(email)
    login_id = crypto.hmac_hash(email)
    now = datetime.datetime.now(datetime.UTC)
    household_id = await _resolve_household(session, href) if href else None
    if href and household_id is None:
        return f"  ! {role} {uid[:8]} household {href} 미발견 — 건너뜀"

    user = await session.get(User, uuid.UUID(uid))
    if user is None:
        vault = PiiVault(
            tenant_id=TID,
            email_enc=crypto.encrypt(dek, email),
            name_enc=crypto.encrypt(dek, name),
            name_hash=crypto.hmac_hash(name),
            key_version=1,
        )
        session.add(vault)
        await session.flush()
        user = User(
            id=uuid.UUID(uid),
            tenant_id=TID,
            household_id=household_id,
            login_id=login_id,
            password_hash=hash_password(EVAL_PASSWORD),
            status="active",
            roster_matched=household_id is not None,
            email_verified_at=now,
            approved_at=APPROVED_AT,
            pii_ref=vault.id,
        )
        session.add(user)
        await session.flush()
        state = "created"
    else:
        user.login_id = login_id
        user.password_hash = hash_password(EVAL_PASSWORD)
        user.status = "active"
        user.deleted_at = None  # soft-delete된 기존 유저면 복구(로그인 제외 방지)
        user.email_verified_at = user.email_verified_at or now
        user.approved_at = APPROVED_AT  # 백데이팅 강제 — 과거 관리비 조회 가능(재실행 정합)
        if household_id is not None:
            user.household_id = household_id
            user.roster_matched = True
        state = "updated"

    exists = await session.scalar(
        select(UserRole.id).where(
            UserRole.tenant_id == TID, UserRole.user_id == user.id, UserRole.role == role
        )
    )
    if exists is None:
        session.add(UserRole(tenant_id=TID, user_id=user.id, role=role))
    return f"  {state:<8} {role:<9} {uid} hh={href or '-':<9} {email}"


async def main() -> None:
    crypto = get_pii_crypto()
    engine = create_engine()
    factory = create_session_factory(engine)
    mapping = {}
    try:
        async with factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TID))
            )
            dek = await crypto.get_dek(session, TID)
            for uid, role, href, email, name in ACCOUNTS:
                line = await _upsert(session, crypto, dek, uid, role, href, email, name)
                print(line)
                mapping[uid] = {
                    "email": _normalize_email(email),
                    "role": role,
                    "tenant_id": str(TID),
                }
    finally:
        await engine.dispose()
    # 검증: 시드 후 approved_at 실값 + period>=approved로 보이는 관리비 수 (새 엔진)
    engine2 = create_engine()
    factory2 = create_session_factory(engine2)
    try:
        async with factory2() as session:
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TID))
            )
            print("\n=== 검증(approved_at · 조회가능 관리비 수) ===")
            for uid, _role, href, _email, _name in ACCOUNTS:
                if not href:
                    continue
                row = await session.execute(
                    text(
                        "SELECT u.approved_at, count(f.*) AS visible FROM users u"
                        " LEFT JOIN fees f ON f.household_id=u.household_id"
                        " AND to_char(u.approved_at,'YYYY-MM') <= f.period"
                        " WHERE u.id=CAST(:uid AS uuid) GROUP BY u.approved_at"
                    ).bindparams(uid=uid)
                )
                r = row.first()
                appr = r.approved_at if r else "??"
                vis = r.visible if r else 0
                print(f"  {href}: approved_at={appr} 조회가능관리비={vis}")
    finally:
        await engine2.dispose()
    print("\n=== USERS_JSON_BEGIN ===")
    print(json.dumps(mapping, ensure_ascii=False))
    print("=== USERS_JSON_END ===")


if __name__ == "__main__":
    asyncio.run(main())
