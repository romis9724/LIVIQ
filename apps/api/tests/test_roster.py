"""명부 엑셀 업로드 통합 테스트 — 실 PG + FakeStorage. diff 병합·행 오류·인가.

xlsx 픽스처는 openpyxl로 코드 생성한다(바이너리 커밋 금지).
"""

from __future__ import annotations

import io
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import RequestContext, get_context, get_storage, get_tenant_session
from app.main import create_app
from app.pii import PiiCrypto
from conftest import MANAGER_USER_ID, TENANT_ID, FakeStorage, seed_tenant
from fastapi import FastAPI
from httpx import ASGITransport
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import ExcelUpload, PiiVault, User

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx(rows: list[tuple[object, ...]], *, header: tuple[str, ...] | None = None) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(list(header or ("성함", "생년월일", "동", "층", "호")))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _build_app(
    db_session: AsyncSession, storage: FakeStorage, *, roles: tuple[str, ...] = ("MANAGER",)
) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, MANAGER_USER_ID, roles=roles
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: storage
    return app


async def _upload(app: FastAPI, data: bytes) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.post(
            "/admin/roster/upload",
            files={"file": ("roster.xlsx", data, _XLSX_MIME)},
        )


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[None]:
    await seed_tenant(db_session)
    yield


async def test_new_rows_create_pre_registered_with_hashes(
    seeded: None, db_session: AsyncSession, pii_crypto: PiiCrypto
) -> None:
    data = _xlsx(
        [
            ("김일", "1990-01-01", "101", 3, 301),
            ("이이", "1985-02-02", "101", 3, 302),
            ("박삼", "2000-03-03", "101", 5, 501),
        ]
    )
    app = _build_app(db_session, FakeStorage())
    response = await _upload(app, data)

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == 3
    assert body["marked_inactive"] == 0
    assert body["errors"] == []

    users = await db_session.scalar(
        select(func.count()).select_from(User).where(User.status == "pre_registered")
    )
    assert users == 3
    vaults = await db_session.scalar(select(func.count()).select_from(PiiVault))
    assert vaults == 3
    # 해시가 저장되어 온보딩 대조 키로 쓰인다.
    stored = await db_session.scalar(
        select(PiiVault.name_hash).where(PiiVault.name_hash == pii_crypto.hmac_hash("김일"))
    )
    assert stored == pii_crypto.hmac_hash("김일")


async def test_reupload_marks_missing_row_inactive(seeded: None, db_session: AsyncSession) -> None:
    full = _xlsx(
        [
            ("김일", "1990-01-01", "101", 3, 301),
            ("이이", "1985-02-02", "101", 3, 302),
            ("박삼", "2000-03-03", "101", 5, 501),
        ]
    )
    first = await _upload(_build_app(db_session, FakeStorage()), full)
    assert first.json()["applied"] == 3

    # 박삼(5,501) 제외하고 재업로드 → 그 사전등록 행 inactive
    partial = _xlsx(
        [
            ("김일", "1990-01-01", "101", 3, 301),
            ("이이", "1985-02-02", "101", 3, 302),
        ]
    )
    second = await _upload(_build_app(db_session, FakeStorage()), partial)
    assert second.status_code == 200
    body = second.json()
    assert body["applied"] == 0  # 기존 2행 불변
    assert body["marked_inactive"] == 1

    inactive = await db_session.scalar(
        select(func.count()).select_from(User).where(User.status == "inactive")
    )
    assert inactive == 1
    still_pre = await db_session.scalar(
        select(func.count()).select_from(User).where(User.status == "pre_registered")
    )
    assert still_pre == 2


async def test_row_with_unknown_household_reported_others_applied(
    seeded: None, db_session: AsyncSession
) -> None:
    data = _xlsx(
        [
            ("김일", "1990-01-01", "101", 3, 301),
            ("없음", "1990-01-01", "101", 9, 999),  # 세대 없음
            ("박삼", "2000-03-03", "101", 5, 501),
        ]
    )
    app = _build_app(db_session, FakeStorage())
    response = await _upload(app, data)

    assert response.status_code == 200
    body = response.json()
    assert body["applied"] == 2
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 3  # 헤더=1, 데이터 2행째
    assert "세대" in body["errors"][0]["reason"]

    upload = await db_session.scalar(select(ExcelUpload).where(ExcelUpload.type == "roster"))
    assert upload is not None
    assert upload.status == "applied"
    assert upload.error_report is not None and len(upload.error_report["errors"]) == 1


async def test_bad_row_validation_reported(seeded: None, db_session: AsyncSession) -> None:
    data = _xlsx(
        [
            ("김일", "not-a-date", "101", 3, 301),  # 생년월일 파싱 실패
            ("박삼", "2000-03-03", "101", 5, 501),
        ]
    )
    response = await _upload(_build_app(db_session, FakeStorage()), data)
    body = response.json()
    assert body["applied"] == 1
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row"] == 2


async def test_wrong_header_rejected(seeded: None, db_session: AsyncSession) -> None:
    data = _xlsx([("김일", "1990-01-01", "101", 3, 301)], header=("이름", "생일", "동", "층", "호"))
    response = await _upload(_build_app(db_session, FakeStorage()), data)
    assert response.status_code == 422


async def test_resident_cannot_upload(seeded: None, db_session: AsyncSession) -> None:
    """RESIDENT 세션으로 명부 업로드 → 403(규칙 4, 서버 인가)."""
    data = _xlsx([("김일", "1990-01-01", "101", 3, 301)])
    app = _build_app(db_session, FakeStorage(), roles=("RESIDENT",))
    response = await _upload(app, data)
    assert response.status_code == 403


# ── 양식 다운로드 (H7-7) ─────────────────────────────────────────────────────


async def test_template_roundtrips_through_parser(
    seeded: None, db_session: AsyncSession
) -> None:
    """양식은 파서와 단일 출처 — 다운로드한 파일이 그대로 업로드 파싱을 통과해야 한다."""
    from app.routers.roster import _parse_rows

    app = _build_app(db_session, FakeStorage())
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/admin/roster/template")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(_XLSX_MIME)
    assert "attachment" in resp.headers["content-disposition"]
    parsed, errors = _parse_rows(resp.content)
    assert errors == []  # 예시 행 전부 유효
    assert len(parsed) >= 1
    assert parsed[0][1].building_name == "101"


async def test_template_requires_manager(seeded: None, db_session: AsyncSession) -> None:
    app = _build_app(db_session, FakeStorage(), roles=("STAFF",))
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get("/admin/roster/template")).status_code == 403
