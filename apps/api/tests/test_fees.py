"""관리비 라우터 통합 — 실 PG + FakeStorage + fake LLM(SSE).

업로드·검증·미리보기 → 확정 전체 교체(FR-FEE-02) → 본인 세대·승인 후 월만(FR-FEE-03)
→ AI 설명(SSE·확정 데이터 출처) → 역할 가드를 검증한다(규칙 4·5).
xlsx 픽스처는 openpyxl로 코드 생성(바이너리 커밋 금지).
"""

from __future__ import annotations

import datetime
import io
import json
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import (
    RequestContext,
    get_context,
    get_llm,
    get_storage,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from conftest import MANAGER_USER_ID, TENANT_ID, USER_ID, FakeStorage, seed_tenant
from httpx import ASGITransport
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from liviq_db.models import Fee, User

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_HEADER = ("동", "층", "호", "일반관리비", "청소비")


def _fee_xlsx(rows: list[tuple[object, ...]], *, header: tuple[str, ...] = _HEADER) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _client(
    db_session: AsyncSession,
    storage: FakeStorage,
    *,
    roles: tuple[str, ...] = ("MANAGER",),
    user_id: uuid.UUID = MANAGER_USER_ID,
    llm: LlmClient | None = None,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        TENANT_ID, user_id, roles=roles, visibilities=visibilities_for(roles)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    app.dependency_overrides[get_storage] = lambda: storage
    if llm is not None:
        app.dependency_overrides[get_llm] = lambda: llm
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _upload(c: httpx.AsyncClient, data: bytes, period: str) -> httpx.Response:
    return await c.post(
        f"/admin/fees/uploads?period={period}",
        files={"file": ("fees.xlsx", data, _XLSX_MIME)},
    )


def _parse_sse(body: str) -> list[tuple[str, dict[str, object]]]:
    events: list[tuple[str, dict[str, object]]] = []
    name = ""
    for line in body.splitlines():
        if line.startswith("event:"):
            name = line[len("event:") :].strip()
        elif line.startswith("data:"):
            events.append((name, json.loads(line[len("data:") :].strip())))
    return events


async def _add_resident(
    session: AsyncSession, household_id: uuid.UUID | None, *, approved: datetime.datetime | None
) -> None:
    session.add(
        User(
            id=USER_ID,
            tenant_id=TENANT_ID,
            status="active",
            household_id=household_id,
            approved_at=approved,
        )
    )
    await session.flush()


@pytest_asyncio.fixture
async def households(db_session: AsyncSession) -> AsyncIterator[dict[tuple[int, int], uuid.UUID]]:
    hmap = await seed_tenant(db_session)
    yield hmap


# ── 업로드·검증 ──────────────────────────────────────────────────────────────


async def test_upload_validates_and_previews(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    data = _fee_xlsx(
        [
            ("101", 3, 301, 100000, 20000),
            ("101", 3, 302, 110000, 21000),
            ("101", 5, 501, 90000, 19000),
        ]
    )
    async with _client(db_session, FakeStorage()) as c:
        resp = await _upload(c, data, "2026-06")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "validated"
    assert body["row_count"] == 3
    assert body["valid_rows"] == 3
    assert body["errors"] == []
    assert len(body["preview"]) == 3
    assert body["preview"][0]["total"] == 120000  # 서버 합계 계산
    # fees에는 아직 쓰지 않는다(확정 전).
    count = await db_session.scalar(select(func.count()).select_from(Fee))
    assert count == 0


async def test_upload_unknown_household_and_bad_amount_reported(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    data = _fee_xlsx(
        [
            ("101", 3, 301, 100000, 20000),
            ("101", 9, 999, 100000, 20000),  # 세대 없음
            ("101", 5, 501, -5, 20000),  # 음수 금액
        ]
    )
    async with _client(db_session, FakeStorage()) as c:
        resp = await _upload(c, data, "2026-06")
    body = resp.json()
    assert body["valid_rows"] == 1
    reasons = {e["reason"] for e in body["errors"]}
    assert any("세대" in r for r in reasons)
    assert any("금액" in r for r in reasons)


async def test_upload_wrong_header_422(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    data = _fee_xlsx([("101", 3, 301, 100)], header=("호실", "층", "호", "관리비"))
    async with _client(db_session, FakeStorage()) as c:
        resp = await _upload(c, data, "2026-06")
    assert resp.status_code == 422


async def test_upload_bad_period_422(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    data = _fee_xlsx([("101", 3, 301, 100, 10)])
    async with _client(db_session, FakeStorage()) as c:
        resp = await _upload(c, data, "2026-13")
    assert resp.status_code == 422


async def test_get_upload_detail_replays_errors(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    data = _fee_xlsx([("101", 3, 301, 100000, 20000), ("101", 9, 999, 100000, 20000)])
    storage = FakeStorage()
    async with _client(db_session, storage) as c:
        up = await _upload(c, data, "2026-06")
        upload_id = up.json()["upload_id"]
        detail = await c.get(f"/admin/fees/uploads/{upload_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "validated"
    assert body["period"] == "2026-06"
    assert len(body["errors"]) == 1  # 세대 없음 행 재표시(preview는 저장 안 함)
    assert "preview" not in body


async def test_get_upload_detail_not_found_404(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get(f"/admin/fees/uploads/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── 확정 적재(전체 교체) ─────────────────────────────────────────────────────


async def test_apply_inserts_fees_with_server_total(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    storage = FakeStorage()
    data = _fee_xlsx(
        [
            ("101", 3, 301, 100000, 20000),
            ("101", 3, 302, 110000, 21000),
            ("101", 5, 501, 90000, 19000),
        ]
    )
    async with _client(db_session, storage) as c:
        up = await _upload(c, data, "2026-06")
        upload_id = up.json()["upload_id"]
        apply = await c.post(f"/admin/fees/uploads/{upload_id}/apply")
    assert apply.status_code == 200, apply.text
    assert apply.json()["applied"] == 3

    fees = list(await db_session.scalars(select(Fee).where(Fee.period == "2026-06")))
    assert len(fees) == 3
    by_h = {f.household_id: f for f in fees}
    fee_301 = by_h[households[(3, 301)]]
    assert fee_301.total_amount == 120000
    assert fee_301.breakdown == {"일반관리비": 100000, "청소비": 20000}
    assert fee_301.source == "excel"


async def test_apply_replaces_whole_month_only(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    # 타 월(2026-05) 기존 데이터 — 교체 대상 아님.
    db_session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=households[(3, 301)],
            period="2026-05",
            breakdown={"일반관리비": 1},
            total_amount=1,
            source="excel",
        )
    )
    await db_session.flush()

    storage = FakeStorage()
    first = _fee_xlsx([("101", 3, 301, 100000, 20000), ("101", 3, 302, 110000, 21000)])
    async with _client(db_session, storage) as c:
        up = await _upload(c, first, "2026-06")
        await c.post(f"/admin/fees/uploads/{up.json()['upload_id']}/apply")

    # 재업로드: 301만·값 변경 → 302 사라지고 301 갱신(전체 교체).
    second = _fee_xlsx([("101", 3, 301, 130000, 25000)])
    async with _client(db_session, storage) as c:
        up2 = await _upload(c, second, "2026-06")
        apply2 = await c.post(f"/admin/fees/uploads/{up2.json()['upload_id']}/apply")
    assert apply2.json()["applied"] == 1

    june = list(await db_session.scalars(select(Fee).where(Fee.period == "2026-06")))
    assert len(june) == 1
    assert june[0].total_amount == 155000
    # 타 월 불변.
    may = await db_session.scalar(
        select(func.count()).select_from(Fee).where(Fee.period == "2026-05")
    )
    assert may == 1


async def test_apply_requires_validated_status(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    storage = FakeStorage()
    data = _fee_xlsx([("101", 3, 301, 100000, 20000)])
    async with _client(db_session, storage) as c:
        up = await _upload(c, data, "2026-06")
        upload_id = up.json()["upload_id"]
        first = await c.post(f"/admin/fees/uploads/{upload_id}/apply")
        assert first.status_code == 200
        # 이미 applied → validated 아님 → 409.
        again = await c.post(f"/admin/fees/uploads/{upload_id}/apply")
    assert again.status_code == 409


# ── FR-FEE-03 (CRITICAL): 본인 세대 + 승인 이후 월만 ─────────────────────────


async def test_resident_sees_own_household_only(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    # 본인=301, 타 세대=302. 둘 다 6월 fee 존재.
    for hid, total in ((households[(3, 301)], 120000), (households[(3, 302)], 999999)):
        db_session.add(
            Fee(
                tenant_id=TENANT_ID,
                household_id=hid,
                period="2026-06",
                breakdown={"일반관리비": total},
                total_amount=total,
                source="excel",
            )
        )
    await _add_resident(
        db_session,
        households[(3, 301)],
        approved=datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC),
    )

    async with _client(db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID) as c:
        resp = await c.get("/fees?period=2026-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 120000  # 본인 세대만, 타 세대(999999) 안 보임


async def test_resident_before_approval_month_empty(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    db_session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=households[(3, 301)],
            period="2026-06",
            breakdown={"일반관리비": 120000},
            total_amount=120000,
            source="excel",
        )
    )
    # 승인월 2026-07 > 조회월 2026-06 → 비공개.
    await _add_resident(
        db_session,
        households[(3, 301)],
        approved=datetime.datetime(2026, 7, 1, tzinfo=datetime.UTC),
    )
    async with _client(db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID) as c:
        resp = await c.get("/fees?period=2026-06")
    assert resp.status_code == 200
    assert resp.json()["total"] is None


async def test_resident_without_household_422(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    await _add_resident(
        db_session, None, approved=datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC)
    )
    async with _client(db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID) as c:
        resp = await c.get("/fees?period=2026-06")
    assert resp.status_code == 422


async def test_resident_prev_total_for_trend(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    for period, total in (("2026-05", 100000), ("2026-06", 120000)):
        db_session.add(
            Fee(
                tenant_id=TENANT_ID,
                household_id=households[(3, 301)],
                period=period,
                breakdown={"일반관리비": total},
                total_amount=total,
                source="excel",
            )
        )
    await _add_resident(
        db_session,
        households[(3, 301)],
        approved=datetime.datetime(2026, 4, 1, tzinfo=datetime.UTC),
    )
    async with _client(db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID) as c:
        resp = await c.get("/fees?period=2026-06")
    body = resp.json()
    assert body["total"] == 120000
    assert body["prev_total"] == 100000


# ── 관리자 월별 현황 ─────────────────────────────────────────────────────────


async def test_admin_list_month_summary(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    for hid, total in ((households[(3, 301)], 120000), (households[(3, 302)], 130000)):
        db_session.add(
            Fee(
                tenant_id=TENANT_ID,
                household_id=hid,
                period="2026-06",
                breakdown={"일반관리비": total},
                total_amount=total,
                source="excel",
            )
        )
    await db_session.flush()
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/admin/fees?period=2026-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["household_count"] == 2
    assert body["total_sum"] == 250000
    assert len(body["households"]) == 2


# ── AI 설명(SSE) ─────────────────────────────────────────────────────────────


async def test_explain_streams_citation_with_period(
    households: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_llm: LlmClient,
) -> None:
    db_session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=households[(3, 301)],
            period="2026-06",
            breakdown={"일반관리비": 100000, "청소비": 20000},
            total_amount=120000,
            source="excel",
        )
    )
    await _add_resident(
        db_session,
        households[(3, 301)],
        approved=datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC),
    )
    async with _client(
        db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID, llm=fake_llm
    ) as c:
        resp = await c.post("/fees/explain", json={"period": "2026-06"})
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    names = [n for n, _ in events]
    assert "token" in names
    assert names[-1] == "done"

    citation = next(data for name, data in events if name == "citation")
    assert citation["document_id"] is None
    assert "2026-06" in str(citation["document_title"])
    done = events[-1][1]
    assert done["status"] == "answered"
    assert done["needs_review"] is False


async def test_explain_missing_month_404(
    households: dict[tuple[int, int], uuid.UUID],
    db_session: AsyncSession,
    fake_llm: LlmClient,
) -> None:
    await _add_resident(
        db_session,
        households[(3, 301)],
        approved=datetime.datetime(2026, 5, 1, tzinfo=datetime.UTC),
    )
    async with _client(
        db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID, llm=fake_llm
    ) as c:
        resp = await c.post("/fees/explain", json={"period": "2026-06"})
    assert resp.status_code == 404


# ── 역할 가드 ────────────────────────────────────────────────────────────────


async def test_resident_cannot_upload(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    data = _fee_xlsx([("101", 3, 301, 100000, 20000)])
    async with _client(db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID) as c:
        resp = await _upload(c, data, "2026-06")
    assert resp.status_code == 403


async def test_staff_cannot_apply(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    storage = FakeStorage()
    data = _fee_xlsx([("101", 3, 301, 100000, 20000)])
    async with _client(db_session, storage) as c:
        up = await _upload(c, data, "2026-06")
        upload_id = up.json()["upload_id"]
    async with _client(db_session, storage, roles=("STAFF",)) as c:
        resp = await c.post(f"/admin/fees/uploads/{upload_id}/apply")
    assert resp.status_code == 403
