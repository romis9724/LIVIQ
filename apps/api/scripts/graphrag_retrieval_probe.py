"""graphrag_retrieval_probe.py — 백엔드 검색 품질 직접 측정 (H15-2 부록).

MEASUREMENT-LOG R25 방법론 발견: 병렬 쌍 인용 지표는 "모델이 어느 백엔드로 라우팅하나"를
잴 뿐(8B는 문서, 14B는 그래프로 라우팅), 백엔드 자체의 **검색 품질**을 못 잰다. 이 스크립트는
LLM·라우팅을 통째로 우회하고, 같은 질문 임베딩을 pgvector·Neo4j 검색 경로에 **직접** 넣어
정답 타깃이 top-k에 올라오는지(hit@k)·rank·지연을 잰다 → 순수 검색 품질 분리.

측정 대상은 겹침 문서(pgvector)와 incident 노드(Neo4j)가 by construction 동일한 장애를
담는 병렬 10쌍(graphrag-cases-draft.csv subcategory=병렬-문서, pair_id p01~p10). 타깃은
런타임에 PG에서 해석한다(incident.symptom ILIKE 키워드 / 겹침 문서 id).

실행(컨테이너 — DB·임베딩·Neo4j 엔드포인트는 env·ai_backend_config가 자동):

    docker exec liviq-prod-api-1 python /tmp/scripts/graphrag_retrieval_probe.py --k 8
    # 여러 k: --k 4,8,16   라벨: --label retrieval-probe

이 스크립트는 읽기 전용이다(검색·조회만, 쓰기·커밋 없음).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient
from ai_core.rag.retrieval import PgVectorRetriever
from liviq_db.engine import create_engine, create_session_factory

# scripts/data는 namespace package 관례 — 겹침 문서 제목 상수를 시드와 단일 출처로 공유한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.graph_overlap_doc import OVERLAP_DOC_TITLE  # noqa: E402

# 파일럿 단지(첫마을 4단지 푸르지오) — 시드 스크립트와 동일 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
# MANAGER 공개범위 전체 — 겹침 문서(visibility=ADMIN)가 검색에 보이도록 최대치로 준다.
ALL_VISIBILITIES = ("ALL", "RESIDENT", "ADMIN")
DEFAULT_K = "8"
DEFAULT_LABEL = "retrieval-probe"
# 리포지토리 상대 저장 경로 — 컨테이너에 없으면 /tmp로 폴백(존재 가드).
RESULTS_SUBPATH = "evals/results/rag500"


@dataclass(frozen=True)
class ProbePair:
    """병렬 쌍 1건: 질문 + 정답 타깃 키워드(incident.symptom ILIKE, 겹침 문서 본문 substring)."""

    pair_id: str
    question: str
    keyword: str


# graphrag-cases-draft.csv subcategory=병렬-문서 turn_1 10건 + 브리프 타깃 키워드.
# CSV·키워드가 서로 다른 출처(질문은 CSV, 키워드는 SEED-PLAN)라 여기서 단일 상수로 고정한다
# — 컨테이너에는 eval fixtures가 없으므로 하드코딩이 CSV 파싱보다 견고하다.
PROBE_PAIRS: tuple[ProbePair, ...] = (
    ProbePair(
        "p01",
        "승강기 주로프 마모로 문제가 있었던 적 있나요? 원인과 조치가 궁금합니다.",
        "주로프 마모 진행",
    ),
    ProbePair(
        "p02",
        "404동 승강기 주로프에 이상이 있었나요? 원인과 조치를 알려주세요.",
        "404동 2호기 승강기 주로프",
    ),
    ProbePair(
        "p03",
        "부스터펌프에 진동 문제가 있었나요? 원인과 조치가 궁금합니다.",
        "부스터펌프 1호기 진동 증가",
    ),
    ProbePair(
        "p04",
        "지역난방 열교환기 차압조절밸브에 문제가 있었던 적 있나요? 원인과 조치를 알려주세요.",
        "차압조절밸브",
    ),
    ProbePair(
        "p05",
        "화재수신반 중계기 통신 불량이 있었나요? 원인과 조치가 궁금합니다.",
        "중계기 통신 불량 반복",
    ),
    ProbePair(
        "p06",
        "스프링클러 헤드에서 누수가 있었나요? 원인과 조치를 알려주세요.",
        "스프링클러 헤드",
    ),
    ProbePair(
        "p07",
        "지하주차장 환기팬 소음 문제가 있었나요? 원인과 조치가 궁금합니다.",
        "환기팬 3호기 소음",
    ),
    ProbePair(
        "p08",
        "홈네트워크 서버 고장으로 월패드에 문제가 있었나요? 원인과 조치를 알려주세요.",
        "홈네트워크 서버 고장",
    ),
    ProbePair(
        "p09",
        "놀이터 미끄럼틀 이음부에 문제가 있었나요? 원인과 조치가 궁금합니다.",
        "미끄럼틀 이음부",
    ),
    ProbePair(
        "p10",
        "EV충전기 통신 오류가 있었나요? 원인과 조치를 알려주세요.",
        "EV충전기 3번기 통신",
    ),
)


# ── 타깃 해석 (런타임, PG) ──────────────────────────────────────────────────────


async def _set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """RLS tenant 컨텍스트 — pgvector 검색·타깃 조회 모두 이 tenant 행을 봐야 한다(규칙 3)."""
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )


async def _resolve_graph_target(
    session: AsyncSession, tenant_id: uuid.UUID, keyword: str
) -> str | None:
    """Neo4j 타깃 = 키워드 매칭 incident의 pg_id(str). 가장 이른 발생분 1건, 0건이면 None."""
    row = await session.execute(
        text(
            "SELECT id FROM incidents "
            "WHERE tenant_id = CAST(:t AS uuid) AND symptom ILIKE :kw "
            "ORDER BY occurred_at NULLS LAST LIMIT 1"
        ).bindparams(t=str(tenant_id), kw=f"%{keyword}%")
    )
    incident_id = row.scalar_one_or_none()
    return str(incident_id) if incident_id is not None else None


async def _resolve_overlap_doc_id(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID | None:
    """pgvector 타깃 = 겹침 문서 id(제목 단일 매칭). 0건이면 None(전체 pg 측정 비활성)."""
    row = await session.execute(
        text(
            "SELECT id FROM documents "
            "WHERE tenant_id = CAST(:t AS uuid) AND title = :title AND deleted_at IS NULL LIMIT 1"
        ).bindparams(t=str(tenant_id), title=OVERLAP_DOC_TITLE)
    )
    doc_id = row.scalar_one_or_none()
    return doc_id if doc_id is not None else None


# ── hit 판정 ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BackendResult:
    """한 백엔드·한 k의 측정 결과. skipped면 타깃 미해석(hit·rank None)."""

    hit: bool
    rank: int | None  # 타깃의 1-base 순위, top-k에 없으면 None
    top1_score: float | None
    search_ms: float
    skipped: bool = False


def _skipped() -> BackendResult:
    return BackendResult(hit=False, rank=None, top1_score=None, search_ms=0.0, skipped=True)


def _pgvector_hit(chunks: list[Any], doc_id: uuid.UUID, keyword: str) -> tuple[bool, int | None]:
    """겹침 문서 청크 중 키워드를 담은 첫 청크의 rank(1-base). 없으면 (False, None)."""
    for index, chunk in enumerate(chunks):
        if chunk.document_id == doc_id and keyword in chunk.content:
            return True, index + 1
    return False, None


def _graph_hit(hits: list[Any], target_pg_id: str) -> tuple[bool, int | None]:
    """타깃 incident pg_id가 나온 첫 순위(1-base). 없으면 (False, None)."""
    for index, hit in enumerate(hits):
        if hit.pg_id == target_pg_id:
            return True, index + 1
    return False, None


# ── 측정 ────────────────────────────────────────────────────────────────────


async def _probe_pair(
    session: AsyncSession,
    graph: GraphClient,
    llm: LlmClient,
    tenant_id: uuid.UUID,
    pair: ProbePair,
    k_values: list[int],
    overlap_doc_id: uuid.UUID | None,
) -> dict[str, Any]:
    """쌍 1건: 임베딩 1회(공통) → 각 k에서 pg·graph 검색. 지연은 호출별 분리 계측."""
    embed_start = time.perf_counter()
    vectors = await llm.embed([pair.question])
    embed_ms = (time.perf_counter() - embed_start) * 1000
    query_vector = vectors[0]

    graph_target = await _resolve_graph_target(session, tenant_id, pair.keyword)
    if graph_target is None:
        print(
            f"  [warn] {pair.pair_id} graph 타깃 미해석"
            f"(symptom ILIKE '%{pair.keyword}%' 0건) — graph skip"
        )
    if overlap_doc_id is None:
        print(f"  [warn] {pair.pair_id} pgvector 타깃(겹침 문서) 미해석 — pgvector skip")

    by_k: dict[str, dict[str, Any]] = {}
    for k in k_values:
        pg = await _measure_pgvector(
            session, query_vector, tenant_id, k, overlap_doc_id, pair.keyword
        )
        gr = await _measure_graph(graph, query_vector, tenant_id, k, graph_target)
        by_k[str(k)] = {"pgvector": _as_dict(pg), "neo4j": _as_dict(gr)}

    return {
        "pair_id": pair.pair_id,
        "keyword": pair.keyword,
        "question": pair.question,
        "embed_ms": round(embed_ms, 1),
        "graph_target": graph_target,
        "overlap_doc_id": str(overlap_doc_id) if overlap_doc_id else None,
        "by_k": by_k,
    }


async def _measure_pgvector(
    session: AsyncSession,
    query_vector: list[float],
    tenant_id: uuid.UUID,
    k: int,
    overlap_doc_id: uuid.UUID | None,
    keyword: str,
) -> BackendResult:
    if overlap_doc_id is None:
        return _skipped()
    retriever = PgVectorRetriever(session)
    start = time.perf_counter()
    chunks = await retriever.search(
        query_embedding=query_vector,
        tenant_id=tenant_id,
        visibilities=ALL_VISIBILITIES,
        top_k=k,
    )
    search_ms = (time.perf_counter() - start) * 1000
    hit, rank = _pgvector_hit(chunks, overlap_doc_id, keyword)
    top1 = chunks[0].score if chunks else None
    return BackendResult(hit=hit, rank=rank, top1_score=top1, search_ms=round(search_ms, 1))


async def _measure_graph(
    graph: GraphClient,
    query_vector: list[float],
    tenant_id: uuid.UUID,
    k: int,
    graph_target: str | None,
) -> BackendResult:
    if graph_target is None:
        return _skipped()
    start = time.perf_counter()
    hits = await graph.search_incidents(tenant_id=str(tenant_id), query_vector=query_vector, k=k)
    search_ms = (time.perf_counter() - start) * 1000
    hit, rank = _graph_hit(hits, graph_target)
    top1 = hits[0].score if hits else None
    return BackendResult(hit=hit, rank=rank, top1_score=top1, search_ms=round(search_ms, 1))


def _as_dict(result: BackendResult) -> dict[str, Any]:
    return {
        "hit": result.hit,
        "rank": result.rank,
        "top1_score": round(result.top1_score, 4) if result.top1_score is not None else None,
        "search_ms": result.search_ms,
        "skipped": result.skipped,
    }


# ── 집계·출력 ──────────────────────────────────────────────────────────────


def _aggregate(results: list[dict[str, Any]], k_values: list[int]) -> dict[str, Any]:
    """k별·백엔드별 hit@k 비율·평균 rank(hit만)·평균 지연(측정 건만)."""
    aggregate: dict[str, Any] = {}
    for k in k_values:
        key = str(k)
        aggregate[key] = {
            "pgvector": _aggregate_backend(results, key, "pgvector"),
            "neo4j": _aggregate_backend(results, key, "neo4j"),
        }
    return aggregate


def _aggregate_backend(results: list[dict[str, Any]], k_key: str, backend: str) -> dict[str, Any]:
    measured = [
        r["by_k"][k_key][backend] for r in results if not r["by_k"][k_key][backend]["skipped"]
    ]
    n = len(measured)
    hits = [m for m in measured if m["hit"]]
    ranks = [m["rank"] for m in hits if m["rank"] is not None]
    latencies = [m["search_ms"] for m in measured]
    return {
        "n": n,
        "hit_at_k": round(len(hits) / n, 3) if n else None,
        "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "avg_search_ms": round(sum(latencies) / len(latencies), 1) if latencies else None,
    }


def _print_report(
    results: list[dict[str, Any]], aggregate: dict[str, Any], k_values: list[int]
) -> None:
    for k in k_values:
        key = str(k)
        print(f"\n=== k={k} ===")
        header = (
            f"{'pair':<5} {'keyword':<24} | pg hit/rank/score/ms          | neo4j hit/rank/score/ms"
        )
        print(header)
        print("-" * len(header))
        for r in results:
            pg = r["by_k"][key]["pgvector"]
            gr = r["by_k"][key]["neo4j"]
            print(f"{r['pair_id']:<5} {r['keyword'][:24]:<24} | {_cell(pg):<30} | {_cell(gr)}")
        agg = aggregate[key]
        print(
            f"\n  집계 pgvector: hit@{k}={agg['pgvector']['hit_at_k']} "
            f"avg_rank={agg['pgvector']['avg_rank']} avg_ms={agg['pgvector']['avg_search_ms']} "
            f"(n={agg['pgvector']['n']})"
        )
        print(
            f"  집계 neo4j   : hit@{k}={agg['neo4j']['hit_at_k']} "
            f"avg_rank={agg['neo4j']['avg_rank']} avg_ms={agg['neo4j']['avg_search_ms']} "
            f"(n={agg['neo4j']['n']})"
        )


def _cell(m: dict[str, Any]) -> str:
    if m["skipped"]:
        return "skip"
    score = f"{m['top1_score']:.3f}" if m["top1_score"] is not None else "-"
    rank = m["rank"] if m["rank"] is not None else "-"
    hit = "Y" if m["hit"] else "n"
    return f"{hit} r={rank} s={score} {m['search_ms']}ms"


def _output_path(label: str) -> Path:
    """리포지토리 상대 결과 경로 — 없으면 /tmp 폴백(컨테이너 실행은 parents 얕아 IndexError 회피)."""
    parents = Path(__file__).resolve().parents
    out_dir = parents[3] / RESULTS_SUBPATH if len(parents) > 3 else Path("/tmp")
    if not out_dir.is_dir():
        out_dir = Path("/tmp")
    return out_dir / f"graphrag-retrieval-{label}.json"


# ── 엔트리포인트 ────────────────────────────────────────────────────────────


def _parse_k(raw: str) -> list[int]:
    """'4,8,16' → [4, 8, 16]. 빈 값·비정수는 fail-fast(경계 검증)."""
    values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    if not values:
        raise ValueError(f"--k 파싱 실패: {raw!r}")
    return values


async def _run(tenant_id: uuid.UUID, k_values: list[int], label: str) -> None:
    engine = create_engine()
    session_factory = create_session_factory(engine)
    llm = LlmClient()
    graph = GraphClient.from_settings()
    try:
        async with session_factory() as session:
            await _set_tenant(session, tenant_id)
            overlap_doc_id = await _resolve_overlap_doc_id(session, tenant_id)
            results = [
                await _probe_pair(session, graph, llm, tenant_id, pair, k_values, overlap_doc_id)
                for pair in PROBE_PAIRS
            ]
    finally:
        await graph.close()
        await engine.dispose()

    aggregate = _aggregate(results, k_values)
    _print_report(results, aggregate, k_values)

    payload = {
        "label": label,
        "tenant_id": str(tenant_id),
        "generated_at": datetime.now(UTC).isoformat(),
        "k_values": k_values,
        "overlap_doc_title": OVERLAP_DOC_TITLE,
        "results": results,
        "aggregate": aggregate,
    }
    out_path = _output_path(label)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nJSON 저장: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="pgvector·Neo4j 검색 품질 직접 비교(hit@k·rank·지연)"
    )
    parser.add_argument("--k", default=DEFAULT_K, help="top-k(쉼표 다중, 예: 4,8,16). 기본 8")
    parser.add_argument("--label", default=DEFAULT_LABEL, help="결과 파일 라벨")
    parser.add_argument(
        "--tenant-id", default=str(DEFAULT_TENANT_ID), help="측정 대상 tenant(기본 첫마을)"
    )
    args = parser.parse_args()
    asyncio.run(_run(uuid.UUID(args.tenant_id), _parse_k(args.k), args.label))


if __name__ == "__main__":
    main()
