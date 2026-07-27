"""seed_documents_demo.py — 문서관리 데모 문서 시드 (DB + MinIO).

generate_demo_docs.py가 만든 PDF 33건(회의록 23 · 지침·매뉴얼 10)을 업로드 라우터
(app/routers/documents.py create_document)와 **같은 방식**으로 적재한다:
storage_key = `{tenant}/documents/{doc_id}/v1.pdf`, content_hash = 파일 sha256,
Document(version=1·index_status="pending") + DocumentVersion(v1) + storage.put.

색인은 미투입 — 벡터 색인은 문서관리 화면의 재색인 버튼이나 후속 작업으로 수행한다
(index_status는 "pending"으로 남는다).

멱등: (tenant_id, title) 기준으로 이미 있으면 건너뛴다(재실행해도 문서 수가 늘지 않음).

실행(DATABASE_URL·S3_*는 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync --env-file .env python scripts/seed_documents_demo.py \\
        --dir scripts/data/generated_docs [--tenant-id <uuid>]
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

# scripts/data는 패키지가 아니라 폴더(namespace package, seed_floor_plans.py와 동일 관례).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.documents_demo import DEMO_DOCS, DemoDoc  # noqa: E402

# 파일럿 단지(첫마을 4단지 푸르지오) — 다른 시드 스크립트와 동일 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEFAULT_DIR = Path(__file__).resolve().parent / "data" / "generated_docs"
CONTENT_TYPE = "application/pdf"


async def _category_ids(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """DOC_CATEGORY 코드 라벨 → code id 매핑(seed_demo의 공지 분류 조회와 동일 패턴)."""
    rows = await session.execute(
        select(Code.code, Code.id)
        .join(CodeGroup, CodeGroup.id == Code.group_id)
        .where(Code.tenant_id == tenant_id, CodeGroup.group_key == "DOC_CATEGORY")
    )
    return {code: code_id for code, code_id in rows}


async def _manager_user_id(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID | None:
    """업로더로 기록할 관리자(MANAGER) user id — 없으면 None(uploaded_by는 nullable)."""
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
    doc: DemoDoc,
    data: bytes,
    category_code_id: uuid.UUID,
    uploaded_by: uuid.UUID | None,
) -> None:
    """문서 1건 적재 — 라우터 create_document와 동일한 키·해시·행 구성."""
    doc_id = uuid.uuid4()
    storage_key = f"{tenant_id}/documents/{doc_id}/v1.pdf"
    await storage.put(storage_key, data)

    session.add(
        Document(
            id=doc_id,
            tenant_id=tenant_id,
            title=doc.title,
            category_code_id=category_code_id,
            visibility=doc.visibility,
            body=doc.body,
            version=1,
            index_status="pending",  # 색인 미투입 — 재색인은 화면/후속 작업에서
            uploaded_by=uploaded_by,
        )
    )
    session.add(
        DocumentVersion(
            tenant_id=tenant_id,
            document_id=doc_id,
            version=1,
            filename=doc.filename,
            content_type=CONTENT_TYPE,
            size_bytes=len(data),
            storage_key=storage_key,
            content_hash=hashlib.sha256(data).hexdigest(),
            uploaded_by=uploaded_by,
        )
    )
    await session.flush()


async def _run(tenant_id: uuid.UUID, source_dir: Path) -> None:
    from app.deps import get_storage

    if not source_dir.is_dir():
        raise SystemExit(
            f"PDF 디렉터리를 찾을 수 없습니다: {source_dir}\n"
            "  먼저 `uv run --no-sync --with fpdf2 python scripts/generate_demo_docs.py`를 "
            "실행하세요."
        )
    missing = [d.filename for d in DEMO_DOCS if not (source_dir / d.filename).is_file()]
    if missing:
        raise SystemExit(f"PDF 누락 {len(missing)}건: {', '.join(missing[:3])} ...")

    storage = get_storage()
    engine = create_engine()
    factory = create_session_factory(engine)
    created = 0
    skipped = 0
    try:
        async with factory() as session, session.begin():
            if await session.get(Tenant, tenant_id) is None:
                raise SystemExit(f"단지를 찾을 수 없습니다: {tenant_id}")
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            category_ids = await _category_ids(session, tenant_id)
            unknown = sorted({d.category for d in DEMO_DOCS} - set(category_ids))
            if unknown:
                raise SystemExit(f"DOC_CATEGORY 코드가 없습니다: {', '.join(unknown)}")
            uploaded_by = await _manager_user_id(session, tenant_id)

            for doc in DEMO_DOCS:
                exists = await session.scalar(
                    select(Document.id).where(
                        Document.tenant_id == tenant_id,
                        Document.title == doc.title,
                        Document.deleted_at.is_(None),
                    )
                )
                if exists is not None:
                    skipped += 1
                    continue
                await _seed_document(
                    session,
                    storage,
                    tenant_id,
                    doc,
                    (source_dir / doc.filename).read_bytes(),
                    category_ids[doc.category],
                    uploaded_by,
                )
                created += 1
    finally:
        await engine.dispose()

    print(f"문서 총 {len(DEMO_DOCS)}건 · 신규 {created} · 건너뜀 {skipped}")
    print(f"업로더(MANAGER): {uploaded_by}   ·   색인: 미투입(index_status=pending)")
    print(f"단지: {tenant_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="문서관리 데모 문서 시드(DB + MinIO)")
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ID,
        help=f"대상 단지 UUID (기본: 첫마을 4단지 {DEFAULT_TENANT_ID})",
    )
    parser.add_argument(
        "--dir", type=Path, default=DEFAULT_DIR, help=f"PDF 디렉터리(기본: {DEFAULT_DIR})"
    )
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id, args.dir))


if __name__ == "__main__":
    main()
