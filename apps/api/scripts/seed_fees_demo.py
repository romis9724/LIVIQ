"""seed_fees_demo.py — 첫마을 4단지 전 세대 × 6개월 관리비 데모 시드.

seed_demo.py의 FEE_TREE(실단지 2026-07 단지 총액 트리)를 574세대로 분배한 값을 **기준**
삼아, 세대(평형)·월(계절)·세대별 지터로 변주해 2026-02~2026-08 7개월치를 전 세대에 넣는다.
관리비 화면·AI 설명 데모가 "한 세대 한 달"이 아니라 실제 단지처럼 보이게 하는 용도다.

변주 규칙(코드가 계산 — AI 미개입, CLAUDE 절대규칙 5):
  · 평형 계수: 공용관리비 하위 전부 + 장기수선충당금은 면적 비례(84M ×1.12 / 59C ×0.79).
    개별사용료 **전용** 항목은 완만한 상관만(×1.08 / ×0.88) — TV수신료는 정액이라 제외.
  · 월 계수: 난방·급탕·전기는 계절 사용량 곡선(2월 난방 성수기 → 7월 최저).
  · 세대 지터: 전용 사용료 ±10% · 공용 사용료 ±3% · 공용관리비 ±1%.
    난수는 (세대, 월, 항목) 시드의 결정적 난수라 재실행해도 같은 값이 나온다.
  · 충당금잔액·적립요율·잡수입은 세대별로 변하는 값이 아니므로 기준값 유지.

부모 행은 자식 합으로 재계산한다. 단, 원본 트리에서 자식 합이 부모와 다른 행
(교육훈련비 = 세부 미기재, 장기수선충당금 월부과액 = 자식이 잔액/요율)은 리프로 취급해
직접 스케일한다 — 그러지 않으면 재계산이 금액을 지운다.

멱등: 대상 period의 해당 단지 fees 행을 전부 delete 후 insert(§4.6 재업로드 = 전 행 교체).

실행(DATABASE_URL은 apps/api/.env에서 로드):

    cd apps/api
    uv run --no-sync --env-file .env python scripts/seed_fees_demo.py [--tenant-id <uuid>]
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import uuid
from pathlib import Path
from typing import Any, NamedTuple

from app.fees_excel import FeeTreeRow, divide_fee_tree
from app.routers.fees import HOUSEHOLD_DIVISOR
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from liviq_db.engine import create_engine, create_session_factory
from liviq_db.models import Building, Fee, Household, HouseholdGeometry

# scripts는 패키지가 아니라 폴더 — 자기 디렉터리를 sys.path에 넣어 invocation 방식과
# 무관하게 임포트되게 한다(seed_floor_plans.py와 동일 관례). seed_demo는 수정하지 않는다.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from seed_demo import FEE_TOTAL_ROW, FEE_TREE  # noqa: E402

# 파일럿 단지(첫마을 4단지 푸르지오) — 다른 시드 스크립트와 동일 tenant.
DEFAULT_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")

PERIODS: tuple[str, ...] = (
    "2026-02",
    "2026-03",
    "2026-04",
    "2026-05",
    "2026-06",
    "2026-07",
    "2026-08",
)

# 대분류(level 0) 이름 — 섹션별로 변주 규칙이 다르다.
SECTION_COMMON = "공용관리비"
SECTION_USAGE = "개별사용료"
SECTION_LONG_TERM = "장기수선충당금 월부과액"
TOTAL_SECTIONS = (SECTION_COMMON, SECTION_USAGE, SECTION_LONG_TERM)

# 평형 계수(전용면적 비례) — unit_type_label "84M(공공임대)" → 키 "84M".
AREA_FACTORS: dict[str, float] = {"84M": 1.12, "59C": 0.79}
# 전용 사용료는 면적 상관이 약하다(사용량은 세대 인원·생활패턴이 더 크다) — 완만한 계수.
USAGE_AREA_FACTORS: dict[str, float] = {"84M": 1.08, "59C": 0.88}
FALLBACK_UNIT_TYPE = "84M"  # geometry 없는 세대(평형 미상)는 다수 평형으로 간주

# 월 계수 — 항목명 접두사별 계절 사용량 곡선.
USAGE_MONTH_FACTORS: dict[str, dict[str, float]] = {
    "난방": {
        "2026-02": 2.6,
        "2026-03": 1.9,
        "2026-04": 1.0,
        "2026-05": 0.4,
        "2026-06": 0.15,
        "2026-07": 0.1,
        "2026-08": 0.1,
    },
    "급탕": {
        "2026-02": 1.3,
        "2026-03": 1.2,
        "2026-04": 1.0,
        "2026-05": 0.9,
        "2026-06": 0.85,
        "2026-07": 0.8,
        "2026-08": 0.75,
    },
    "전기": {
        "2026-02": 1.05,
        "2026-03": 1.0,
        "2026-04": 1.0,
        "2026-05": 1.0,
        "2026-06": 1.05,
        "2026-07": 1.2,
        "2026-08": 1.35,
    },
}
FLAT_MONTH_FACTOR = 1.0  # 수도료·TV수신료 등 계절성 없는 항목

# 세대 지터 폭(±비율).
JITTER_PRIVATE = 0.10  # 전용 사용료 — 세대 생활패턴 차이
JITTER_SHARED = 0.03  # 공용 사용료 — 세대별 배분 차이
JITTER_COMMON = 0.01  # 공용관리비 — 거의 균등

PRIVATE_SUFFIX = "전용"  # "난방 전용"처럼 세대 전용 사용분
# 면적과 무관한 정액 항목 — 전용 사용료지만 평형 계수를 적용하지 않는다.
FLAT_RATE_ITEMS = frozenset({"TV방송수신료 전용"})

# 세대·월에 따라 변하지 않는 참고 수치(잔액·요율) — 기준값 유지.
KEEP_AS_IS = frozenset({"충당금잔액", "적립요율(%)"})

FEE_SOURCE = "excel"  # 데모지만 원천 계약은 엑셀 업로드와 동일(§4.6)


class RowMeta(NamedTuple):
    """기준 breakdown 한 행의 변주 메타 — 세대·월과 무관하므로 1회만 계산한다."""

    name: str
    level: int
    base_amount: int
    section: str  # 속한 level 0 대분류 이름
    children: tuple[int, ...]  # 직속 자식 인덱스(재계산 대상일 때만 비어있지 않음)


class HouseholdRow(NamedTuple):
    """시드 대상 세대."""

    id: uuid.UUID
    building_name: str
    unit_type: str  # "84M" | "59C"


def _base_breakdown() -> list[dict[str, Any]]:
    """실단지 총액 트리 / 574세대 — 라우터와 동일한 divide_fee_tree(코드 계산)."""
    rows = [FeeTreeRow(level=level, name=name, amount=amount) for level, name, amount in FEE_TREE]
    return divide_fee_tree(rows, HOUSEHOLD_DIVISOR)


def _direct_children(base: list[dict[str, Any]], index: int) -> tuple[int, ...]:
    """index 행의 직속 자식(level+1) 인덱스 — 다음 형제/상위 행을 만나면 종료."""
    level = int(base[index]["level"])
    found: list[int] = []
    for offset in range(index + 1, len(base)):
        child_level = int(base[offset]["level"])
        if child_level <= level:
            break
        if child_level == level + 1:
            found.append(offset)
    return tuple(found)


def _build_metas(base: list[dict[str, Any]]) -> list[RowMeta]:
    """행별 섹션·재계산 여부를 미리 계산한다."""
    if len(base) != len(FEE_TREE):
        raise SystemExit("분배 결과가 원본 트리와 행 수가 다릅니다")
    # 정합 판정은 **단지 총액**(반올림 전)으로 한다 — 분배값은 행마다 독립 반올림돼
    # 자식 합이 부모와 몇 원씩 어긋난다(divide_fee_tree 주석 참조).
    tree_amounts = [amount for _, _, amount in FEE_TREE]
    metas: list[RowMeta] = []
    section = ""
    for index, row in enumerate(base):
        name = str(row["name"])
        level = int(row["level"])
        amount = int(row["amount"])
        if level == 0:
            section = name
        children = _direct_children(base, index)
        # 원본 트리에서 자식 합 == 부모 금액인 행만 재계산 대상. 합이 어긋나는 행
        # (교육훈련비·장기수선충당금 월부과액)은 리프처럼 직접 스케일한다.
        is_recalc = bool(children) and sum(tree_amounts[c] for c in children) == tree_amounts[index]
        metas.append(
            RowMeta(
                name=name,
                level=level,
                base_amount=amount,
                section=section,
                children=children if is_recalc else (),
            )
        )
    return metas


def _usage_month_factor(name: str, period: str) -> float:
    for prefix, table in USAGE_MONTH_FACTORS.items():
        if name.startswith(prefix):
            return table[period]
    return FLAT_MONTH_FACTOR


def _jitter(household_id: uuid.UUID, period: str, name: str, width: float) -> float:
    """(세대, 월, 항목) 결정적 난수 — 재실행해도 같은 금액이 나온다."""
    rng = random.Random(f"{household_id}:{period}:{name}")  # 데모 데이터용(암호 용도 아님)
    return rng.uniform(1.0 - width, 1.0 + width)


def _leaf_factor(meta: RowMeta, household: HouseholdRow, period: str) -> float:
    """리프 한 행에 적용할 배율(평형 × 월 × 지터)."""
    if meta.name in KEEP_AS_IS:
        return 1.0
    area = AREA_FACTORS[household.unit_type]
    if meta.section == SECTION_COMMON:
        return area * _jitter(household.id, period, meta.name, JITTER_COMMON)
    if meta.section == SECTION_LONG_TERM:
        return area  # 면적 비례 고정 부과 — 세대 지터 없음
    if meta.section == SECTION_USAGE:
        is_private = meta.name.endswith(PRIVATE_SUFFIX)
        width = JITTER_PRIVATE if is_private else JITTER_SHARED
        # 전용 사용량만 완만한 면적 상관. 공용 배분분·정액 항목(TV수신료)은 면적 무관.
        usage_area = (
            USAGE_AREA_FACTORS[household.unit_type]
            if is_private and meta.name not in FLAT_RATE_ITEMS
            else 1.0
        )
        return (
            usage_area
            * _usage_month_factor(meta.name, period)
            * _jitter(household.id, period, meta.name, width)
        )
    return 1.0  # 잡수입 등 — 기준값 유지


def build_breakdown(
    metas: list[RowMeta], total_index: int, household: HouseholdRow, period: str
) -> list[dict[str, Any]]:
    """세대·월 breakdown 생성 — 리프 스케일 → 부모 재계산(역순) → 합계."""
    amounts = [
        0 if meta.children else round(meta.base_amount * _leaf_factor(meta, household, period))
        for meta in metas
    ]
    for index in reversed(range(len(metas))):
        children = metas[index].children
        if children:
            amounts[index] = sum(amounts[child] for child in children)
    amounts[total_index] = sum(
        amounts[i] for i, meta in enumerate(metas) if meta.name in TOTAL_SECTIONS
    )
    return [
        {"name": meta.name, "level": meta.level, "amount": amounts[index]}
        for index, meta in enumerate(metas)
    ]


def _unit_type_of(label: str | None) -> str:
    """unit_type_label "84M(공공임대)" → "84M". 미상·미등록 평형은 fallback."""
    key = label.split("(")[0].strip() if label else ""
    return key if key in AREA_FACTORS else FALLBACK_UNIT_TYPE


async def _load_households(session: AsyncSession, tenant_id: uuid.UUID) -> list[HouseholdRow]:
    rows = (
        await session.execute(
            select(Household.id, Building.name, HouseholdGeometry.unit_type_label)
            .join(Building, Building.id == Household.building_id)
            .outerjoin(HouseholdGeometry, HouseholdGeometry.household_id == Household.id)
            .where(Household.tenant_id == tenant_id)
            .order_by(Building.name, Household.floor, Household.unit_no)
        )
    ).all()
    return [
        HouseholdRow(id=hid, building_name=building, unit_type=_unit_type_of(label))
        for hid, building, label in rows
    ]


def _assert_invariants(metas: list[RowMeta], total_index: int) -> None:
    """쓰기 전 자체 점검 — 평형·계절 계수가 의도대로 총액에 반영되는지."""
    sample = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
    large = HouseholdRow(id=sample, building_name="401", unit_type="84M")
    small = HouseholdRow(id=sample, building_name="401", unit_type="59C")

    def total(household: HouseholdRow, period: str) -> int:
        return int(build_breakdown(metas, total_index, household, period)[total_index]["amount"])

    assert total(large, PERIODS[0]) > total(small, PERIODS[0]), "84M 총액이 59C보다 커야 한다"
    assert total(large, PERIODS[0]) > total(large, PERIODS[-1]), "2월(난방)이 7월보다 커야 한다"


def _report(households: list[HouseholdRow], totals: dict[tuple[str, uuid.UUID], int]) -> None:
    print(f"세대 {len(households)}건 × {len(PERIODS)}개월 = {len(totals)}행 적재")
    unit_type_of = {household.id: household.unit_type for household in households}

    print("\n월별 평균 총액")
    for period in PERIODS:
        month = [amount for (p, _), amount in totals.items() if p == period]
        print(f"  {period}: {len(month):4d}행 · 평균 {sum(month) // len(month):,}원")

    print("\n평형별 평균 총액(전 기간)")
    by_unit_type: dict[str, list[int]] = {}
    for (_, household_id), amount in totals.items():
        by_unit_type.setdefault(unit_type_of[household_id], []).append(amount)
    for unit_type, amounts in sorted(by_unit_type.items()):
        print(
            f"  {unit_type}: {len(amounts):4d}행 · 평균 {sum(amounts) // len(amounts):,}원"
            f" · 최소 {min(amounts):,} · 최대 {max(amounts):,}"
        )


async def _run(tenant_id: uuid.UUID) -> None:
    base = _base_breakdown()
    metas = _build_metas(base)
    total_index = next(i for i, meta in enumerate(metas) if meta.name == FEE_TOTAL_ROW)
    _assert_invariants(metas, total_index)

    engine = create_engine()
    factory = create_session_factory(engine)
    totals: dict[tuple[str, uuid.UUID], int] = {}
    try:
        async with factory() as session, session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)").bindparams(t=str(tenant_id))
            )
            households = await _load_households(session, tenant_id)
            if not households:
                raise SystemExit(f"세대가 없습니다: {tenant_id}")
            # 재업로드 계약과 동일 — 대상 월의 기존 행은 전부 교체(멱등).
            await session.execute(
                delete(Fee).where(Fee.tenant_id == tenant_id, Fee.period.in_(PERIODS))
            )
            for period in PERIODS:
                for household in households:
                    breakdown = build_breakdown(metas, total_index, household, period)
                    total = int(breakdown[total_index]["amount"])
                    totals[(period, household.id)] = total
                    session.add(
                        Fee(
                            tenant_id=tenant_id,
                            household_id=household.id,
                            period=period,
                            breakdown=breakdown,
                            total_amount=total,
                            source=FEE_SOURCE,
                        )
                    )
            await session.flush()
        _report(households, totals)
        print(f"\n단지: {tenant_id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="첫마을 4단지 전 세대 6개월 관리비 데모 시드")
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
