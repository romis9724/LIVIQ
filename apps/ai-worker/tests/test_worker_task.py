"""arq 태스크 배선 테스트 — 실 PG 세션 팩토리 + 가짜 LLM/다운로더."""

from __future__ import annotations

import httpx
from conftest import EMBED_DIM, RULES_TEXT
from conftest import seed_document as _seed_document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ai_core.backend_config import CONFIG_ROW_ID
from ai_core.llm.client import LlmClient
from ai_worker.worker import ingest_document_task, ingest_notice_task
from liviq_db.models import AiBackendConfig, ContentChunk, Document, Notice, Tenant


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


async def test_ingest_notice_task_runs_with_tenant_context(
    pg_dsn: str, fake_llm: LlmClient
) -> None:
    import datetime

    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as seed_session, seed_session.begin():
        tenant = Tenant(name="t", status="active")
        seed_session.add(tenant)
        await seed_session.flush()
        notice = Notice(
            tenant_id=tenant.id,
            title="발행 공지",
            body="지하주차장은 24시간 개방한다.",
            status="published",
            pinned=False,
            audience="ALL",
            published_at=datetime.datetime.now(datetime.UTC),
        )
        seed_session.add(notice)
        await seed_session.flush()
        tenant_id, notice_id = tenant.id, notice.id

    async def download(storage_key: str) -> bytes:
        return b""

    from fakeredis.aioredis import FakeRedis

    redis = FakeRedis(decode_responses=True)
    ctx = {"session_factory": factory, "llm": fake_llm, "download": download, "redis": redis}
    try:
        result = await ingest_notice_task(ctx, str(notice_id), str(tenant_id))
        assert result["status"] == "indexed"
        assert result["chunks"] >= 1

        async with factory() as check:
            count = await check.scalar(
                select(ContentChunk).where(ContentChunk.notice_id == notice_id)
            )
        assert count is not None
        assert await redis.get(f"cache:gen:{tenant_id}") == "1"  # 색인 → 캐시 무효화
    finally:
        await redis.aclose()
        async with factory() as cleanup, cleanup.begin():
            t = await cleanup.get(Tenant, tenant_id)
            if t is not None:
                await cleanup.delete(t)
        await engine.dispose()


async def test_ingest_task_uses_active_config_for_embedding_and_chunking(pg_dsn: str) -> None:
    """잡 실행마다 `ai_backend_config`를 읽어 임베딩 백엔드·청킹 상한을 따른다(H15-3).

    워커 재시작 없이 관리자 설정이 반영되는지가 요점 — 임베딩 요청 URL과 청크 수로 확인한다.
    """
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as seed_session, seed_session.begin():
        tenant_id, doc_id = await _seed_document(seed_session, storage_key="t/config.txt")
        seed_session.add(
            AiBackendConfig(
                id=CONFIG_ROW_ID,
                base_url="http://db-llm.test/v1",
                model="db-model",
                embedding_base_url="http://db-embed.test/v1",
                embedding_model="db-embed",
                chunk_max_tokens=5,  # 아주 작은 상한 → 기본(400)보다 잘게 쪼개진다
            )
        )

    # 한 문단 3문장 — 기본 상한(400 토큰)이면 1청크, 상한 5면 문장별 3청크.
    async def download(storage_key: str) -> bytes:
        return "제1조 목적\n첫째 문장을 적는다. 둘째 문장을 적는다. 셋째 문장을 적는다.".encode()

    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        payload = json.loads(request.content)
        seen.append((str(request.url), payload["model"]))
        data = [{"index": i, "embedding": [0.01] * EMBED_DIM} for i in range(len(payload["input"]))]
        return httpx.Response(200, json={"data": data})

    from ai_core.config import AiCoreSettings

    env_settings = AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://env-llm.test/v1",
        LLM_MODEL="env-model",
        EMBEDDING_BASE_URL="http://env-embed.test/v1",
        EMBEDDING_MODEL="env-embed",
    )
    ctx = {
        "session_factory": factory,
        "llm": LlmClient(env_settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0),
        "download": download,
    }
    try:
        result = await ingest_document_task(ctx, str(doc_id), str(tenant_id))
        assert result["status"] == "indexed"
        assert result["chunks"] == 3  # 기본 상한이면 1청크 — 노브가 반영됐다
        assert seen and all(url.startswith("http://db-embed.test/v1") for url, _ in seen)
        assert {model for _, model in seen} == {"db-embed"}  # env 아님 = DB 설정 사용
    finally:
        async with factory() as cleanup, cleanup.begin():
            tenant = await cleanup.get(Tenant, tenant_id)
            if tenant is not None:
                await cleanup.delete(tenant)
            config = await cleanup.get(AiBackendConfig, CONFIG_ROW_ID)
            if config is not None:
                await cleanup.delete(config)
        await engine.dispose()
