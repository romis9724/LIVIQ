"""seed_rag_validation.py — H15-2 RAG 검증 fixture 시드 (DB + MinIO).

`evals/fixtures/rag-validation/`의 **합성** fixture(단지 3 · 문서 40 · 사용자 15 · 세대 15 ·
관리비 72)를 로컬 DB와 MinIO에 넣는다. 500 케이스 자동 측정 어댑터가 이 데이터를 전제로 한다.

ID 규약(어댑터와 공유하는 정본 — 매핑 파일 없음, 양쪽이 같은 식으로 재계산):

    uuid.uuid5(uuid.NAMESPACE_URL, f"liviq-rag-validation:{fixture_id}")

tenant(`TENANT-A`) · user(`SYN-USER-001`) · household(`A-HH-0101`) · document(`A-RULE-001-V2`) ·
관리비 업로드(`SYN-UPLOAD-A-202601`) 전부 같은 규약이다.

revision 처리(구판 배제 = 현행 스키마의 버전 메커니즘):
  · 같은 topic의 V1/V2 쌍(`A-RULE-001-V*`·`A-MEET-001-V*`)은 **한 Document의 버전 1·2**로 넣는다.
    인제스트는 `documents.version`과 같은 첨부만 벡터화하므로(ADR-0016, ai_worker.ingest) V1은
    자동으로 검색에서 배제된다 — 기대 동작과 일치하고, 별도 플래그·중복 문서가 필요 없다.
    문서 uuid는 **현행판(V2) fixture id 기준**이고 V1 id는 같은 uuid로 별칭(`document_uuid`).
  · `DocumentVersion.version` = manifest `revision`(단독 문서의 rev 3도 그대로) — DB 버전 번호와
    manifest revision이 어긋나지 않게 맞춘다. `documents.version` = 현행판 revision.
  · 쌍이 없는 `A-NOTICE-004-DRAFT`(is_current=false, 미발행 초안)는 버전으로 표현할 수 없다 →
    Document로 넣되 **인제스트하지 않는다**(index_status=pending → 검색 SQL의 `index_status =
    'indexed'` 조건에서 배제). `--enqueue`도 이 문서를 건너뛴다.
    # ponytail: 전 단지 재색인(POST /system/ai-config/reindex)을 돌리면 이 초안도 색인된다 —
    # 필요해지면 notices(status=draft)로 옮기거나 인제스트 제외 목록을 코드에 둔다.

파일 형식: 파서(ai_worker.parsing)는 md·txt·pdf만 지원하고 **docx는 미지원**이다(10건). 파서는
고치지 않고, docx만 시드 시 텍스트로 변환해 `.txt` 키로 올린다(원본 파일명은 그대로 기록).

색인은 미투입 — `--enqueue`로 arq에 `ingest_document_task`를 직접 넣거나 문서관리 화면의
재색인으로 수행한다.

멱등: 결정적 uuid 존재 검사로 건너뛴다(관리비만 (tenant, period) 전 행 교체 — §4.6 재업로드 계약).

실행(DATABASE_URL·S3_*·REDIS_URL·PII_MASTER_KEY는 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync --env-file .env python scripts/seed_rag_validation.py [--enqueue]
    uv run --no-sync --env-file .env python scripts/seed_rag_validation.py --wipe
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import hashlib
import io
import json
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from app.password import hash_password
from app.pii import PiiCrypto, get_pii_crypto
from app.routers.auth import _normalize_email
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import (
    Base,
    Building,
    Code,
    CodeGroup,
    Document,
    DocumentVersion,
    ExcelUpload,
    Fee,
    Household,
    PiiVault,
    Tenant,
    User,
    UserRole,
)

# fixture 루트 — apps/api/scripts/ 에서 저장소 루트로 3단 상위.
FIXTURE_DIR = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "rag-validation"

# 결정적 uuid 규약(어댑터와 공유 — 문자열 하나라도 바뀌면 양쪽 다 바뀌어야 한다).
UUID_PREFIX = "liviq-rag-validation:"

TENANT_STATUS = "active"
BUILDING_NAME = "101"  # fixture 세대 코드(A-HH-0101)에 동 정보가 없어 단지별 단일 동으로 둔다
DOC_CATEGORY_GROUP = "DOC_CATEGORY"
INDEX_PENDING = "pending"
FEE_SOURCE = "excel"  # 합성이지만 원천 계약은 엑셀 업로드와 동일(§4.6)
UPLOAD_STATUS_CONFIRMED = "applied"  # fees.json confirmed=true → 확정 적재 완료 업로드

# visibility enum은 ALL|RESIDENT|ADMIN — COUNCIL은 제거됐다(마이그레이션 d4e5f6a7b8c9와 동일 이관).
VISIBILITY_ALIAS = {"COUNCIL": "ADMIN"}

# 승인 시각 — 관리비는 승인 월 이후만 열린다(FR-FEE-03). fixture 최초 월(2026-01)보다 앞.
APPROVED_AT = datetime.datetime(2025, 12, 1, tzinfo=datetime.UTC)
# 합성 계정 공통 비밀번호 — 세션 로그인이 필요한 케이스(역할 스코프)용. dev 헤더만 쓸 땐 무관.
EVAL_PASSWORD = "liviq-eval-1234!"  # noqa: S105 — 로컬 합성 데모 계정(운영 시드 아님)

# 관리비 항목명 = 500 케이스 expected_facts의 표기("난방비 86500원")와 일치시킨다.
FEE_ITEMS: tuple[tuple[str, str], ...] = (
    ("일반관리비", "general_fee"),
    ("난방비", "heating_fee"),
    ("전기료", "electricity_fee"),
    ("수도료", "water_fee"),
)

CONTENT_TYPES = {
    ".md": "text/markdown; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".pdf": "application/pdf",
}
DOCX_SUFFIX = ".docx"
CONVERTED_SUFFIX = ".txt"  # docx → 텍스트 변환 후 저장 키 확장자(파서가 읽는 기준)
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

INGEST_TASK = "ingest_document_task"


# ── ID 규약 ────────────────────────────────────────────────────────────────────


def fixture_uuid(fixture_id: str) -> uuid.UUID:
    """fixture ID → DB UUID(결정적). 어댑터가 같은 식으로 재계산한다."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"{UUID_PREFIX}{fixture_id}")


