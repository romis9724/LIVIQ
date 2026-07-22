"""ai-worker 테스트 — 실 PG(testcontainers) + LLM은 MockTransport (네트워크 금지).

RLS 격리 검증은 packages/db 소유(CRITICAL 스위트) — 여기선 인제스트 로직만 본다.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient

_DB_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "packages" / "db"


def _ensure_docker_host() -> None:
    if os.environ.get("DOCKER_HOST"):
        return
    colima_sock = Path.home() / ".colima" / "default" / "docker.sock"
    if colima_sock.exists():
        os.environ["DOCKER_HOST"] = f"unix://{colima_sock}"


_ensure_docker_host()
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

# ai_worker.worker가 import 시점에 WorkerSettings.redis_settings를 평가(env 필요) —
# 더미 env 선설정(연결 안 함, apps/api conftest와 동일 패턴).
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9002")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test")
# graph-sync는 GraphClient를 지연 생성(startup 시점)하지만, 더미 NEO4J_* 선설정으로
# 어떤 import 경로에서도 부팅 실패가 없게 한다(연결은 하지 않음).
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7688")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "liviqlocal")


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16", driver="asyncpg") as pg:
        dsn = pg.get_connection_url()
        os.environ["DATABASE_URL"] = dsn
        from liviq_db.config import get_settings

        get_settings.cache_clear()
        cfg = Config()
        cfg.set_main_option("script_location", str(_DB_ROOT / "alembic"))
        command.upgrade(cfg, "head")
        yield dsn


@pytest_asyncio.fixture
async def session(pg_dsn: str) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        trans = await s.begin()
        try:
            yield s
        finally:
            await trans.rollback()
            await engine.dispose()


EMBED_DIM = 1024

RULES_TEXT = "제1조 목적\n관리 규약의 목적을 정한다.\n\n제2조 주차\n지하주차장은 24시간 개방한다."


async def seed_document(session: AsyncSession, *, storage_key: str) -> tuple[uuid.UUID, uuid.UUID]:
    """tenant + DOC_CATEGORY 코드 + pending 문서(+ v1 첨부) 시드 — (tenant_id, document_id) 반환."""
    from liviq_db.models import Code, CodeGroup, Document, DocumentVersion, Tenant

    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    group = CodeGroup(
        tenant_id=tenant.id, group_key="DOC_CATEGORY", name="문서 카테고리", is_system=True
    )
    session.add(group)
    await session.flush()
    code = Code(tenant_id=tenant.id, group_id=group.id, code="규약", label="규약")
    session.add(code)
    await session.flush()
    doc = Document(
        tenant_id=tenant.id,
        title="관리규약",
        category_code_id=code.id,
        visibility="ALL",
        version=1,
        index_status="pending",
    )
    session.add(doc)
    await session.flush()
    session.add(
        DocumentVersion(
            tenant_id=tenant.id,
            document_id=doc.id,
            version=1,
            filename=storage_key.rsplit("/", 1)[-1],
            content_type="text/plain",
            size_bytes=1,
            storage_key=storage_key,
            content_hash=f"hash-{storage_key}",
        )
    )
    await session.flush()
    return tenant.id, doc.id


@pytest.fixture
def fake_llm() -> LlmClient:
    """임베딩만 쓰는 가짜 LLM — 입력 개수만큼 고정 벡터 반환."""
    settings = AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="test",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        texts = json.loads(request.content)["input"]
        data = [{"index": i, "embedding": [0.01] * EMBED_DIM} for i in range(len(texts))]
        return httpx.Response(200, json={"data": data})

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)
