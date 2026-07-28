"""arq 워커 — 큐 태스크 등록·실행 진입점 (docs/01 §8, ADR-0013).

실행: `uv run --no-sync arq ai_worker.worker.WorkerSettings`
태스크는 이벤트 claim 후 해당 tenant로 `SET LOCAL app.tenant_id` — BYPASSRLS 없이
RLS를 그대로 받는다(docs/03 §5). jobs 테이블로 상태 추적(docs/03 §4.7).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from typing import Any

import boto3
from arq import cron
from arq.connections import RedisSettings
from redis.exceptions import RedisError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.backend_config import CONFIG_ROW_ID, AiTuning, merge_settings, merge_tuning
from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient
from ai_worker.config import get_settings
from ai_worker.graph_sync import sync_outbox_task
from ai_worker.ingest import IngestResult, ingest_document
from ai_worker.ingest_notice import NoticeIngestResult, ingest_notice
from ai_worker.notices_publish import publish_due_notices
from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import AiBackendConfig
from liviq_db.runtime_roles import RuntimeRoleError, assert_no_rls_bypass

logger = logging.getLogger("ai_worker.worker")


async def _job_runtime(session: AsyncSession, ctx: dict[str, Any]) -> tuple[LlmClient, AiTuning]:
    """잡 실행 시점의 활성 임베딩 설정·튜닝 노브 해석 (H15-3, docs/03 §4.7).

    관리자가 UI로 임베딩 백엔드·청킹 상한을 바꾸면 **다음 잡부터** 반영된다(워커 재시작
    불필요). `ai_backend_config`는 전역 단일 행이고 `liviq_worker`는 SELECT만 가진다.
    행이 없으면 기동 시 만든 env 기반 클라이언트를 그대로 쓴다(기존 계약).
    """
    base: LlmClient = ctx["llm"]
    row = await session.scalar(select(AiBackendConfig).where(AiBackendConfig.id == CONFIG_ROW_ID))
    if row is None:
        return base, AiTuning()
    return base.with_settings(merge_settings(row, env=base.settings)), merge_tuning(row)


def _download_factory() -> Any:  # pragma: no cover — boto3 I/O 배선(통합 환경에서 검증)
    """S3(MinIO) 다운로더 — boto3는 동기라 스레드로 감싼다."""
    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
    )

    async def download(storage_key: str) -> bytes:
        def _get() -> bytes:
            obj = client.get_object(Bucket=settings.s3_bucket, Key=storage_key)
            body: bytes = obj["Body"].read()
            return body

        return await asyncio.to_thread(_get)

    return download


async def ingest_document_task(
    ctx: dict[str, Any], document_id: str, tenant_id: str
) -> dict[str, Any]:
    """문서 인제스트 태스크. 인프라 오류는 예외 전파(arq 재시도), 형식 오류는 failed 기록."""
    session_factory = ctx["session_factory"]
    download = ctx["download"]
    doc_id, ten_id = uuid.UUID(document_id), uuid.UUID(tenant_id)

    async with session_factory() as session, session.begin():
        # 활성 설정은 tenant 컨텍스트와 무관한 전역 행 — 컨텍스트 설정 전에 읽는다.
        llm, tuning = await _job_runtime(session, ctx)
        # tenant 컨텍스트 — RLS 이중 방어의 1층(docs/03 §5)
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(ten_id))
        )
        result: IngestResult = await ingest_document(
            session,
            llm=llm,
            download=download,
            document_id=doc_id,
            tenant_id=ten_id,
            chunk_max_tokens=tuning.chunk_max_tokens,
        )

    # 색인 성공 시 캐시 세대 증가 → 이전 답변 캐시를 키 수준에서 무효화(H4-2, docs/08 §2.1).
    # 키 포맷은 apps/api answer_cache._gen_key(`cache:gen:{tenant}`)와 일치해야 한다.
    # arq는 ctx["redis"]로 풀을 주입한다(테스트 ctx엔 없을 수 있음 → 건너뜀). fail-open.
    redis = ctx.get("redis")
    if redis is not None and result.status == "indexed":
        # 무효화 실패가 인제스트 성공을 되돌리면 안 됨(fail-open).
        with contextlib.suppress(RedisError):
            await redis.incr(f"cache:gen:{ten_id}")

    return {"status": result.status, "chunks": result.chunk_count, "error": result.error}


async def ingest_notice_task(ctx: dict[str, Any], notice_id: str, tenant_id: str) -> dict[str, Any]:
    """공지 인제스트 태스크. published 공지만 색인, 미발행·삭제는 스킵(ingest_notice)."""
    session_factory = ctx["session_factory"]
    download = ctx["download"]
    nid, ten_id = uuid.UUID(notice_id), uuid.UUID(tenant_id)

    async with session_factory() as session, session.begin():
        llm, tuning = await _job_runtime(session, ctx)  # 잡 단위 활성 설정(H15-3)
        # tenant 컨텍스트 — RLS 이중 방어의 1층(docs/03 §5)
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(ten_id))
        )
        result: NoticeIngestResult = await ingest_notice(
            session,
            llm=llm,
            download=download,
            notice_id=nid,
            tenant_id=ten_id,
            chunk_max_tokens=tuning.chunk_max_tokens,
        )

    # 색인 시 캐시 세대 증가 → 이전 답변 캐시 무효화(H4-2, ingest_document_task와 동일). fail-open.
    redis = ctx.get("redis")
    if redis is not None and result.status == "indexed":
        with contextlib.suppress(RedisError):
            await redis.incr(f"cache:gen:{ten_id}")

    return {"status": result.status, "chunks": result.chunk_count}


async def startup(ctx: dict[str, Any]) -> None:  # pragma: no cover — 배선 전용
    engine = create_engine()
    # 접속 롤 검증 — RLS 이중 방어 2층은 접속 롤이 BYPASSRLS·superuser가 아닐 때만 성립한다
    # (H10-2, docs/03 §5.1). 워커는 WORKER_DATABASE_URL(liviq_worker)로 접속해야 한다.
    # local 개발 DB는 superuser 단일 롤이라 경고만 남기고 계속 진행한다.
    async with engine.connect() as conn:
        try:
            await assert_no_rls_bypass(conn)
        except RuntimeRoleError:
            if get_settings().api_env == "local":
                logger.warning(
                    "접속 롤이 RLS를 우회한다(local이라 계속 진행) — 배포 환경에서는 기동 실패다."
                )
            else:
                raise
    ctx["session_factory"] = create_session_factory(engine)
    ctx["llm"] = LlmClient()
    ctx["download"] = _download_factory()
    graph = GraphClient.from_settings()
    await graph.ensure_constraints_and_index()
    ctx["graph"] = graph


async def shutdown(ctx: dict[str, Any]) -> None:  # pragma: no cover — 배선 전용
    graph: GraphClient | None = ctx.get("graph")
    if graph is not None:
        await graph.close()


class WorkerSettings:  # pragma: no cover — arq가 소비하는 선언
    functions = [
        ingest_document_task,
        ingest_notice_task,
        sync_outbox_task,
        publish_due_notices,
    ]
    # graph-sync는 15초 주기, 예약 공지 발행은 1분 주기(매분 second=0) cron(docs/11 §3.5,
    # ADR-0015). cron_jobs도 arq가 읽는 클래스 속성.
    cron_jobs = [
        cron(sync_outbox_task, second={0, 15, 30, 45}, run_at_startup=False),
        cron(publish_due_notices, second=0, run_at_startup=False),
    ]
    on_startup = startup
    on_shutdown = shutdown
    # arq는 redis_settings를 "속성"으로 읽는다(호출 아님) — 메서드로 두면
    # 'staticmethod' object has no attribute 'host'로 기동 실패. import 시점에
    # env(REDIS_URL)가 필요하므로 테스트 conftest는 더미 env를 선설정한다.
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
