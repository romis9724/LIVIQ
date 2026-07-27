"""drain_outbox.py — pending outbox_events를 1회 처리(H13-6, docs/03 §4.9).

ai-worker를 상시 기동하지 않고도 로컬에서 outbox → Neo4j 반영을 확인하기 위한 1회성
러너다. `sync_outbox_task`가 배치(최대 100건, `graph_sync.BATCH_SIZE`)를 claim해 처리
하므로, pending이 100건을 넘으면 남는 만큼 재실행한다(--until-empty로 자동 반복).

실행(DATABASE_URL·REDIS_URL 불필요 — redis/arq 큐 자체는 건드리지 않음):

    cd apps/ai-worker
    uv run --no-sync python scripts/drain_outbox.py [--until-empty]
"""

from __future__ import annotations

import argparse
import asyncio

from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient
from ai_worker.graph_sync import sync_outbox_task
from liviq_db.engine import create_engine, create_session_factory


async def _run(until_empty: bool) -> None:
    engine = create_engine()
    graph = GraphClient.from_settings()
    await graph.ensure_constraints_and_index()
    ctx = {
        "session_factory": create_session_factory(engine),
        "graph": graph,
        "llm": LlmClient(),
    }
    try:
        while True:
            result = await sync_outbox_task(ctx)
            print(f"processed={result['processed']} failed={result['failed']}")
            if not until_empty or result["processed"] == 0:
                break
    finally:
        await graph.close()
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="pending outbox 1회(또는 소진까지) 처리")
    parser.add_argument(
        "--until-empty", action="store_true", help="pending이 없어질 때까지 반복 처리"
    )
    args = parser.parse_args()
    asyncio.run(_run(args.until_empty))


if __name__ == "__main__":
    main()
