"""관리비 라우터 통합 — 실 PG + FakeStorage + fake LLM(SSE).

단지 총액 트리 업로드·미리보기 → 세대수(574) 균등분배 후 401동 201호 1건 적재(H8-7)
→ 본인 세대·승인 후 월만(FR-FEE-03) → AI 설명(SSE·확정 데이터 출처) → 역할 가드(규칙 4·5).
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
from app.routers.fees import HOUSEHOLD_DIVISOR
from conftest import MANAGER_USER_ID, TENANT_ID, USER_ID, FakeStorage, seed_tenant
from httpx import ASGITransport
from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.llm.client import LlmClient
from liviq_db.models import Building, Fee, Household, User

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_TREE_HEADER = ("분류", "우리단지총액")

# 실단지 트리 축약본(레벨/이름/단지총액). 분배 검산은 test_fees_excel이 담당.
_TREE_ROWS: tuple[tuple[str, int], ...] = (
    ("공용관리비", 46762861),
    ("  일반관리비", 24210020),
    ("  청소비", 7250220),
    ("개별사용료", 47700530),
    ("  난방비", 7808640),
    ("    수도 공용", -156720),
    ("장기수선충당금 월부과액", 6905380),
    ("  충당금잔액", 233697416),
    ("합계", 101368771),
    ("잡수입", 1589874),
)


def _tree_xlsx(rows: tuple[tuple[str, int], ...] = _TREE_ROWS) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.append(list(_TREE_HEADER))
    for name, amount in rows:
        sheet.append([name, amount])
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


async def _add_target_household(session: AsyncSession) -> uuid.UUID:
    """401동 201호(2층) 세대 시드 — apply 분배 대상."""
    building_id = uuid.uuid4()
    session.add(Building(id=building_id, tenant_id=TENANT_ID, name="401", floors=25))
    await session.flush()
    hid = uuid.uuid4()
    session.add(
        Household(
            id=hid,
            tenant_id=TENANT_ID,
            building_id=building_id,
            floor=2,
            unit_no=201,
            status="active",
        )
    )
    await session.flush()
    return hid


def _row(name: str, level: int, amount: int) -> dict[str, object]:
    return {"name": name, "level": level, "amount": amount}


@pytest_asyncio.fixture
async def households(db_session: AsyncSession) -> AsyncIterator[dict[tuple[int, int], uuid.UUID]]:
    hmap = await seed_tenant(db_session)
    yield hmap


# ── 업로드·검증(총액 트리) ─────────────────────────────────────────────────


async def test_upload_previews_divided_top_levels(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    async with _client(db_session, FakeStorage()) as c:
        resp = await _upload(c, _tree_xlsx(), "2026-07")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "validated"
    assert body["row_count"] == len(_TREE_ROWS)
    assert body["total"] == 176601  # 합계행 / 574
    # 미리보기는 상위 레벨(level<=1)만.
    assert all(r["level"] <= 1 for r in body["preview"])
    top = {r["name"]: r["amount"] for r in body["preview"]}
    assert top["공용관리비"] == 81468
    assert top["일반관리비"] == 42178
    # 확정 전에는 fees 미기록.
    count = await db_session.scalar(select(func.count()).select_from(Fee))
    assert count == 0


async def test_upload_non_numeric_amount_422(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    data = _tree_xlsx((("공용관리비", 100), ("  일반관리비", "많음"),))  # type: ignore[arg-type]
    async with _client(db_session, FakeStorage()) as c:
        resp = await _upload(c, data, "2026-07")
    assert resp.status_code == 422


async def test_upload_bad_period_422(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    async with _client(db_session, FakeStorage()) as c:
        resp = await _upload(c, _tree_xlsx(), "2026-13")
    assert resp.status_code == 422


async def test_get_upload_detail(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    storage = FakeStorage()
    async with _client(db_session, storage) as c:
        up = await _upload(c, _tree_xlsx(), "2026-07")
        upload_id = up.json()["upload_id"]
        detail = await c.get(f"/admin/fees/uploads/{upload_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "validated"
    assert body["period"] == "2026-07"
    assert body["row_count"] == len(_TREE_ROWS)


async def test_get_upload_detail_not_found_404(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get(f"/admin/fees/uploads/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── 확정 적재(401동 201호 1건) ─────────────────────────────────────────────


async def test_apply_inserts_single_household_with_divided_tree(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    target = await _add_target_household(db_session)
    storage = FakeStorage()
    async with _client(db_session, storage) as c:
        up = await _upload(c, _tree_xlsx(), "2026-07")
        apply = await c.post(f"/admin/fees/uploads/{up.json()['upload_id']}/apply")
    assert apply.status_code == 200, apply.text
    assert apply.json()["applied"] == 1

    fees = list(await db_session.scalars(select(Fee).where(Fee.period == "2026-07")))
    assert len(fees) == 1
    fee = fees[0]
    assert fee.household_id == target
    assert fee.total_amount == 176601
    assert fee.source == "excel"
    # breakdown = 순서 보존 리스트.
    assert isinstance(fee.breakdown, list)
    assert fee.breakdown[0] == {"name": "공용관리비", "level": 0, "amount": 81468}
    neg = next(r for r in fee.breakdown if r["name"] == "수도 공용")
    assert neg["amount"] == -273  # 음수 유지


async def test_apply_without_target_household_422(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    storage = FakeStorage()  # 401동 201호 미시드 → 422
    async with _client(db_session, storage) as c:
        up = await _upload(c, _tree_xlsx(), "2026-07")
        apply = await c.post(f"/admin/fees/uploads/{up.json()['upload_id']}/apply")
    assert apply.status_code == 422


async def test_apply_replaces_target_household_month(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    target = await _add_target_household(db_session)
    # 기존 7월 데이터(값 다름) — apply가 교체.
    db_session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=target,
            period="2026-07",
            breakdown=[_row("합계", 0, 1)],
            total_amount=1,
            source="excel",
        )
    )
    await db_session.flush()
    storage = FakeStorage()
    async with _client(db_session, storage) as c:
        up = await _upload(c, _tree_xlsx(), "2026-07")
        await c.post(f"/admin/fees/uploads/{up.json()['upload_id']}/apply")
    july = list(await db_session.scalars(select(Fee).where(Fee.period == "2026-07")))
    assert len(july) == 1
    assert july[0].total_amount == 176601


async def test_apply_requires_validated_status(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    await _add_target_household(db_session)
    storage = FakeStorage()
    async with _client(db_session, storage) as c:
        up = await _upload(c, _tree_xlsx(), "2026-07")
        upload_id = up.json()["upload_id"]
        first = await c.post(f"/admin/fees/uploads/{upload_id}/apply")
        assert first.status_code == 200
        again = await c.post(f"/admin/fees/uploads/{upload_id}/apply")
    assert again.status_code == 409


# ── FR-FEE-03 (CRITICAL): 본인 세대 + 승인 이후 월만 ─────────────────────────


async def test_resident_sees_own_household_only(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    for hid, total in ((households[(3, 301)], 120000), (households[(3, 302)], 999999)):
        db_session.add(
            Fee(
                tenant_id=TENANT_ID,
                household_id=hid,
                period="2026-06",
                breakdown=[_row("합계", 0, total)],
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
    assert body["total"] == 120000  # 본인 세대만
    assert body["breakdown"][0]["name"] == "합계"  # 리스트 포맷


async def test_resident_before_approval_month_empty(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    db_session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=households[(3, 301)],
            period="2026-06",
            breakdown=[_row("합계", 0, 120000)],
            total_amount=120000,
            source="excel",
        )
    )
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
                breakdown=[_row("합계", 0, total)],
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


# ── 관리자 월별 현황·검색·고지서 상세 ───────────────────────────────────────


async def test_admin_list_month_summary_and_search(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    for (floor, unit), total in (((3, 301), 120000), ((3, 302), 130000)):
        db_session.add(
            Fee(
                tenant_id=TENANT_ID,
                household_id=households[(floor, unit)],
                period="2026-06",
                breakdown=[_row("합계", 0, total)],
                total_amount=total,
                source="excel",
            )
        )
    await db_session.flush()
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get("/admin/fees?period=2026-06")
        assert resp.json()["household_count"] == 2
        assert resp.json()["total_sum"] == 250000
        # 호 검색 필터.
        filtered = await c.get("/admin/fees?period=2026-06&unit=301")
    body = filtered.json()
    assert body["household_count"] == 1
    assert body["households"][0]["unit_no"] == 301


async def test_admin_fee_detail(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    hid = households[(3, 301)]
    db_session.add(
        Fee(
            tenant_id=TENANT_ID,
            household_id=hid,
            period="2026-06",
            breakdown=[_row("공용관리비", 0, 81468), _row("합계", 0, 176601)],
            total_amount=176601,
            source="excel",
        )
    )
    await db_session.flush()
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get(f"/admin/fees/{hid}?period=2026-06")
    assert resp.status_code == 200
    body = resp.json()
    assert body["building_name"] == "101"
    assert body["unit_no"] == 301
    assert body["total"] == 176601
    assert [r["name"] for r in body["breakdown"]] == ["공용관리비", "합계"]


async def test_admin_fee_detail_missing_404(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    async with _client(db_session, FakeStorage()) as c:
        resp = await c.get(f"/admin/fees/{households[(3, 301)]}?period=2026-06")
    assert resp.status_code == 404


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
            breakdown=[_row("공용관리비", 0, 81468), _row("급여", 3, 27214), _row("합계", 0, 176601)],
            total_amount=176601,
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
    assert events[-1][1]["status"] == "answered"


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
    async with _client(db_session, FakeStorage(), roles=("RESIDENT",), user_id=USER_ID) as c:
        resp = await _upload(c, _tree_xlsx(), "2026-07")
    assert resp.status_code == 403


async def test_staff_cannot_apply(
    households: dict[tuple[int, int], uuid.UUID], db_session: AsyncSession
) -> None:
    await _add_target_household(db_session)
    storage = FakeStorage()
    async with _client(db_session, storage) as c:
        up = await _upload(c, _tree_xlsx(), "2026-07")
        upload_id = up.json()["upload_id"]
    async with _client(db_session, storage, roles=("STAFF",)) as c:
        resp = await c.post(f"/admin/fees/uploads/{upload_id}/apply")
    assert resp.status_code == 403


# HOUSEHOLD_DIVISOR 상수 참조(계약 고정 확인).
def test_household_divisor_is_574() -> None:
    assert HOUSEHOLD_DIVISOR == 574