def document_uuid(document_id: str) -> uuid.UUID:
    """문서 fixture ID → Document UUID. `-V1`은 현행판(`-V2`)과 같은 Document의 구 버전이다."""
    return fixture_uuid(document_id[:-3] + "-V2" if document_id.endswith("-V1") else document_id)


# ── fixture 로드 ───────────────────────────────────────────────────────────────


def _read_json(path: Path) -> Any:
    if not path.is_file():
        raise SystemExit(f"fixture 파일이 없습니다: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_fixtures() -> tuple[
    list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
]:
    """manifest 문서 · 단지 · 사용자 · 관리비 로드 + 경계 검증(파일 존재·합계 정합)."""
    documents = _read_json(FIXTURE_DIR / "manifest.json")["documents"]
    tenants = _read_json(FIXTURE_DIR / "seed" / "tenants.json")
    users = _read_json(FIXTURE_DIR / "seed" / "users.json")
    fees = _read_json(FIXTURE_DIR / "seed" / "fees.json")

    missing = [
        d["relative_path"] for d in documents if not (FIXTURE_DIR / d["relative_path"]).is_file()
    ]
    if missing:
        raise SystemExit(f"corpus 파일 누락 {len(missing)}건: {', '.join(missing[:3])} ...")
    known = {t["tenant_id"] for t in tenants}
    unknown = sorted({r["tenant_id"] for r in documents + users + fees} - known)
    if unknown:
        raise SystemExit(f"tenants.json에 없는 tenant_id: {', '.join(unknown)}")
    broken = [f for f in fees if sum(f[key] for _, key in FEE_ITEMS) != f["total_amount"]]
    if broken:
        raise SystemExit(f"관리비 항목 합계 != total_amount {len(broken)}건 — fixture 확인 필요")
    return documents, tenants, users, fees


