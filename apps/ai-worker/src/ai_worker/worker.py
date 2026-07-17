"""arq 워커 — 큐 태스크 등록·실행 진입점 (docs/01 §8, ADR-0013).

실행: `uv run --no-sync arq ai_worker.worker.WorkerSettings`
태스크는 이벤트 claim 후 해당 tenant로 `SET LOCAL app.tenant_id` — BYPASSRLS 없이
RLS를 그대로 받는다(docs/03 §5). jobs 테이블로 상태 추적(docs/03 §4.7).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import boto3
from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import text

from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient
from ai_worker.config import get_settings
from ai_worker.graph_sync import sync_outbox_task
from ai_worker.ingest import IngestResult, ingest_document
from liviq_db.engine import create_engine, create_session_factory


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
    llm: LlmClient = ctx["llm"]
    download = ctx["download"]
    doc_id, ten_id = uuid.UUID(document_id), uuid.UUID(tenant_id)

    async with session_factory() as session, session.begin():
        # tenant 컨텍스트 — RLS 이중 방어의 1층(docs/03 §5)
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(ten_id))
        )
        result: IngestResult = await ingest_document(
            session, llm=llm, download=download, document_id=doc_id, tenant_id=ten_id
        )
    return {"status": result.status, "chunks": result.chunk_count, "error": result.error}


async def startup(ctx: dict[str, Any]) -> None:  # pragma: no cover — 배선 전용
    ctx["session_factory"] = create_session_factory(create_engine())
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
    functions = [ingest_document_task, sync_outbox_task]
    # graph-sync는 15초 주기 cron(docs/11 §3.5). cron_jobs도 arq가 읽는 클래스 속성.
    cron_jobs = [cron(sync_outbox_task, second={0, 15, 30, 45}, run_at_startup=False)]
    on_startup = startup
    on_shutdown = shutdown
    # arq는 redis_settings를 "속성"으로 읽는다(호출 아님) — 메서드로 두면
    # 'staticmethod' object has no attribute 'host'로 기동 실패. import 시점에
    # env(REDIS_URL)가 필요하므로 테스트 conftest는 더미 env를 선설정한다.
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
