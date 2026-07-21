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


async def test_template_roundtrips_through_parser(seeded: None, db_session: AsyncSession) -> None:
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


# ── 명부 목록 (H7-9) ─────────────────────────────────────────────────────────


async def _get_roster(app: FastAPI, params: dict[str, str | int] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get("/admin/roster", params=params or {})


async def test_roster_list_states_counts_and_masking(
    seeded: None, db_session: AsyncSession
) -> None:
    """상태 분류(미가입/가입완료/전출후보)·총계·성함 마스킹·생년월일 비노출(H7-9)."""
    import datetime as dt

    from liviq_db.models import User as UserModel

    app = _build_app(db_session, FakeStorage())
    data = _xlsx(
        [
            ("김일", "1990-01-01", "101", 3, 301),
            ("이가입", "1985-05-05", "101", 3, 302),
            ("박전출", "1970-12-12", "101", 5, 501),
        ]
    )
    assert (await _upload(app, data)).status_code == 200

    # 이가입 → 소진(가입 완료), 박전출 → inactive(전출 후보)로 상태 변형.
    rows = (
        await db_session.execute(
            select(UserModel).where(UserModel.login_id.is_(None), UserModel.pii_ref.is_not(None))
        )
    ).scalars()
    from app.pii import get_pii_crypto

    crypto = get_pii_crypto()
    for user in rows:
        vault = await db_session.scalar(select(PiiVault).where(PiiVault.id == user.pii_ref))
        assert vault is not None
        if vault.name_hash == crypto.hmac_hash("이가입"):
            user.deleted_at = dt.datetime.now(dt.UTC)
        elif vault.name_hash == crypto.hmac_hash("박전출"):
            user.status = "inactive"
    await db_session.flush()

    resp = await _get_roster(app)
    assert resp.status_code == 200
    body = resp.json()
    assert body["counts"] == {"total": 3, "unregistered": 1, "joined": 1, "moved_out": 1}
    by_state = {i["state"]: i for i in body["items"]}
    assert by_state["unregistered"]["name_masked"] == "김*"
    assert by_state["joined"]["unit_no"] == 302
    assert by_state["moved_out"]["unit_no"] == 501
    # 원문 성함·생년월일이 응답 어디에도 없다(마스킹·비표시 — 운영자 결정).
    assert "김일" not in resp.text and "1990-01-01" not in resp.text
    # 마지막 업로드 요약.
    assert body["last_upload"] is not None and body["last_upload"]["row_count"] == 3


async def test_roster_list_search_filter_and_pagination(
    seeded: None, db_session: AsyncSession
) -> None:
    app = _build_app(db_session, FakeStorage())
    data = _xlsx(
        [
            ("김일", "1990-01-01", "101", 3, 301),
            ("김이", "1991-01-01", "101", 3, 302),
            ("김삼", "1992-01-01", "101", 5, 501),
        ]
    )
    assert (await _upload(app, data)).status_code == 200

    # 호수 검색.
    resp = await _get_roster(app, {"q": "501"})
    assert [i["unit_no"] for i in resp.json()["items"]] == [501]
    # 상태 필터 + 페이지네이션(사이즈 2 → 2페이지).
    page1 = (await _get_roster(app, {"state": "unregistered", "size": 2, "page": 1})).json()
    page2 = (await _get_roster(app, {"state": "unregistered", "size": 2, "page": 2})).json()
    assert page1["total"] == 3 and len(page1["items"]) == 2 and len(page2["items"]) == 1


async def test_roster_list_requires_manager(seeded: None, db_session: AsyncSession) -> None:
    app = _build_app(db_session, FakeStorage(), roles=("STAFF",))
    assert (await _get_roster(app)).status_code == 403


async def test_roster_state_change_and_delete(seeded: None, db_session: AsyncSession) -> None:
    """상태 수동 변경(미가입↔전출 후보)·행 삭제(PII vault째) — 소진 행은 404(H7-9 보강)."""
    from liviq_db.models import User as UserModel

    app = _build_app(db_session, FakeStorage())
    data = _xlsx([("김일", "1990-01-01", "101", 3, 301)])
    assert (await _upload(app, data)).status_code == 200

    listed = (await _get_roster(app)).json()
    row = listed["items"][0]
    user_id = row["user_id"]

    async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        # 전출 후보로 → 다시 미가입으로.
        moved = await c.patch(f"/admin/roster/{user_id}", json={"state": "moved_out"})
        assert moved.status_code == 204
        assert (await _get_roster(app)).json()["items"][0]["state"] == "moved_out"
        assert (
            await c.patch(f"/admin/roster/{user_id}", json={"state": "unregistered"})
        ).status_code == 204
        # 허용 외 상태는 422.
        bad = await c.patch(f"/admin/roster/{user_id}", json={"state": "joined"})
        assert bad.status_code == 422

        # 삭제 — 행·vault 완전 제거.
        assert (await c.delete(f"/admin/roster/{user_id}")).status_code == 204
        assert (await _get_roster(app)).json()["counts"]["total"] == 0
        assert (await c.delete(f"/admin/roster/{user_id}")).status_code == 404

    gone = await db_session.scalar(select(UserModel).where(UserModel.id == user_id))
    assert gone is None
    vault_count = await db_session.scalar(select(func.count()).select_from(PiiVault))
    assert vault_count == 0  # vault 잔존 0(사전등록 행 외 vault 없음)
