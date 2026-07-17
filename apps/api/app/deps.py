"""공통 의존성 — 요청 컨텍스트(테넌트·사용자·역할)·DB 세션·스토리지·큐·LLM (docs/02 §4).

인가는 서버에서(규칙 4). 정식 세션 인증(Redis 서버 세션 + httpOnly 쿠키, ADR-0011)은
쿠키 경로로 확립하고, local 환경에선 기존 dev 헤더 경로를 보조로 유지한다. 그 외 환경에서
쿠키·세션이 없으면 401(암묵 통과 금지 — fail-closed).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from fastapi import Cookie, Depends, Header, HTTPException, Response
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_core.llm.client import LlmClient
from app.config import get_settings
from app.session import SESSION_ABSOLUTE_TTL, SessionData, SessionStore, get_session_store
from liviq_db.engine import create_engine, create_session_factory

SESSION_COOKIE_NAME = "liviq_session"

# 역할→문서 공개범위(docs/03 §4.2 visibility 매핑).
RESIDENT_VISIBILITIES = ("ALL", "RESIDENT")
_ROLE_VISIBILITIES: dict[str, tuple[str, ...]] = {
    "RESIDENT": ("ALL", "RESIDENT"),
    "MANAGER": ("ALL", "RESIDENT", "ADMIN", "COUNCIL"),
    "STAFF": ("ALL", "RESIDENT", "ADMIN", "COUNCIL"),
    "FACILITY": ("ALL", "ADMIN"),
    "COUNCIL": ("ALL", "RESIDENT", "COUNCIL"),
}
_VISIBILITY_ORDER = ("ALL", "RESIDENT", "ADMIN", "COUNCIL")
# local dev 헤더 컨텍스트에 부여할 역할 — 기존 로컬 워크플로·테스트 보존.
DEV_ROLES = ("RESIDENT", "MANAGER", "STAFF")


def visibilities_for(roles: Iterable[str]) -> tuple[str, ...]:
    """역할 집합의 공개범위 합집합(정렬 고정). 비어 있으면 입주민 기본값."""
    granted: set[str] = set()
    for role in roles:
        granted.update(_ROLE_VISIBILITIES.get(role, ()))
    result = tuple(v for v in _VISIBILITY_ORDER if v in granted)
    return result or RESIDENT_VISIBILITIES


@dataclass(frozen=True)
class RequestContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    roles: tuple[str, ...] = ()
    visibilities: tuple[str, ...] = RESIDENT_VISIBILITIES


async def get_context(
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    liviq_session: Annotated[str | None, Cookie()] = None,
    x_dev_tenant_id: Annotated[str | None, Header()] = None,
    x_dev_user_id: Annotated[str | None, Header()] = None,
) -> RequestContext:
    """세션 쿠키 우선, 없으면 local dev 헤더. 둘 다 없으면 401(fail-closed).

    온보딩 세션·비활성 상태(pending/rejected/inactive)는 일반 API 접근 403 —
    상태별 화면 분기는 /me가 담당(docs/06 §2). 상태 무관 조회는 get_session_raw.
    """
    if liviq_session:
        try:
            data = await session_store.get(liviq_session)
        except RedisError as exc:  # Redis 장애 → 세션 검증 실패 = 401(ADR-0011)
            raise HTTPException(status_code=401, detail="세션 검증 실패") from exc
        if data is None:
            raise HTTPException(status_code=401, detail="세션 만료 또는 무효")
        if data.kind != "user":  # 온보딩 세션은 일반 API 접근 불가(온보딩 제출만)
            raise HTTPException(status_code=403, detail="온보딩 필요")
        if data.status != "active":  # pending/rejected/inactive → 상태별 안내 화면만
            raise HTTPException(status_code=403, detail=data.status)
        return RequestContext(
            tenant_id=uuid.UUID(data.tenant_id),
            user_id=uuid.UUID(data.user_id),
            roles=data.roles,
            visibilities=visibilities_for(data.roles),
        )
    if get_settings().api_env == "local":
        if not x_dev_tenant_id or not x_dev_user_id:
            raise HTTPException(status_code=401, detail="X-Dev-Tenant-Id·X-Dev-User-Id 헤더 필요")
        try:
            tenant_id = uuid.UUID(x_dev_tenant_id)
            user_id = uuid.UUID(x_dev_user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="헤더 UUID 형식 오류") from exc
        return RequestContext(
            tenant_id=tenant_id,
            user_id=user_id,
            roles=DEV_ROLES,
            visibilities=visibilities_for(DEV_ROLES),
        )
    raise HTTPException(status_code=401, detail="인증 필요 — 세션 없음")


async def get_session_raw(
    session_store: Annotated[SessionStore, Depends(get_session_store)],
    liviq_session: Annotated[str | None, Cookie()] = None,
) -> SessionData:
    """상태 무관 세션 조회 — /me·온보딩 제출용. 쿠키 없거나 만료면 401(상태는 통과)."""
    if not liviq_session:
        raise HTTPException(status_code=401, detail="인증 필요 — 세션 없음")
    try:
        data = await session_store.get(liviq_session)
    except RedisError as exc:
        raise HTTPException(status_code=401, detail="세션 검증 실패") from exc
    if data is None:
        raise HTTPException(status_code=401, detail="세션 만료 또는 무효")
    return data


def require_roles(*roles: str) -> Callable[[RequestContext], Awaitable[RequestContext]]:
    """지정 역할 중 하나 이상을 가진 컨텍스트만 통과. 교집합 없으면 403(규칙 4)."""
    allowed = frozenset(roles)

    async def guard(
        ctx: Annotated[RequestContext, Depends(get_context)],
    ) -> RequestContext:
        if allowed.isdisjoint(ctx.roles):
            raise HTTPException(status_code=403, detail="권한 없음")
        return ctx

    return guard


def set_session_cookie(response: Response, session_id: str) -> None:
    """세션 쿠키 설정 — httpOnly·SameSite=lax, 비-local에서만 Secure."""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        path="/",
        secure=get_settings().api_env != "local",
        max_age=int(SESSION_ABSOLUTE_TTL.total_seconds()),
    )


def clear_session_cookie(response: Response) -> None:
    """로그아웃 — 세션 쿠키 제거."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")


