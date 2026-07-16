"""공통 의존성 — 요청 컨텍스트(테넌트·사용자)·DB 세션·스토리지·큐·LLM (docs/02 §4).

인가는 서버에서(규칙 4). 정식 인증(Google OAuth + Redis 세션, ADR-0011)은 후속 —
지금은 **local 환경 전용 dev 헤더 컨텍스트**만 허용하고, 그 외 환경은 501을 반환한다
(암묵 통과 금지 — fail-closed).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from fastapi import Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_core.llm.client import LlmClient
from app.config import get_settings
from liviq_db.engine import create_engine, create_session_factory

# 역할→문서 공개범위(docs/03 §4.2 visibility 매핑). H1은 입주민 여정만.
RESIDENT_VISIBILITIES = ("ALL", "RESIDENT")


@dataclass(frozen=True)
class RequestContext:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    visibilities: tuple[str, ...] = RESIDENT_VISIBILITIES


async def get_context(
    x_dev_tenant_id: Annotated[str | None, Header()] = None,
    x_dev_user_id: Annotated[str | None, Header()] = None,
) -> RequestContext:
    """local 전용 dev 컨텍스트. 정식 세션 인증 도입 시 이 함수만 교체."""
    if get_settings().api_env != "local":
        raise HTTPException(status_code=501, detail="인증 미구현 — local 환경 전용 API")
    if not x_dev_tenant_id or not x_dev_user_id:
        raise HTTPException(status_code=401, detail="X-Dev-Tenant-Id·X-Dev-User-Id 헤더 필요")
    try:
        return RequestContext(
            tenant_id=uuid.UUID(x_dev_tenant_id), user_id=uuid.UUID(x_dev_user_id)
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="헤더 UUID 형식 오류") from exc


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


class Storage(Protocol):
    """원본 파일 저장 인터페이스 — 테스트는 인메모리, 운영은 S3(MinIO)."""

    async def put(self, key: str, data: bytes) -> None: ...


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
