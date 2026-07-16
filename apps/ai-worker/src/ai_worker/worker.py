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
from arq.connections import RedisSettings
from sqlalchemy import text

from ai_core.llm.client import LlmClient
from ai_worker.config import get_settings
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


async def shutdown(ctx: dict[str, Any]) -> None:  # pragma: no cover — 배선 전용
    pass


class WorkerSettings:  # pragma: no cover — arq가 소비하는 선언
    functions = [ingest_document_task]
    on_startup = startup
    on_shutdown = shutdown

    @staticmethod
    def redis_settings() -> RedisSettings:
        return RedisSettings.from_dsn(get_settings().redis_url)