# ── 파일 → 저장소 페이로드 ─────────────────────────────────────────────────────


def _docx_text(data: bytes) -> str:
    """docx → 문단 단위 텍스트(stdlib만). 파서가 docx 미지원이라 시드 시점에 변환한다."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = [
        "".join(node.text or "" for node in para.iter(f"{_W_NS}t"))
        for para in root.iter(f"{_W_NS}p")
    ]
    return "\n".join(paragraphs).strip() + "\n"


def _stored_suffix(relative_path: str) -> str:
    """저장소 키 확장자 — docx는 변환 후 .txt(파서 판별 기준은 storage_key 확장자)."""
    suffix = PurePosixPath(relative_path).suffix.lower()
    return CONVERTED_SUFFIX if suffix == DOCX_SUFFIX else suffix


def _payload(relative_path: str) -> bytes:
    """저장소에 올릴 바이트 — docx만 텍스트 변환, 나머지는 원본 그대로."""
    raw = (FIXTURE_DIR / relative_path).read_bytes()
    if PurePosixPath(relative_path).suffix.lower() == DOCX_SUFFIX:
        return _docx_text(raw).encode("utf-8")
    return raw


# ── 단지·코드·세대 ─────────────────────────────────────────────────────────────


async def _set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
    )


async def _ensure_tenant(session: AsyncSession, fixture: dict[str, Any]) -> uuid.UUID:
    """단지 확보(멱등) + 최초 생성 시 기본 공통 코드 시드(라우터 create_tenant와 같은 경로)."""
    from app.codes_seed import seed_default_codes

    tenant_id = fixture_uuid(fixture["tenant_id"])
    if await session.get(Tenant, tenant_id) is None:
        session.add(Tenant(id=tenant_id, name=fixture["name"], status=TENANT_STATUS, settings={}))
        await session.flush()
        await seed_default_codes(session, tenant_id)
    await _set_tenant(session, tenant_id)
    return tenant_id


async def _category_ids(
    session: AsyncSession, tenant_id: uuid.UUID, categories: set[str]
) -> dict[str, uuid.UUID]:
    """DOC_CATEGORY 코드 라벨 → code id. fixture 분류 중 기본 코드에 없는 값은 추가한다."""
    group_id = await session.scalar(
        select(CodeGroup.id).where(
            CodeGroup.tenant_id == tenant_id, CodeGroup.group_key == DOC_CATEGORY_GROUP
        )
    )
    if group_id is None:
        raise SystemExit(f"{DOC_CATEGORY_GROUP} 코드 그룹이 없습니다: tenant={tenant_id}")
    rows = await session.execute(
        select(Code.code, Code.id).where(Code.tenant_id == tenant_id, Code.group_id == group_id)
    )
    ids = {code: code_id for code, code_id in rows}
    for order, category in enumerate(sorted(categories - set(ids)), start=len(ids)):
        code = Code(
            tenant_id=tenant_id,
            group_id=group_id,
            code=category,
            label=category,
            sort_order=order,
        )
        session.add(code)
        await session.flush()
        ids[category] = code.id
    return ids


async def _ensure_building(session: AsyncSession, tenant_id: uuid.UUID) -> uuid.UUID:
    building_id = await session.scalar(
        select(Building.id).where(Building.tenant_id == tenant_id, Building.name == BUILDING_NAME)
    )
    if building_id is not None:
        return building_id
    building = Building(tenant_id=tenant_id, name=BUILDING_NAME, floors=2)
    session.add(building)
    await session.flush()
    return building.id


async def _ensure_household(
    session: AsyncSession, tenant_id: uuid.UUID, building_id: uuid.UUID, code: str
) -> uuid.UUID:
    """세대 확보(멱등). `A-HH-0101` → 1층 101호(seed_households_xlsx의 floor·unit_no 관례)."""
    household_id = fixture_uuid(code)
    if await session.get(Household, household_id) is None:
        digits = code.rsplit("-", 1)[-1]
        session.add(
            Household(
                id=household_id,
                tenant_id=tenant_id,
                building_id=building_id,
                floor=int(digits[:2]),
                unit_no=int(digits),
                status="active",
            )
        )
        await session.flush()
    return household_id


# ── 사용자 ─────────────────────────────────────────────────────────────────────


async def _seed_user(
    session: AsyncSession,
    crypto: PiiCrypto,
    dek: bytes,
    tenant_id: uuid.UUID,
    fixture: dict[str, Any],
) -> None:
    """합성 계정 1건 + 역할(멱등). 이름·이메일은 pii_vault 암호문으로만 저장(규칙 2)."""
    user_id = fixture_uuid(fixture["user_id"])
    if await session.get(User, user_id) is not None:
        return
    email = _normalize_email(fixture["email"])
    name = fixture["display_name"]
    vault = PiiVault(
        tenant_id=tenant_id,
        email_enc=crypto.encrypt(dek, email),
        name_enc=crypto.encrypt(dek, name),
        name_hash=crypto.hmac_hash(name),
        key_version=1,
    )
    session.add(vault)
    await session.flush()
    is_active = fixture["status"] == "active"
    household = fixture["household_id"]
    session.add(
        User(
            id=user_id,
            tenant_id=tenant_id,
            household_id=fixture_uuid(household) if household else None,
            login_id=crypto.hmac_hash(email),
            password_hash=hash_password(EVAL_PASSWORD),
            status=fixture["status"],
            roster_matched=household is not None,
            email_verified_at=APPROVED_AT,
            # 미승인(pending)은 관리비가 열리지 않아야 한다 → approved_at 없음.
            approved_at=APPROVED_AT if is_active else None,
            pii_ref=vault.id,
        )
    )
    await session.flush()
    session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role=fixture["role"]))


# ── 관리비 ─────────────────────────────────────────────────────────────────────


async def _seed_fees(
    session: AsyncSession, tenant_id: uuid.UUID, rows: list[dict[str, Any]]
) -> None:
    """확정 관리비 적재 — 업로드 이력(applied) + fees. (tenant, period) 전 행 교체(멱등)."""
    periods = sorted({row["period"] for row in rows})
    await session.execute(delete(Fee).where(Fee.tenant_id == tenant_id, Fee.period.in_(periods)))
    for row in rows:
        upload_id = fixture_uuid(row["upload_id"])
        if await session.get(ExcelUpload, upload_id) is None:
            session.add(
                ExcelUpload(
                    id=upload_id,
                    tenant_id=tenant_id,
                    type="fee",
                    period=row["period"],
                    file_key=f"{tenant_id}/fees/{row['upload_id']}.xlsx",
                    status=UPLOAD_STATUS_CONFIRMED if row["confirmed"] else "validated",
                    row_count=sum(1 for r in rows if r["upload_id"] == row["upload_id"]),
                )
            )
            await session.flush()
        session.add(
            Fee(
                tenant_id=tenant_id,
                household_id=fixture_uuid(row["household_id"]),
                period=row["period"],
                breakdown=[
                    {"name": name, "level": 0, "amount": row[key]} for name, key in FEE_ITEMS
                ],
                total_amount=row["total_amount"],
                source=FEE_SOURCE,
                upload_id=upload_id,
            )
        )
    await session.flush()


# ── 문서 ───────────────────────────────────────────────────────────────────────


def _document_groups(documents: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """같은 Document(uuid)에 속하는 fixture들을 revision 순으로 묶는다(V1/V2 쌍 → 버전 1·2)."""
    grouped: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for fixture in documents:
        grouped.setdefault(document_uuid(fixture["document_id"]), []).append(fixture)
    return [sorted(group, key=lambda f: f["revision"]) for group in grouped.values()]


def _current(group: list[dict[str, Any]]) -> dict[str, Any]:
    """그룹의 현행 fixture — is_current가 있으면 그것, 없으면(초안 단독) 최신 revision."""
    return next((f for f in group if f["is_current"]), group[-1])


async def _seed_document_group(
    session: AsyncSession,
    storage: Any,
    tenant_id: uuid.UUID,
    group: list[dict[str, Any]],
    category_code_id: uuid.UUID,
    uploaded_by: uuid.UUID | None,
) -> bool:
    """Document 1건(+ 버전 전부) 적재. 이미 있으면 False(멱등)."""
    current = _current(group)
    doc_id = document_uuid(current["document_id"])
    if await session.get(Document, doc_id) is not None:
        return False

    visibility = VISIBILITY_ALIAS.get(current["visibility"], current["visibility"])
    session.add(
        Document(
            id=doc_id,
            tenant_id=tenant_id,
            title=current["title"],
            category_code_id=category_code_id,
            visibility=visibility,
            body=f"H15-2 RAG 검증 합성 fixture · {current['document_id']} · {current['topic_ko']}",
            version=current["revision"],
            index_status=INDEX_PENDING,  # 색인 미투입 — --enqueue 또는 재색인 화면에서
            uploaded_by=uploaded_by,
        )
    )
    for fixture in group:
        data = _payload(fixture["relative_path"])
        suffix = _stored_suffix(fixture["relative_path"])
        storage_key = f"{tenant_id}/documents/{doc_id}/v{fixture['revision']}{suffix}"
        await storage.put(storage_key, data)
        session.add(
            DocumentVersion(
                tenant_id=tenant_id,
                document_id=doc_id,
                version=fixture["revision"],
                filename=PurePosixPath(fixture["relative_path"]).name,
                content_type=CONTENT_TYPES[suffix],
                size_bytes=len(data),
                storage_key=storage_key,
                content_hash=hashlib.sha256(data).hexdigest(),
                uploaded_by=uploaded_by,
            )
        )
    await session.flush()
    return True


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


# ── 시드 본체 ──────────────────────────────────────────────────────────────────


async def _seed(session: AsyncSession, storage: Any) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """전 단지 시드 — 색인 대상 (tenant_id, document_id) 목록 반환(미발행 초안 제외)."""
    documents, tenants, users, fees = _load_fixtures()
    crypto = get_pii_crypto()
    indexable: list[tuple[uuid.UUID, uuid.UUID]] = []

    for tenant_fixture in tenants:
        code = tenant_fixture["tenant_id"]
        tenant_id = await _ensure_tenant(session, tenant_fixture)
        dek = await crypto.get_dek(session, tenant_id)
        building_id = await _ensure_building(session, tenant_id)

        tenant_fees = [row for row in fees if row["tenant_id"] == code]
        tenant_users = [row for row in users if row["tenant_id"] == code]
        household_codes = sorted(
            {row["household_id"] for row in tenant_fees}
            | {row["household_id"] for row in tenant_users if row["household_id"]}
        )
        for household_code in household_codes:
            await _ensure_household(session, tenant_id, building_id, household_code)

        for user_fixture in tenant_users:
            await _seed_user(session, crypto, dek, tenant_id, user_fixture)
        await _seed_fees(session, tenant_id, tenant_fees)

        tenant_docs = [row for row in documents if row["tenant_id"] == code]
        category_ids = await _category_ids(
            session, tenant_id, {row["category"] for row in tenant_docs}
        )
        uploaded_by = await _manager_user_id(session, tenant_id)
        for group in _document_groups(tenant_docs):
            current = _current(group)
            await _seed_document_group(
                session, storage, tenant_id, group, category_ids[current["category"]], uploaded_by
            )
            # 미발행 초안(is_current=false·쌍 없음)은 색인 대상이 아니다 — 검색 배제가 기대 동작.
            if current["is_current"]:
                indexable.append((tenant_id, document_uuid(current["document_id"])))
    return indexable


# ── 삭제(--wipe) ───────────────────────────────────────────────────────────────


async def _wipe(session: AsyncSession, storage: Any, tenant_ids: list[uuid.UUID]) -> None:
    """이 스크립트가 만든 3개 단지 데이터만 삭제. 다른 단지는 tenant_id 가드로 건드리지 않는다."""
    documents, _, _, _ = _load_fixtures()
    for fixture in documents:
        doc_id = document_uuid(fixture["document_id"])
        suffix = _stored_suffix(fixture["relative_path"])
        for tenant_id in tenant_ids:
            await storage.delete(f"{tenant_id}/documents/{doc_id}/v{fixture['revision']}{suffix}")
    # 자식 → 부모 순(sorted_tables는 부모 먼저) — 합성 단지에 쌓인 대화·감사 이력까지 함께 정리.
    for table in reversed(Base.metadata.sorted_tables):
        if "tenant_id" in table.c:
            await session.execute(table.delete().where(table.c.tenant_id.in_(tenant_ids)))
    await session.execute(delete(Tenant).where(Tenant.id.in_(tenant_ids)))


# ── 보고 ───────────────────────────────────────────────────────────────────────


async def _count(session: AsyncSession, model: Any, tenant_ids: list[uuid.UUID]) -> int:
    total = await session.scalar(
        select(func.count()).select_from(model).where(model.tenant_id.in_(tenant_ids))
    )
    return int(total or 0)


async def _report(session: AsyncSession, tenant_ids: list[uuid.UUID], indexable: int) -> None:
    documents, tenants, users, fees = _load_fixtures()
    groups = len(_document_groups(documents))
    counts = {
        "단지": await session.scalar(
            select(func.count()).select_from(Tenant).where(Tenant.id.in_(tenant_ids))
        )
        or 0,
        "문서(Document)": await _count(session, Document, tenant_ids),
        "문서 버전": await _count(session, DocumentVersion, tenant_ids),
        "사용자": await _count(session, User, tenant_ids),
        "세대": await _count(session, Household, tenant_ids),
        "관리비": await _count(session, Fee, tenant_ids),
        "관리비 업로드": await _count(session, ExcelUpload, tenant_ids),
    }
    for label, value in counts.items():
        print(f"  {label}: {value}건")

    assert counts["단지"] == len(tenants), f"단지 {counts['단지']} != {len(tenants)}"
    assert counts["문서 버전"] == len(documents), (
        f"문서 버전 {counts['문서 버전']} != {len(documents)}"
    )
    assert counts["문서(Document)"] == groups, f"문서 {counts['문서(Document)']} != {groups}"
    assert counts["사용자"] == len(users), f"사용자 {counts['사용자']} != {len(users)}"
    assert counts["관리비"] == len(fees), f"관리비 {counts['관리비']} != {len(fees)}"
    print(
        f"\n색인: 미투입(index_status={INDEX_PENDING}) — 색인 대상 {indexable}건.\n"
        f"  `--enqueue`로 arq에 {INGEST_TASK}를 넣거나 문서관리 화면에서 재색인하세요.\n"
        f"  (미발행 초안 {groups - indexable}건은 검색 배제가 기대 동작 — 색인하지 않습니다.)"
    )


# ── 진입점 ─────────────────────────────────────────────────────────────────────


async def _run(*, wipe: bool, enqueue: bool) -> None:
    from app.deps import get_queue, get_storage

    _, tenants, _, _ = _load_fixtures()
    tenant_ids = [fixture_uuid(t["tenant_id"]) for t in tenants]
    storage = get_storage()
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            if wipe:
                await _wipe(session, storage, tenant_ids)
                names = ", ".join(t["name"] for t in tenants)
                print(f"삭제 완료 — 합성 단지 {len(tenant_ids)}개 데이터 제거: {names}")
                return
            indexable = await _seed(session, storage)
        async with factory() as session:
            await _report(session, tenant_ids, len(indexable))
        if enqueue:
            queue = get_queue()
            for tenant_id, document_id in indexable:
                await queue.enqueue(INGEST_TASK, str(document_id), str(tenant_id))
            print(f"\narq enqueue 완료: {INGEST_TASK} × {len(indexable)}건")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="H15-2 RAG 검증 fixture 시드(DB + MinIO)")
    parser.add_argument(
        "--enqueue", action="store_true", help=f"시드 후 {INGEST_TASK}를 arq에 직접 enqueue"
    )
    parser.add_argument(
        "--wipe", action="store_true", help="합성 단지 3개 데이터만 삭제(다른 단지는 건드리지 않음)"
    )
    args = parser.parse_args()
    asyncio.run(_run(wipe=args.wipe, enqueue=args.enqueue))


if __name__ == "__main__":
    main()
