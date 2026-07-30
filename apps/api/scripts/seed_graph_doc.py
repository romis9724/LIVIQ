"""seed_graph_doc.py — G1c 겹침 문서 시드 (DB + MinIO).

GraphRAG 비교(pgvector vs Neo4j)의 pgvector 쪽 겹침 문서 1건을 적재한다. 같은 장애를
그래프(Neo4j incident)와 문서(pgvector 청크) 양쪽으로 넣어 동일 질의를 교차 비교한다
(SEED-PLAN §3). 문서 본문은 graph_seed.INCIDENTS 상수에서 렌더하므로(graph_overlap_doc)
문서 사실이 그래프 사실과 by construction 동일하다. 이 문서는 DB의 incident 행과 독립인
별개 경로다 — seed_graph.py 선행 실행이 필요 없다.

업로드 라우터(app/routers/documents.py create_document)·seed_documents_demo와 같은 방식:
storage_key = `{tenant}/documents/{doc_id}/v1.md`, content_hash = 파일 sha256,
Document(version=1·index_status="pending") + DocumentVersion(v1) + storage.put.

멱등: (tenant_id, title) 기준으로 이미 있으면 건너뛴다(재실행해도 문서 수가 늘지 않음).

색인은 미투입 — `--enqueue`로 arq에 ingest_document_task를 직접 넣거나 문서관리 화면의
재색인으로 수행한다.

실행(DATABASE_URL·S3_*·REDIS_URL은 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync --env-file .env python scripts/seed_graph_doc.py [--enqueue] \\
        [--tenant-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import Code, CodeGroup, Document, DocumentVersion, Tenant, User, UserRole

# scripts/data는 패키지가 아니라 폴더(namespace package, 다른 시드 스크립트와 동일 관례).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.graph_overlap_doc import OVERLAP_DOC_MD, OVERLAP_DOC_TITLE  # noqa: E402

# 파일럿 단지(첫마을 4단지 푸르지오) — 다른 시드 스크립트와 동일 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DOC_CATEGORY_GROUP = "DOC_CATEGORY"
# 설비 장애·정비 이력 = 내부 운영 기록 → 지침(ADMIN). documents_demo의 설비 운전·법정
# 점검 지침 문서가 category=지침·visibility=ADMIN이라 같은 값으로 맞춘다(SEED-PLAN §3
# "category=지침/기록" — DOC_CATEGORY에 '기록' 라벨은 없어 가장 가까운 '지침'을 쓴다).
CATEGORY_LABEL = "지침"
VISIBILITY = "ADMIN"
CONTENT_TYPE = "text/markdown"
FILENAME = "설비-장애-정비-이력-요약.md"
INGEST_TASK = "ingest_document_task"


async def _category_id(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    """DOC_CATEGORY '지침' 코드 id — 없으면 fail-fast(어느 라벨을 찾는지 출력)."""
    code_id = await session.scalar(
        select(Code.id)
        .join(CodeGroup, CodeGroup.id == Code.group_id)
        .where(
            Code.tenant_id == tenant_id,
            CodeGroup.group_key == DOC_CATEGORY_GROUP,
            Code.code == CATEGORY_LABEL,
        )
    )
    if code_id is None:
        raise SystemExit(f"DOC_CATEGORY 코드가 없습니다: '{CATEGORY_LABEL}' (tenant={tenant_id})")
    return code_id


async def _manager_user_id(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID | None:
    """업로더로 기록할 MANAGER — 없으면 None(uploaded_by는 nullable)."""
    return await session.scalar(
        select(User.id)
        .join(UserRole, UserRole.user_id == User.id)
        .where(
            User.tenant_id == tenant_id,
            UserRole.tenant_id == tenant_id,
            UserRole.role == "MANAGER",
            User.deleted_at.is_(None),
        )
        .order_by(User.created_at)
        .limit(1)
    )


async def _seed_document(
    session: AsyncSession,
    storage: Any,
    tenant_id: uuid.UUID,
    category_code_id: uuid.UUID,
    uploaded_by: uuid.UUID | None,
) -> uuid.UUID:
    """겹침 문서 1건 적재 — 라우터 create_document와 동일한 키·해시·행 구성."""
    doc_id = uuid.uuid4()
    data = OVERLAP_DOC_MD.encode("utf-8")
    storage_key = f"{tenant_id}/documents/{doc_id}/v1.md"
    await storage.put(storage_key, data)

    session.add(
        Document(
            id=doc_id,
            tenant_id=tenant_id,
            title=OVERLAP_DOC_TITLE,
            category_code_id=category_code_id,
            visibility=VISIBILITY,
            body=OVERLAP_DOC_MD,
            version=1,
            index_status="pending",  # 색인 미투입 — --enqueue 또는 재색인 화면에서
            uploaded_by=uploaded_by,
        )
    )
    session.add(
        DocumentVersion(
            tenant_id=tenant_id,
            document_id=doc_id,
            version=1,
            filename=FILENAME,
            content_type=CONTENT_TYPE,
            size_bytes=len(data),
            storage_key=storage_key,
            content_hash=hashlib.sha256(data).hexdigest(),
            uploaded_by=uploaded_by,
        )
    )
    await session.flush()
    return doc_id


async def _run(tenant_id: uuid.UUID, *, enqueue: bool) -> None:
    from app.deps import get_queue, get_storage

    storage = get_storage()
    engine = create_engine()
    factory = create_session_factory(engine)
    document_id: uuid.UUID | None = None
    skipped = False
    try:
        async with factory() as session, session.begin():
            if await session.get(Tenant, tenant_id) is None:
                raise SystemExit(f"단지를 찾을 수 없습니다: {tenant_id}")
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            existing = await session.scalar(
                select(Document.id).where(
                    Document.tenant_id == tenant_id,
                    Document.title == OVERLAP_DOC_TITLE,
                    Document.deleted_at.is_(None),
                )
            )
            if existing is not None:
                document_id, skipped = existing, True
            else:
                category_code_id = await _category_id(session, tenant_id)
                uploaded_by = await _manager_user_id(session, tenant_id)
                document_id = await _seed_document(
                    session, storage, tenant_id, category_code_id, uploaded_by
                )

        print(f"겹침 문서: {OVERLAP_DOC_TITLE}")
        print(f"  문서 id: {document_id}   ·   {'건너뜀(기존)' if skipped else '신규'}")
        print(f"  단지: {tenant_id}   ·   category={CATEGORY_LABEL}·visibility={VISIBILITY}")

        if enqueue and document_id is not None:
            queue = get_queue()
            await queue.enqueue(INGEST_TASK, str(document_id), str(tenant_id))
            print(f"\narq enqueue 완료: {INGEST_TASK}(document={document_id})")
        else:
            print(
                f"\n색인: 미투입(index_status=pending) — `--enqueue`로 arq에 {INGEST_TASK}를 "
                "넣거나 문서관리 화면에서 재색인하세요."
            )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="G1c GraphRAG 비교 겹침 문서 시드(DB + MinIO)")
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ID,
        help=f"대상 단지 UUID (기본: 첫마을 4단지 {DEFAULT_TENANT_ID})",
    )
    parser.add_argument(
        "--enqueue", action="store_true", help=f"시드 후 {INGEST_TASK}를 arq에 직접 enqueue"
    )
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id, enqueue=args.enqueue))


if __name__ == "__main__":
    main()
