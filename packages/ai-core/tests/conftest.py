"""ai-core 테스트 공용 — 네트워크 금지, settings는 env 무관하게 직접 구성.

그래프 테스트는 Neo4jContainer(실 Neo4j) 사용 — 벡터 인덱스·MERGE·tenant 격리를
모킹 없이 검증한다(격리는 CRITICAL, docs/07 §3).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from ai_core.config import AiCoreSettings
from ai_core.graph import GraphClient

_NEO4J_PASSWORD = "liviqtestpw"


def _ensure_docker_host() -> None:
    if os.environ.get("DOCKER_HOST"):
        return
    colima_sock = Path.home() / ".colima" / "default" / "docker.sock"
    if colima_sock.exists():
        os.environ["DOCKER_HOST"] = f"unix://{colima_sock}"


_ensure_docker_host()
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")


@pytest.fixture
def settings() -> AiCoreSettings:
    return AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="test-model",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )


# ── 도구 SQL 테스트용 가짜 세션(raw text() SELECT 전용) ──────────────────────
#
# 도구는 retrieval.py처럼 raw SQL을 주입 세션으로 실행한다. 단위 테스트는 SQL을 실제
# 실행하지 않고, 쿼리 텍스트로 분기해 준비된 행을 돌려주는 가짜 세션으로 포매팅·소유권
# 분기 로직을 커버한다(실 PG·RLS·규칙8 무변경 검증은 apps/api 통합 테스트가 담당).


def row(**fields: Any) -> SimpleNamespace:
    """SQLAlchemy Row 흉내 — 속성 접근(`row.total_amount`)만 지원."""
    return SimpleNamespace(**fields)


class FakeResult:
    def __init__(self, rows: Sequence[SimpleNamespace]) -> None:
        self._rows = list(rows)

    def first(self) -> SimpleNamespace | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[SimpleNamespace]:
        return list(self._rows)

    def __iter__(self) -> Iterator[SimpleNamespace]:
        return iter(self._rows)


class FakeSession:
    """handler(sql, params) -> rows 로 응답하는 가짜 AsyncSession(execute만 제공)."""

    def __init__(self, handler: Callable[[str, dict[str, Any]], Sequence[SimpleNamespace]]) -> None:
        self._handler = handler
        self.executed: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> FakeResult:
        sql = str(stmt)
        self.executed.append((sql, params or {}))
        return FakeResult(self._handler(sql, params or {}))


@pytest.fixture(scope="session")
def neo4j_auth() -> Iterator[tuple[str, str, str]]:
    """(uri, user, password) — 세션 1회 컨테이너 기동."""
    from testcontainers.neo4j import Neo4jContainer

    with Neo4jContainer("neo4j:5-community", password=_NEO4J_PASSWORD) as container:
        yield container.get_connection_url(), "neo4j", _NEO4J_PASSWORD


@pytest_asyncio.fixture
async def graph(neo4j_auth: tuple[str, str, str]) -> AsyncIterator[GraphClient]:
    """초기화된 GraphClient — 각 테스트 전 노드 전체 삭제(제약·인덱스는 유지)."""
    from neo4j import AsyncGraphDatabase

    uri, user, password = neo4j_auth
    driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
    await driver.execute_query("MATCH (n) DETACH DELETE n", database_="neo4j")
    client = GraphClient(driver)
    await client.ensure_constraints_and_index()
    try:
        yield client
    finally:
        await client.close()
