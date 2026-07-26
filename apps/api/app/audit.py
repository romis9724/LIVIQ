"""감사 로그 기록 (H11-1 — docs/06 §8, 03 §4.7).

`audit_logs`는 **append-only**다(런타임 롤에 INSERT·SELECT만 GRANT — 권한으로 강제).
기록 대상 목록은 [docs/06 §8]이 단일 출처이고, 여기 상수가 그 목록의 코드 표현이다.
**행위명 문자열을 직접 타이핑하지 않는다** — 오타는 조용한 감사 누락이 된다.

두 가지 규율:

1. **개인정보 비저장**(docs/06 §4.3·§9). `meta`에 이메일·이름·연락처·차량번호·거절 사유
   원문을 넣지 않는다. 대상은 `target_type`+`target_id`(UUID)로, 규모는 **건수**로만 남긴다.
2. **트랜잭션**. 성공 기록은 업무 변경과 같은 트랜잭션(`record_audit`) — 업무가 롤백되면
   감사도 롤백돼 거짓 기록이 남지 않는다. **로그인 실패만 예외**(`record_audit_standalone`):
   401이 트랜잭션을 롤백시키므로 같은 트랜잭션에 쓰면 기록이 사라진다.

RLS 표준 격리 대상이라 **호출 전에 `app.tenant_id`가 설정돼 있어야** 한다(미설정이면 정책이
거짓 → INSERT 거부 = fail-closed).
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from liviq_db.config import get_settings
from liviq_db.models import AuditLog

logger = logging.getLogger("app.audit")


def client_ip(request: Request) -> str | None:
    """감사용 클라이언트 IP. 프록시 뒤에서는 uvicorn `--proxy-headers`가 X-Forwarded-For를
    반영하므로 `request.client.host`가 실제 클라이언트다(docs/09 §4.3 · Caddyfile).
    """
    return request.client.host if request.client else None


# ── 행위 상수 (docs/06 §8 표와 1:1) ────────────────────────────────────────
AUTH_LOGIN = "auth.login"
AUTH_LOGIN_FAILED = "auth.login_failed"
USER_APPROVED = "user.approved"
USER_REJECTED = "user.rejected"
USER_DEACTIVATED = "user.deactivated"
STAFF_INVITED = "staff.invited"
MANAGER_INVITED = "manager.invited"
ROSTER_UPLOADED = "roster.uploaded"
FEES_CONFIRMED = "fees.confirmed"
PII_PLATES_VIEWED = "pii.plates_viewed"
PII_ROSTER_VIEWED = "pii.roster_viewed"

# target_type 값 — 자유 문자열이 아니라 이 집합만 쓴다(집계·조회 안정).
TARGET_USER = "user"
TARGET_TENANT = "tenant"
TARGET_UPLOAD = "excel_upload"


async def record_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """업무 트랜잭션을 공유하는 감사 기록. 커밋은 호출부 트랜잭션이 한다.

    `meta`에 식별정보를 넣지 말 것(docs/06 §4.3) — 이 함수는 내용을 검사하지 않는다.
    """
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            meta=meta,
            ip=ip,
        )
    )
    # 같은 트랜잭션 안에서 즉시 INSERT를 보내 RLS·권한 위반을 호출 시점에 드러낸다
    # (커밋 시점까지 미루면 실패 원인이 업무 로직에서 멀어진다).
    await session.flush()


async def record_audit_standalone(
    *,
    tenant_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """자기 트랜잭션으로 커밋하는 감사 기록 — **로그인 실패 전용**.

    실패 응답(401)은 요청 트랜잭션을 롤백시키므로, 같은 세션에 쓰면 기록이 사라진다.

    엔진을 **호출마다 만들고 버린다**(NullPool). 요청 세션 팩토리를 재사용하지 않는 이유는
    ①요청 트랜잭션과 분리돼야 하고 ②프로세스 전역 엔진은 생성 시점의 이벤트 루프에 묶여
    다른 루프에서 재사용하면 깨지기 때문이다(테스트에서 실측). 실패 로그인은 레이트 리밋이
    분당 상한을 두는 예외 경로라 커넥션 1개 비용은 문제가 되지 않는다.

    **쓰기 실패는 요청을 바꾸지 않는다**(best-effort + ERROR 로그). 인증 실패 응답(401)은
    감사 저장소 상태와 무관하게 성립해야 하고, 여기서 예외를 올리면 401이 500으로 바뀌어
    인증 계약이 저장소 장애에 묶인다. 레이트 리밋·답변 캐시의 fail-open과 같은 취급이다
    (성공 경로 감사는 반대로 **엄격**하다 — 업무 트랜잭션과 함께 롤백된다).
    누락은 조용히 넘기지 않고 ERROR로 남기므로 모니터링에서 드러난다.
    """
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            await record_audit(
                session,
                tenant_id=tenant_id,
                action=action,
                actor_user_id=actor_user_id,
                target_type=target_type,
                target_id=target_id,
                meta=meta,
                ip=ip,
            )
    except SQLAlchemyError:
        logger.error("감사 기록 실패(요청은 계속) action=%s tenant=%s", action, tenant_id)
    finally:
        await engine.dispose()