_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(create_engine())
    return _session_factory


async def get_tenant_session(
    ctx: Annotated[RequestContext, Depends(get_context)],
) -> AsyncIterator[AsyncSession]:
    """tenant 컨텍스트가 설정된 트랜잭션 세션 — 래퍼 밖 쿼리 금지(docs/03 §5)."""
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(ctx.tenant_id))
        )
        yield session


async def get_onboarding_session() -> AsyncIterator[AsyncSession]:
    """온보딩 제출 전용 트랜잭션 세션 — 컨텍스트 미설정으로 시작.

    온보딩은 아직 tenant가 확정되지 않았다(초대코드로 확정). tenants는 RLS 예외라
    코드가 초대코드로 조회하고, 확정 후 라우터가 같은 트랜잭션에서 app.tenant_id를
    설정해 households·users·pii_vault를 정상 격리 경로로 읽고 쓴다(auth_lookup 아님 —
    users 전역 SELECT를 열지 않아 명부 대조가 단지 밖으로 새지 않는다, docs/03 §5).
    """
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        yield session


async def get_auth_lookup_session() -> AsyncIterator[AsyncSession]:
    """OAuth 콜백의 login_id(google sub) 전역 조회 전용 트랜잭션 세션.

    login_id는 글로벌 partial-unique라 tenant 확정 전 조회가 불가피 = 표준 격리 예외.
    `app.auth_lookup='on'` 플래그로 users의 `auth_lookup` permissive 정책(SELECT 전용)을
    켠다(docs/03 §5). 행을 찾으면 콜백이 같은 트랜잭션에서 그 tenant_id로 app.tenant_id를
    설정해 정상 격리 경로로 전환한다(user_roles 등 조회).
    """
    factory = _get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(text("SELECT set_config('app.auth_lookup', 'on', true)"))
        yield session


class Storage(Protocol):
    """원본 파일 저장 인터페이스 — 테스트는 인메모리, 운영은 S3(MinIO)."""

    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...


class Queue(Protocol):
    """작업 큐 인터페이스 — 테스트는 fake, 운영은 arq."""

    async def enqueue(self, task: str, *args: Any) -> None: ...


def get_storage() -> Storage:  # pragma: no cover — boto3 I/O 배선(테스트는 오버라이드)
    import asyncio

    import boto3

    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
    )

    class S3Storage:
        async def put(self, key: str, data: bytes) -> None:
            await asyncio.to_thread(
                client.put_object, Bucket=settings.s3_bucket, Key=key, Body=data
            )

        async def get(self, key: str) -> bytes:
            obj = await asyncio.to_thread(client.get_object, Bucket=settings.s3_bucket, Key=key)
            body: bytes = await asyncio.to_thread(obj["Body"].read)
            return body

    return S3Storage()


def get_queue() -> Queue:  # pragma: no cover — arq 배선(테스트는 오버라이드)
    from arq.connections import RedisSettings, create_pool

    class ArqQueue:
        async def enqueue(self, task: str, *args: Any) -> None:
            pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
            try:
                await pool.enqueue_job(task, *args)
            finally:
                await pool.aclose()

    return ArqQueue()


def get_llm() -> LlmClient:  # pragma: no cover — env 배선(테스트는 오버라이드)
    return LlmClient()
