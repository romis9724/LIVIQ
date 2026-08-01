"""공지 벡터 검색 노출 — PgVectorRetriever가 published 공지 청크만 반환 (H8-3, CRITICAL).

실 PG에서 검색 SQL의 notice 조인(published·미삭제)이 미발행 공지 청크를 배제하는지 본다.
draft 공지에 청크를 강제로 심어도 조인 검증으로 걸러져야 한다(인제스트 published-only와 이중 방어).

대상 동 필터(H19-1)도 여기서 본다 — 동별로 쪼개진 공지는 본문이 거의 같아 유사도로 구분되지
않으므로, 배제가 SQL에서 실제로 일어나는지는 실 PG로만 검증된다.
"""

from __future__ import annotations

import datetime
import uuid

from conftest import RULES_TEXT
from conftest import seed_document as _seed_document
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from ai_core.rag.retrieval import PgVectorRetriever
from ai_worker.ingest import Downloader, ingest_document
from ai_worker.ingest_notice import ingest_notice
from liviq_db.models import Building, ContentChunk, Notice, Tenant

_QUERY = "주차 안내"


def _downloader(data: bytes) -> Downloader:
    async def download(storage_key: str) -> bytes:
        return data

    return download


async def _seed_notice(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    status: str,
    title: str | None = None,
    target_buildings: list[str] | None = None,
) -> uuid.UUID:
    now = datetime.datetime.now(datetime.UTC)
    notice = Notice(
        tenant_id=tenant_id,
        title=title or f"{status} 공지",
        body="지하주차장은 24시간 개방한다.",
        status=status,
        pinned=False,
        audience="building" if target_buildings else "ALL",
        target_buildings=target_buildings,
        published_at=now if status == "published" else None,
        scheduled_at=now if status == "scheduled" else None,
    )
    session.add(notice)
    await session.flush()
    return notice.id


async def _force_chunk(session: AsyncSession, tenant_id: uuid.UUID, notice_id: uuid.UUID) -> None:
    """공지에 청크를 인제스트 없이 직접 심는다 — 검색 SQL의 조인·필터만 남겨 검증한다."""
    session.add(
        ContentChunk(
            tenant_id=tenant_id,
            source_type="notice",
            notice_id=notice_id,
            chunk_index=0,
            content="강제 삽입 청크",
            embedding=[0.01] * 1024,
        )
    )
    await session.flush()


async def _search(
    session: AsyncSession,
    llm: LlmClient,
    tenant_id: uuid.UUID,
    *,
    default_top_k: int | None = None,
    building_id: uuid.UUID | None = None,
) -> list:
    query_vec = (await llm.embed([_QUERY]))[0]
    retriever = (
        PgVectorRetriever(session)
        if default_top_k is None
        else PgVectorRetriever(session, default_top_k=default_top_k)
    )
    return await retriever.search(
        query_vec,
        tenant_id=tenant_id,
        visibilities=["ALL", "RESIDENT", "ADMIN"],
        building_id=building_id,
    )


