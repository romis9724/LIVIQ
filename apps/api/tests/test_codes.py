"""공통 코드 레지스트리 통합 — 실 PG (H8-4, ADR-0017).

CRUD·코드 트리(평면+parent_id)·인가 매트릭스(STAFF 조회만·RESIDENT 전부 403)·is_system 그룹
삭제 409·group_key 불변·순환 방지·그룹 내 code 중복·자식 있는 코드 삭제 409·tenant 격리를 본다.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from app.deps import (
    RequestContext,
    get_context,
    get_tenant_session,
    visibilities_for,
)
from app.main import create_app
from conftest import MANAGER_USER_ID, TENANT_ID
from httpx import ASGITransport
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.models import Code, CodeGroup, Notice, Tenant

TENANT_B_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")


async def _seed(session: AsyncSession) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(TENANT_ID))
    )
    session.add(Tenant(id=TENANT_ID, name="단지A", status="active"))
    await session.flush()


def _client(
    db_session: AsyncSession,
    *,
    roles: tuple[str, ...] = ("MANAGER",),
    tenant_id: uuid.UUID = TENANT_ID,
) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_context] = lambda: RequestContext(
        tenant_id, MANAGER_USER_ID, roles=roles, visibilities=visibilities_for(roles)
    )
    app.dependency_overrides[get_tenant_session] = lambda: db_session
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(db_session: AsyncSession) -> AsyncIterator[AsyncSession]:
    await _seed(db_session)
    yield db_session


# ── 그룹 CRUD ────────────────────────────────────────────────────────────────


async def test_create_group_and_list_returns_flat_codes(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        g = await c.post(
            "/admin/code-groups", json={"group_key": "INQUIRY_CATEGORY", "name": "민원 분류"}
        )
        assert g.status_code == 201, g.text
        gid = g.json()["id"]
        assert g.json()["is_system"] is False

        p = await c.post("/admin/codes", json={"group_id": gid, "code": "누수", "label": "누수"})
        assert p.status_code == 201, p.text
        parent_id = p.json()["id"]
        ch = await c.post(
            "/admin/codes",
            json={
                "group_id": gid,
                "code": "천장누수",
                "label": "천장 누수",
                "parent_id": parent_id,
            },
        )
        assert ch.status_code == 201, ch.text

        listed = await c.get("/admin/code-groups")
    assert listed.status_code == 200
    groups = {grp["group_key"]: grp for grp in listed.json()["items"]}
    assert "INQUIRY_CATEGORY" in groups
    codes = groups["INQUIRY_CATEGORY"]["codes"]
    assert len(codes) == 2
    child = next(c for c in codes if c["code"] == "천장누수")
    assert child["parent_id"] == parent_id  # 평면 + parent_id


async def test_create_group_rejects_lowercase_group_key(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        r = await c.post("/admin/code-groups", json={"group_key": "bad key", "name": "x"})
    assert r.status_code == 422


async def test_create_group_duplicate_key_409(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        assert (
            await c.post("/admin/code-groups", json={"group_key": "DUP", "name": "a"})
        ).status_code == 201
        dup = await c.post("/admin/code-groups", json={"group_key": "DUP", "name": "b"})
    assert dup.status_code == 409


async def test_patch_group_name_but_group_key_immutable(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        g = await c.post("/admin/code-groups", json={"group_key": "ORIG", "name": "원래"})
        gid = g.json()["id"]
        r = await c.patch(f"/admin/code-groups/{gid}", json={"name": "변경", "group_key": "HACKED"})
    assert r.status_code == 200
    assert r.json()["name"] == "변경"
    assert r.json()["group_key"] == "ORIG"  # group_key 변경 무시


async def test_delete_system_group_409(seeded: AsyncSession) -> None:
    group = CodeGroup(
        tenant_id=TENANT_ID, group_key="NOTICE_CATEGORY", name="공지 분류", is_system=True
    )
    seeded.add(group)
    await seeded.flush()
    async with _client(seeded) as c:
        r = await c.delete(f"/admin/code-groups/{group.id}")
    assert r.status_code == 409


async def test_delete_custom_group_cascades_codes(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        g = await c.post("/admin/code-groups", json={"group_key": "TEMP", "name": "임시"})
        gid = g.json()["id"]
        await c.post("/admin/codes", json={"group_id": gid, "code": "a", "label": "a"})
        r = await c.delete(f"/admin/code-groups/{gid}")
        assert r.status_code == 204
        listed = await c.get("/admin/code-groups")
    assert all(grp["group_key"] != "TEMP" for grp in listed.json()["items"])


# ── 코드 검증 ────────────────────────────────────────────────────────────────


async def test_create_code_duplicate_in_group_409(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        gid = (await c.post("/admin/code-groups", json={"group_key": "G", "name": "g"})).json()[
            "id"
        ]
        assert (
            await c.post("/admin/codes", json={"group_id": gid, "code": "X", "label": "X"})
        ).status_code == 201
        dup = await c.post("/admin/codes", json={"group_id": gid, "code": "X", "label": "X2"})
    assert dup.status_code == 409


async def test_create_code_parent_other_group_422(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        g1 = (await c.post("/admin/code-groups", json={"group_key": "G1", "name": "1"})).json()[
            "id"
        ]
        g2 = (await c.post("/admin/code-groups", json={"group_key": "G2", "name": "2"})).json()[
            "id"
        ]
        p = (await c.post("/admin/codes", json={"group_id": g1, "code": "p", "label": "p"})).json()[
            "id"
        ]
        r = await c.post(
            "/admin/codes", json={"group_id": g2, "code": "c", "label": "c", "parent_id": p}
        )
    assert r.status_code == 422


async def test_patch_code_cycle_409(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        gid = (await c.post("/admin/code-groups", json={"group_key": "G", "name": "g"})).json()[
            "id"
        ]
        a = (
            await c.post("/admin/codes", json={"group_id": gid, "code": "A", "label": "A"})
        ).json()["id"]
        b = (
            await c.post(
                "/admin/codes", json={"group_id": gid, "code": "B", "label": "B", "parent_id": a}
            )
        ).json()["id"]
        # A→B→A 순환 지정 거부.
        cycle = await c.patch(f"/admin/codes/{a}", json={"parent_id": b})
        assert cycle.status_code == 409
        # 자기 자신 부모 지정도 거부.
        self_ref = await c.patch(f"/admin/codes/{a}", json={"parent_id": a})
    assert self_ref.status_code == 409


async def test_delete_code_with_children_409(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        gid = (await c.post("/admin/code-groups", json={"group_key": "G", "name": "g"})).json()[
            "id"
        ]
        a = (
            await c.post("/admin/codes", json={"group_id": gid, "code": "A", "label": "A"})
        ).json()["id"]
        b = (
            await c.post(
                "/admin/codes", json={"group_id": gid, "code": "B", "label": "B", "parent_id": a}
            )
        ).json()["id"]
        with_child = await c.delete(f"/admin/codes/{a}")
        assert with_child.status_code == 409
        # 자식 먼저 삭제하면 부모 삭제 성공.
        assert (await c.delete(f"/admin/codes/{b}")).status_code == 204
        assert (await c.delete(f"/admin/codes/{a}")).status_code == 204


async def test_patch_code_updates_label_sort_active(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:
        gid = (await c.post("/admin/code-groups", json={"group_key": "G", "name": "g"})).json()[
            "id"
        ]
        cid = (
            await c.post("/admin/codes", json={"group_id": gid, "code": "A", "label": "A"})
        ).json()["id"]
        r = await c.patch(
            f"/admin/codes/{cid}", json={"label": "A2", "sort_order": 5, "active": False}
        )
    assert r.status_code == 200
    body = r.json()
    assert body["label"] == "A2" and body["sort_order"] == 5 and body["active"] is False


async def test_delete_code_referenced_by_notice_409(seeded: AsyncSession) -> None:
    """도메인(notices)이 참조 중인 코드는 FK RESTRICT → 409(H8-6). 코드는 남는다."""
    group = CodeGroup(
        tenant_id=TENANT_ID, group_key="NOTICE_CATEGORY", name="공지 분류", is_system=True
    )
    seeded.add(group)
    await seeded.flush()
    code = Code(tenant_id=TENANT_ID, group_id=group.id, code="일반", label="일반")
    seeded.add(code)
    await seeded.flush()
    seeded.add(
        Notice(
            tenant_id=TENANT_ID,
            title="공지",
            body="본문",
            status="draft",
            audience="ALL",
            category_code_id=code.id,
        )
    )
    await seeded.flush()

    async with _client(seeded) as c:
        response = await c.delete(f"/admin/codes/{code.id}")
    assert response.status_code == 409
    # SAVEPOINT 롤백 후에도 바깥 트랜잭션은 살아있어 코드가 그대로 조회된다.
    still_there = await seeded.scalar(select(Code.id).where(Code.id == code.id))
    assert still_there == code.id


# ── 인가 매트릭스 ─────────────────────────────────────────────────────────────


async def test_staff_can_read_but_not_write(seeded: AsyncSession) -> None:
    async with _client(seeded, roles=("STAFF",)) as c:
        assert (await c.get("/admin/code-groups")).status_code == 200
        assert (
            await c.post("/admin/code-groups", json={"group_key": "S", "name": "s"})
        ).status_code == 403


async def test_resident_denied_all(seeded: AsyncSession) -> None:
    async with _client(seeded, roles=("RESIDENT",)) as c:
        assert (await c.get("/admin/code-groups")).status_code == 403
        assert (
            await c.post("/admin/code-groups", json={"group_key": "R", "name": "r"})
        ).status_code == 403


# ── tenant 격리 ──────────────────────────────────────────────────────────────


async def test_cross_tenant_code_access_404(seeded: AsyncSession) -> None:
    async with _client(seeded) as c:  # 단지A 소유 코드 생성
        gid = (await c.post("/admin/code-groups", json={"group_key": "G", "name": "g"})).json()[
            "id"
        ]
        cid = (
            await c.post("/admin/codes", json={"group_id": gid, "code": "A", "label": "A"})
        ).json()["id"]

    async with _client(seeded, tenant_id=TENANT_B_ID) as c:  # 다른 단지 컨텍스트
        listed = await c.get("/admin/code-groups")
        assert listed.status_code == 200
        assert listed.json()["items"] == []  # 타 단지 그룹 미노출
        assert (await c.patch(f"/admin/codes/{cid}", json={"label": "x"})).status_code == 404
        assert (await c.delete(f"/admin/codes/{cid}")).status_code == 404
        assert (await c.delete(f"/admin/code-groups/{gid}")).status_code == 404
