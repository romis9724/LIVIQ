"""pgvector 벡터 검색 — tenant·visibility 선필터 후 ANN (docs/01 §5.2, 03 §4.2).

세션은 호출자(api)가 tenant 컨텍스트(`app.tenant_id`)를 설정한 것을 받는다 — RLS가
1차 방어, 이 쿼리의 tenant_id 필터가 2차 방어(이중 방어, 규칙 3).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# 벡터로 넉넉히 가져온 뒤 예산으로 절단(docs/08 §3). 리랭커는 후속 과제.
DEFAULT_TOP_K = 8
# 이 유사도(cosine) 미만이면 근거로 취급하지 않는다 — 파일럿 보정 대상.
MIN_SCORE = 0.35


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID | None  # notice 청크는 None(source는 document_title로 표기)
    document_title: str
    content: str
    heading: str | None
    page: int | None
    clause: str | None
    score: float  # cosine 유사도(1 - distance), 높을수록 유사


class Retriever(Protocol):
    """검색 인터페이스 — 테스트는 fake, 운영은 PgVectorRetriever."""

    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        tenant_id: uuid.UUID,
        visibilities: Sequence[str],
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedChunk]: ...


_SEARCH_SQL = text(
    """
    SELECT c.id AS chunk_id, c.document_id,
           COALESCE(d.title, n.title) AS document_title,
           c.content, c.heading, c.page, c.clause,
           1 - (c.embedding <=> CAST(:query_embedding AS vector)) AS score
    FROM content_chunks c
    LEFT JOIN documents d ON d.id = c.document_id AND d.tenant_id = c.tenant_id
    LEFT JOIN notices n ON n.id = c.notice_id AND n.tenant_id = c.tenant_id
    WHERE c.tenant_id = :tenant_id
      AND (
        (c.source_type = 'document'
           AND d.deleted_at IS NULL
           AND d.index_status = 'indexed'
           AND d.visibility = ANY(:visibilities))
        OR
        (c.source_type = 'notice'
           AND n.status = 'published'
           AND n.deleted_at IS NULL)
      )
    ORDER BY c.embedding <=> CAST(:query_embedding AS vector)
    LIMIT :top_k
    """
)
# 문서·공지 다형 검색(H8-3): document는 visibility 조인, notice는 published·미삭제 조인으로
# 미발행 공지 청크를 원천 배제(인제스트 published-only와 함께 이중 방어, CRITICAL). notice
# 청크는 document_id NULL → title은 notices.title로 COALESCE.


class PgVectorRetriever:
    """pgvector cosine ANN. HNSW 인덱스는 초기 마이그레이션에서 생성됨."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def search(
        self,
        query_embedding: Sequence[float],
        *,
        tenant_id: uuid.UUID,
        visibilities: Sequence[str],
        top_k: int = DEFAULT_TOP_K,
    ) -> list[RetrievedChunk]:
        result = await self._session.execute(
            _SEARCH_SQL,
            {
                # asyncpg는 list→vector 인코딩을 모른다 → pgvector 텍스트 리터럴로 바인딩,
                # CAST(:query_embedding AS vector)가 파싱한다.
                "query_embedding": _to_pgvector(query_embedding),
                "tenant_id": tenant_id,
                "visibilities": list(visibilities),
                "top_k": top_k,
            },
        )
        return [
            RetrievedChunk(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_title=row.document_title,
                content=row.content,
                heading=row.heading,
                page=row.page,
                clause=row.clause,
                score=float(row.score),
            )
            for row in result
        ]


def _to_pgvector(embedding: Sequence[float]) -> str:
    """pgvector 텍스트 리터럴: `[0.1,0.2,...]`."""
    return "[" + ",".join(repr(float(x)) for x in embedding) + "]"