async def test_published_notice_chunks_are_searchable(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    notice_id = await _seed_notice(session, tenant.id, status="published")
    await ingest_notice(
        session, llm=fake_llm, download=_downloader(b""), notice_id=notice_id, tenant_id=tenant.id
    )

    results = await _search(session, fake_llm, tenant.id)
    notice_hits = [r for r in results if r.document_id is None]
    assert notice_hits, "published 공지 청크가 검색에 노출되지 않음"
    assert notice_hits[0].document_title == "published 공지"  # title=공지 제목


async def test_draft_and_deleted_notice_chunks_excluded(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    draft_id = await _seed_notice(session, tenant.id, status="draft")
    scheduled_id = await _seed_notice(session, tenant.id, status="scheduled")
    await _force_chunk(session, tenant.id, draft_id)
    await _force_chunk(session, tenant.id, scheduled_id)

    results = await _search(session, fake_llm, tenant.id)
    assert results == [], "미발행 공지 청크가 검색에 노출됨(CRITICAL 위반)"


# ── 대상 동 필터(H19-1, ADR-0026 결정 1) ─────────────────────────────────


_ALL_DONG_TITLES = ("전체동 단수 안내", "전체동 소방 점검")


async def _seed_dong_notices(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """401동·403동 공지 + 전체동 공지 2형태를 청크까지 심는다 — (tenant, 401 id, 403 id).

    전체동은 저장 형태가 둘이다 — ORM이 파이썬 None을 jsonb 'null'로 넣는 쪽(작성 경로가
    실제로 만드는 값)과 SQL NULL 쪽. 둘 다 통과해야 회귀가 없다.
    """
    tenant = Tenant(name="t", status="active")
    session.add(tenant)
    await session.flush()
    b401 = Building(tenant_id=tenant.id, name="401")
    b403 = Building(tenant_id=tenant.id, name="403")
    session.add_all([b401, b403])
    await session.flush()
    for title, targets in (
        ("401동 승강기 점검", [str(b401.id)]),
        ("403동 승강기 점검", [str(b403.id)]),
        (_ALL_DONG_TITLES[0], None),
        (_ALL_DONG_TITLES[1], None),
    ):
        notice_id = await _seed_notice(
            session, tenant.id, status="published", title=title, target_buildings=targets
        )
        await _force_chunk(session, tenant.id, notice_id)
    await session.execute(
        text(
            "UPDATE notices SET target_buildings = NULL WHERE tenant_id = :tid AND title = :title"
        ),
        {"tid": tenant.id, "title": _ALL_DONG_TITLES[1]},
    )
    return tenant.id, b401.id, b403.id


async def test_other_building_notice_chunks_excluded(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    """타 동 공지 인용 0건 — 403동 사용자에게 401동 청크가 근거로 들어오지 않는다."""
    tenant_id, _, b403 = await _seed_dong_notices(session)

    titles = {
        r.document_title for r in await _search(session, fake_llm, tenant_id, building_id=b403)
    }
    assert "401동 승강기 점검" not in titles, "타 동 공지가 검색에 노출됨"
    assert "403동 승강기 점검" in titles


async def test_all_building_notice_survives_filter(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    """전체동 공지(target_buildings NULL)는 동 필터를 항상 통과한다(회귀 신호)."""
    tenant_id, _, b403 = await _seed_dong_notices(session)

    titles = {
        r.document_title for r in await _search(session, fake_llm, tenant_id, building_id=b403)
    }
    assert set(_ALL_DONG_TITLES) <= titles


async def test_unknown_building_keeps_all_dongs(session: AsyncSession, fake_llm: LlmClient) -> None:
    """동 미상(관리자·비입주민)은 필터 미적용 — 전 동 검색을 유지한다."""
    tenant_id, _, _ = await _seed_dong_notices(session)

    titles = {r.document_title for r in await _search(session, fake_llm, tenant_id)}
    assert titles == {"401동 승강기 점검", "403동 승강기 점검", *_ALL_DONG_TITLES}


async def test_document_search_unaffected_by_building_filter(
    session: AsyncSession, fake_llm: LlmClient
) -> None:
    """document 청크는 동 필터의 영향을 받지 않는다(notice 분기 전용)."""
    tenant_id, doc_id = await _seed_document(session, storage_key="t/dong.txt")
    await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(RULES_TEXT.encode()),
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    results = await _search(session, fake_llm, tenant_id, building_id=uuid.uuid4())
    assert [r.document_id for r in results] == [doc_id, doc_id]


async def test_document_search_regression(session: AsyncSession, fake_llm: LlmClient) -> None:
    """document 청크 검색은 다형 SQL 전환 후에도 회귀 없이 동작한다."""
    tenant_id, doc_id = await _seed_document(session, storage_key="t/rules.txt")
    await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(RULES_TEXT.encode()),
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    results = await _search(session, fake_llm, tenant_id)
    doc_hits = [r for r in results if r.document_id == doc_id]
    assert doc_hits, "document 청크 검색이 회귀됨"
    assert doc_hits[0].document_title == "관리규약"


async def test_default_top_k_limits_results(session: AsyncSession, fake_llm: LlmClient) -> None:
    """검색 상한은 관리자 노브(H15-3) — 생성자 default_top_k가 LIMIT으로 반영된다."""
    tenant_id, doc_id = await _seed_document(session, storage_key="t/topk.txt")
    await ingest_document(
        session,
        llm=fake_llm,
        download=_downloader(RULES_TEXT.encode()),
        document_id=doc_id,
        tenant_id=tenant_id,
    )
    assert len(await _search(session, fake_llm, tenant_id)) == 2  # 기본 상한(8) 안에 2청크
    assert len(await _search(session, fake_llm, tenant_id, default_top_k=1)) == 1
