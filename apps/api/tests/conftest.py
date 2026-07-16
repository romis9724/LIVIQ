"""api 테스트 공용 — 실 PG(testcontainers) + 의존성 오버라이드(스토리지·큐·LLM).

app.main·config 임포트 시점 env 검증을 통과시키기 위해 더미 env를 먼저 설정한다.
"""

from __future__ import annotations

import base64
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from app.session import SessionStore
    from fakeredis.aioredis import FakeRedis

os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9002")
os.environ.setdefault("S3_ACCESS_KEY_ID", "test")
os.environ.setdefault("S3_SECRET_ACCESS_KEY", "test")
# 봉투 암호화 KEK — 32byte base64 더미(ADR-0010, fail-closed 검증용).
os.environ.setdefault("PII_MASTER_KEY", base64.b64encode(b"0" * 32).decode())

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool  # noqa: E402

from ai_core.config import AiCoreSettings  # noqa: E402
from ai_core.llm.client import LlmClient  # noqa: E402

_DB_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "packages" / "db"
EMBED_DIM = 1024


def _ensure_docker_host() -> None:
    if os.environ.get("DOCKER_HOST"):
        return
    sock = Path.home() / ".colima" / "default" / "docker.sock"
    if sock.exists():
        os.environ["DOCKER_HOST"] = f"unix://{sock}"


_ensure_docker_host()
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture(scope="session")
def pg_dsn() -> Iterator[str]:
    from alembic import command
    from alembic.config import Config
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
async def db_session(pg_dsn: str) -> AsyncIterator[AsyncSession]:
    """테스트별 트랜잭션 롤백 세션(tenant 컨텍스트는 각 테스트에서 설정)."""
    engine = create_async_engine(pg_dsn, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        trans = await session.begin()
        try:
            yield session
        finally:
            await trans.rollback()
            await engine.dispose()


@pytest.fixture
def fake_llm() -> LlmClient:
    """임베딩 고정 벡터 + chat_stream은 요청별 지정 응답(디폴트: 근거 [1] 인용)."""
    settings = AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="test",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )
    answer = os.environ.get("_TEST_LLM_ANSWER", "24시간 개방합니다 [1].")

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        if request.url.path.endswith("/embeddings"):
            texts = json.loads(request.content)["input"]
            data = [{"index": i, "embedding": [0.05] * EMBED_DIM} for i in range(len(texts))]
            return httpx.Response(200, json={"data": data})
        sse = "\n\n".join(
            [
                f"data: {json.dumps({'choices': [{'delta': {'content': answer}}]})}",
                "data: [DONE]",
                "",
            ]
        )
        return httpx.Response(200, content=sse.encode())

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


@pytest_asyncio.fixture
async def fake_redis() -> AsyncIterator[FakeRedis]:
    from fakeredis.aioredis import FakeRedis

    redis = FakeRedis(decode_responses=True)
    try:
        yield redis
    finally:
        await redis.aclose()


@pytest.fixture
def session_store(fake_redis: FakeRedis) -> SessionStore:
    from app.session import SessionStore

    return SessionStore(fake_redis)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue(self, task: str, *args: object) -> None:
        self.jobs.append((task, args))


TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

GOOGLE_SUB = "google-sub-fixed-001"


class FakeOAuthProvider:
    """OAuthProvider 오버라이드 — 고정 sub/email 반환(네트워크 없음)."""

    def __init__(self, sub: str = GOOGLE_SUB, email: str | None = None) -> None:
        self.sub = sub
        self.email = email

    def authorize_url(self, state: str, code_challenge: str) -> str:
        return (
            "https://accounts.google.com/o/oauth2/v2/auth"
            f"?state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
        )

    async def exchange(self, code: str, code_verifier: str) -> object:
        from app.oauth import OAuthIdentity

        return OAuthIdentity(sub=self.sub, email=self.email)
