"""seed_facilities_kapt.py — 첫마을 4단지 시설물 실데이터 시드 (H13-6 ②).

K-apt(공동주택관리정보시스템) A33982105 실측 시설물 + 표준 필수 설비 보강
(scripts/data/facilities_kapt.py — 상수)을 facilities 테이블에 적재한다.

멱등: (tenant_id, name) 기준 upsert — 있으면 type/location 갱신(status는 보존,
운영자가 바꾼 상태를 덮지 않는다), 없으면 status="normal"로 신규 생성. 삭제는 없다.
도메인 행 변경과 outbox_events 기록은 한 트랜잭션(app/routers/facilities.py의
_facility_snapshot·record_outbox 재사용 — 이중 쓰기 금지, docs/03 §4.9).

facilities 테이블에는 memo/description 컬럼이 없어(모델 확인) memo는 name에
" — " 구분자로 병기해 저장한다(data/facilities_kapt.py 모듈 docstring 참고).

실행(DATABASE_URL은 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync python scripts/seed_facilities_kapt.py [--tenant-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

from app.outbox import record_outbox
from app.routers.facilities import _facility_snapshot
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import Facility, Tenant

# scripts/data는 패키지가 아니라 폴더(namespace package, seed_floor_plans.py와 동일 관례) —
# 이 파일 자신의 디렉터리를 sys.path에 넣어 invocation 방식과 무관하게 임포트되게 한다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from data.facilities_kapt import ALLOWED_TYPES, FACILITIES  # noqa: E402

# 파일럿 단지(첫마을 4단지 푸르지오) — 다른 시드 스크립트와 동일 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

_MEMO_SEP = " — "  # facilities에 memo 컬럼이 없어 name에 병기하는 구분자


def _validate_types() -> None:
    """type 슬러그 오타 방지 — 허용 집합 밖 값이 있으면 즉시 중단."""
    bad = sorted({row["type"] for row in FACILITIES} - ALLOWED_TYPES)
    if bad:
        raise SystemExit(f"허용되지 않은 시설 type: {', '.join(bad)}")


def _full_name(row: dict[str, Any]) -> str:
    memo = row.get("memo")
    return f"{row['name']}{_MEMO_SEP}{memo}" if memo else row["name"]


async def _upsert_facility(
    session: AsyncSession, tenant_id: uuid.UUID, row: dict[str, Any]
) -> tuple[Facility, bool]:
    """(facility, is_new) 반환 — status는 기존 행이면 보존."""
    name = _full_name(row)
    existing = await session.scalar(
        select(Facility).where(
            Facility.tenant_id == tenant_id,
            Facility.name == name,
            Facility.deleted_at.is_(None),
        )
    )
    if existing is not None:
        existing.type = row["type"]
        existing.location = row["location"]
        return existing, False

    facility = Facility(
        tenant_id=tenant_id,
        name=name,
        location=row["location"],
        type=row["type"],
        status="normal",
    )
    session.add(facility)
    await session.flush()
    return facility, True


def _report(created: int, updated: int) -> None:
    by_type: dict[str, int] = {}
    for row in FACILITIES:
        by_type[row["type"]] = by_type.get(row["type"], 0) + 1
    print(f"시설 총 {len(FACILITIES)}건 · 신규 {created} · 갱신 {updated}")
    for type_name, count in sorted(by_type.items()):
        print(f"  {type_name}: {count}건")


async def _run(tenant_id: uuid.UUID) -> None:
    _validate_types()
    engine = create_engine()
    factory = create_session_factory(engine)
    try:
        async with factory() as session, session.begin():
            if await session.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None:
                raise SystemExit(f"단지를 찾을 수 없습니다: {tenant_id}")
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            created = 0
            updated = 0
            for row in FACILITIES:
                facility, is_new = await _upsert_facility(session, tenant_id, row)
                await session.flush()
                await record_outbox(
                    session,
                    tenant_id=tenant_id,
                    aggregate_type="facility",
                    aggregate_id=facility.id,
                    event_type="created" if is_new else "updated",
                    payload=_facility_snapshot(facility),
                )
                created += is_new
                updated += not is_new
        _report(created, updated)
        print(f"단지: {tenant_id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="첫마을 4단지 시설물 실데이터 시드(H13-6 ②)")
    parser.add_argument(
        "--tenant-id",
        type=uuid.UUID,
        default=DEFAULT_TENANT_ID,
        help=f"대상 단지 UUID (기본: 첫마을 4단지 {DEFAULT_TENANT_ID})",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.tenant_id))


if __name__ == "__main__":
    main()
