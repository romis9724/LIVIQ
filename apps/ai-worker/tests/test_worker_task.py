"""arq 태스크 배선 테스트 — 실 PG 세션 팩토리 + 가짜 LLM/다운로더."""

from __future__ import annotations

from conftest import RULES_TEXT
from conftest import seed_document as _seed_document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ai_core.llm.client import LlmClient
from ai_worker.worker import ingest_document_task
from liviq_db.models import Document, Tenant


async def test_ingest_task_runs_with_tenant_context(pg_dsn: str, fake_llm: LlmClient) -> None:
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    # 시드는 커밋(태스크가 자체 세션·트랜잭션으로 읽음) — 종료 시 직접 정리
    async with factory() as seed_session, seed_session.begin():
        tenant_id, doc_id = await _seed_document(seed_session, storage_key="t/task.txt")

    async def download(storage_key: str) -> bytes:
        return RULES_TEXT.encode()

    from fakeredis.aioredis import FakeRedis

    redis = FakeRedis(decode_responses=True)
    ctx = {
        "session_factory": factory,
        "llm": fake_llm,
        "download": download,
        "redis": redis,
    }
    try:
        result = await ingest_document_task(ctx, str(doc_id), str(tenant_id))
        assert result["status"] == "indexed"
        assert result["chunks"] == 2

        async with factory() as check:
            status = await check.scalar(select(Document.index_status).where(Document.id == doc_id))
        assert status == "indexed"

        # 색인 성공 → 캐시 세대 증가(H4-2 무효화). 키 포맷은 answer_cache와 동일.
        assert await redis.get(f"cache:gen:{tenant_id}") == "1"
    finally:
        await redis.aclose()
        # 커밋된 시드 정리(tenant CASCADE로 문서·청크까지)
        async with factory() as cleanup, cleanup.begin():
            tenant = await cleanup.get(Tenant, tenant_id)
            if tenant is not None:
                await cleanup.delete(tenant)
        await engine.dispose()
