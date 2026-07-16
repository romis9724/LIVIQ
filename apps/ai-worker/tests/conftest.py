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
    """tenant + pending 문서 시드 — (tenant_id, document_id) 반환."""
    from liviq_db.models import Document, Tenant

    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    doc = Document(
        tenant_id=tenant.id,
        title="관리규약",
        source_type="규약",
        visibility="ALL",
        storage_key=storage_key,
        content_hash=f"hash-{storage_key}",
        index_status="pending",
    )
    session.add(doc)
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
