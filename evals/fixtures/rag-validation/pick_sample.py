"""OpenAI 축 측정용 층화 표본 선정 (H15-2).

500 케이스 전수를 외부 API로 돌리면 비용이 과하다. **판별력이 확인된 카테고리**(로컬 기준선
R6~R12에서 자동 채점이 유효했던 6종)만 남기고 카테고리 × priority로 층화해 뽑는다.

선정 규칙:
1. 모집단은 기본 `--set critical`(Critical 180) — 로컬 확정 기준선(R9·R12)이 같은 모집단이라
   표본 케이스ID로 기존 결과 JSON을 필터하면 **재측정 없이 짝지은 비교**가 된다.
2. 판별 카테고리에 비례 배분 + 카테고리당 최소 MIN_PER_CATEGORY건(반복 변동폭 ±8%p 고려).
3. 인젝션은 **Hard Gate 관측 전용 정액 쿼터**(사실 채점 불가 — 적대적 지시 복창을 외부 모델에서도
   보는 것이 목적). 카테고리별 집계라 품질 평균을 오염시키지 않는다.
4. 측정 불가 카테고리(관리비·KG·문서버전)는 기본 제외 — `--include-excluded`로만 포함.
5. 랜덤이 아니라 **정렬 후 균등 간격 추출**(case_id 오름차순). `--seed`는 간격 내 위상만
   옮기므로 결과는 항상 재현된다.

출력은 원본과 **같은 열 구조의 CSV**(rag500.mjs가 읽을 수 있는 형태) + 같은 이름의 `.ids.txt`
(쉼표 목록 — 러너에 파일 지정 옵션이 없어 `--case=$(cat ...)`로 투입한다).

실행:
    uv run --no-sync python evals/fixtures/rag-validation/pick_sample.py --size 72
    uv run --no-sync python evals/fixtures/rag-validation/pick_sample.py --selfcheck
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
SOURCE_CSV = BASE / "quality-cases-500.csv"
DEFAULT_OUT = BASE / "sample-openai.csv"
DEFAULT_SIZE = 72
MIN_PER_CATEGORY = 8

# 자동 채점이 유효한 카테고리 — 비례 배분 대상(R6 §저조 카테고리 원인 규명).
DISCRIMINATIVE = (
    "계정·온보딩·개인정보",
    "안전·법률 등 고위험 질문",
    "민원·업무 절차",
    "시설·점검·유지보수",
    "관리규약·공지·생활 안내",
    "답변 불가·모호한 질문·폴백",
)
# 정액 쿼터: 사실 채점은 불가하지만 Hard Gate(적대적 지시 복창) 관측 가치가 있다 — llama3.1에서
# 실측 2~4건. 표본이 커도 늘리지 않는다(품질 지표에 쓰지 않으므로 관측용 최소 수량).
GATE_ONLY_QUOTA = {"프롬프트 인젝션·적대적 질문": 6}
# 균등 간격으로 뽑으면 실제 위반 케이스를 놓친다(첫 시행에서 확인 — 표본 72건 6회 실행 hardfail 0).
# 로컬 10회 실행에서 llama3.1이 반복 위반한 케이스를 못으로 박아 **같은 프롬프트로 외부 모델을
# 비교**한다. 빈도: QA-0460 7회 · QA-0474 5회 · QA-0464·0470·0473 각 3회.
GATE_ONLY_PINNED = {
    "프롬프트 인젝션·적대적 질문": ("QA-0460", "QA-0464", "QA-0470", "QA-0473", "QA-0474"),
}
# 측정 불가 — 사유를 남긴다(제외를 결정으로 기록).
EXCLUDED_REASONS = {
    "다중 문서·Knowledge Graph": "합성 단지에 시설·그래프 데이터 없음 — 인용이 구조적으로 불가(R6)",
    "문서 버전·충돌·기준 시점": "citations에 revision 필드 없음 — 파이프라인 한계(R6·보고서 §5.1)",
    "관리비 조회·설명": "케이스셋 fee_data 과요구 결함 잔재 — 인용 적중 21%가 상한(R8)",
}


def load_rows(path: Path, execution_set: str) -> list[dict[str, str]]:
    """CSV 로드 + execution_set 필터(all이면 전건). 원본 행을 그대로 보존한다."""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    if execution_set.lower() == "all":
        return rows
    wanted = execution_set.lower()
    return [r for r in rows if r["execution_set"].lower() == wanted]


def allocate(pool: dict[str, int], size: int, minimum: int) -> dict[str, int]:
    """카테고리별 배분 수 — 최소 보장 후 잔여를 모집단 크기 비례(최대 잉여법)로 나눈다.

    모집단이 최소 수량보다 작으면 그 카테고리는 전건 사용(잔여 배분에서 빠진다).
    """
    base = {cat: min(minimum, n) for cat, n in pool.items()}
    remaining = size - sum(base.values())
    if remaining < 0:
        return _trim(base, pool, size)
    if remaining == 0:
        return base
    room = {cat: pool[cat] - base[cat] for cat in pool}
    total_room = sum(room.values())
    if total_room == 0:
        return base
    exact = {cat: remaining * room[cat] / total_room for cat in pool}
    extra = {cat: min(room[cat], int(exact[cat])) for cat in pool}
    # 내림으로 남은 자리는 소수부가 큰 카테고리부터(같으면 모집단이 큰 쪽, 그다음 이름순 — 결정적)
    leftover = remaining - sum(extra.values())
    order = sorted(pool, key=lambda c: (-(exact[c] - int(exact[c])), -pool[c], c))
    for cat in order:
        if leftover <= 0:
            break
        if extra[cat] < room[cat]:
            extra[cat] += 1
            leftover -= 1
    return {cat: base[cat] + extra[cat] for cat in pool}


def _trim(base: dict[str, int], pool: dict[str, int], size: int) -> dict[str, int]:
    """최소 보장 합이 size를 넘을 때(카테고리가 너무 많을 때) 큰 쪽부터 1건씩 깎는다."""
    out = dict(base)
    while sum(out.values()) > size:
        cat = max(out, key=lambda c: (out[c], pool[c], c))
        if out[cat] == 0:
            break
        out[cat] -= 1
    return out


def pick_even(items: list[dict[str, str]], count: int, seed: int) -> list[dict[str, str]]:
    """정렬된 목록에서 균등 간격 추출(랜덤 아님 — 항상 같은 결과).

    간격 step = len/count. i번째는 floor((i + phase) * step) — step >= 1이므로 인덱스는
    단조 증가하고 중복되지 않는다. phase는 seed로만 정해지는 [0,1) 위상.
    """
    if count <= 0:
        return []
    if count >= len(items):
        return list(items)
    step = len(items) / count
    phase = (seed % 100) / 100
    return [items[int((i + phase) * step)] for i in range(count)]


def pick_sample(
    rows: list[dict[str, str]], *, size: int, seed: int, include_excluded: bool
) -> list[dict[str, str]]:
    """층화(카테고리 × priority) 표본. 결과는 case_id 오름차순."""
    by_category: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        category = row["category"]
        if category in GATE_ONLY_QUOTA:
            continue
        if category in EXCLUDED_REASONS and not include_excluded:
            continue
        if category not in DISCRIMINATIVE and category not in EXCLUDED_REASONS:
            continue
        by_category.setdefault(category, []).append(row)

    gate_only = {
        cat: [r for r in rows if r["category"] == cat]
        for cat in GATE_ONLY_QUOTA
        if any(r["category"] == cat for r in rows)
    }
    gate_size = sum(min(GATE_ONLY_QUOTA[cat], len(pool)) for cat, pool in gate_only.items())
    quotas = allocate(
        {cat: len(pool) for cat, pool in by_category.items()},
        max(0, size - gate_size),
        MIN_PER_CATEGORY,
    )

    picked: list[dict[str, str]] = []
    for cat, pool in sorted(by_category.items()):
        picked += _pick_by_priority(pool, quotas[cat], seed)
    for cat, pool in sorted(gate_only.items()):
        picked += _pick_gate_only(cat, pool, min(GATE_ONLY_QUOTA[cat], len(pool)), seed)
    return sorted(picked, key=lambda r: r["case_id"])


def _pick_gate_only(
    category: str, pool: list[dict[str, str]], count: int, seed: int
) -> list[dict[str, str]]:
    """게이트 관측 쿼터 — 못 박은 실제 위반 케이스 우선, 남는 자리는 균등 간격."""
    pinned_ids = GATE_ONLY_PINNED.get(category, ())
    pinned = [r for r in pool if r["case_id"] in pinned_ids][:count]
    rest = [r for r in pool if r["case_id"] not in {p["case_id"] for p in pinned}]
    return pinned + pick_even(sorted(rest, key=lambda r: r["case_id"]), count - len(pinned), seed)


def _pick_by_priority(pool: list[dict[str, str]], count: int, seed: int) -> list[dict[str, str]]:
    """카테고리 안에서 priority 비례 배분 후 층별 균등 간격 추출.

    현 케이스셋은 priority가 카테고리로 결정되므로(계정=P0 등) 실제로는 단일 층이지만,
    라벨이 갈라져도 비율이 유지되도록 층화 코드를 유지한다.
    """
    strata: dict[str, list[dict[str, str]]] = {}
    for row in pool:
        strata.setdefault(row["priority"], []).append(row)
    quotas = allocate({p: len(rs) for p, rs in strata.items()}, count, 0)
    out: list[dict[str, str]] = []
    for priority, rows_of in sorted(strata.items()):
        ordered = sorted(rows_of, key=lambda r: r["case_id"])
        out += pick_even(ordered, quotas[priority], seed)
    return out


def write_sample(rows: list[dict[str, str]], out: Path, fieldnames: list[str]) -> Path:
    """원본과 동일한 열·순서로 저장(BOM 포함 — 원본과 같은 인코딩). ids 목록도 함께."""
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    ids_path = out.with_suffix(".ids.txt")
    ids_path.write_text(",".join(r["case_id"] for r in rows) + "\n", encoding="utf-8")
    return ids_path


def print_summary(rows: list[dict[str, str]], population: list[dict[str, str]]) -> None:
    pool = Counter(r["category"] for r in population)
    picked = Counter(r["category"] for r in rows)
    print(f"\n선정 {len(rows)}건 / 모집단 {len(population)}건\n")
    print(f"  {'카테고리':<24} {'선정':>4} {'모집단':>6} {'비율':>6}  구분")
    for cat, n in picked.most_common():
        kind = "게이트 관측" if cat in GATE_ONLY_QUOTA else "판별"
        if cat in EXCLUDED_REASONS:
            kind = "제외 카테고리(강제 포함)"
        print(f"  {cat:<24} {n:>4} {pool[cat]:>6} {n / pool[cat] * 100:>5.0f}%  {kind}")
    print(
        "\n  priority 분포: "
        + " · ".join(f"{p} {n}건" for p, n in sorted(Counter(r["priority"] for r in rows).items()))
    )
    print("  turn 합계(질의 수): " + str(sum(_turn_count(r) for r in rows)))
    for cat, reason in sorted(EXCLUDED_REASONS.items()):
        if cat not in picked:
            print(f"  제외 — {cat}: {reason}")


def _turn_count(row: dict[str, str]) -> int:
    return sum(1 for key in ("turn_1", "turn_2", "turn_3") if row[key].strip())


def selfcheck() -> int:
    """실 케이스셋으로 돌리는 최소 검증 — 배분·결정성·필드 구조."""
    population = load_rows(SOURCE_CSV, "critical")
    sample = pick_sample(population, size=DEFAULT_SIZE, seed=0, include_excluded=False)
    assert len(sample) == DEFAULT_SIZE, f"표본 크기 {len(sample)} != {DEFAULT_SIZE}"

    counts = Counter(r["category"] for r in sample)
    for cat in DISCRIMINATIVE:
        assert counts[cat] >= MIN_PER_CATEGORY, f"{cat} {counts[cat]}건 — 최소 미달"
    for cat, quota in GATE_ONLY_QUOTA.items():
        assert counts[cat] == quota, f"{cat} {counts[cat]}건 != 쿼터 {quota}"
    for cat in EXCLUDED_REASONS:
        assert counts[cat] == 0, f"{cat} 기본 표본에 포함됨"

    ids = [r["case_id"] for r in sample]
    for cat, pinned in GATE_ONLY_PINNED.items():
        missing = set(pinned) - set(ids)
        assert not missing, f"{cat} 못 박은 케이스 누락: {sorted(missing)}"
    assert len(set(ids)) == len(ids), "case_id 중복"
    assert ids == sorted(ids), "case_id 정렬 아님"
    again = pick_sample(population, size=DEFAULT_SIZE, seed=0, include_excluded=False)
    assert [r["case_id"] for r in again] == ids, "같은 seed에서 결과가 다름(비결정적)"
    shifted = pick_sample(population, size=DEFAULT_SIZE, seed=50, include_excluded=False)
    assert [r["case_id"] for r in shifted] != ids, "seed 위상이 선택을 바꾸지 않음"

    source = {r["case_id"]: r for r in load_rows(SOURCE_CSV, "all")}
    for row in sample:
        assert row == source[row["case_id"]], f"{row['case_id']} 원본 행과 불일치"

    with_excluded = pick_sample(population, size=DEFAULT_SIZE, seed=0, include_excluded=True)
    assert len(with_excluded) == DEFAULT_SIZE, "include-excluded에서 크기 붕괴"
    assert set(EXCLUDED_REASONS) & {r["category"] for r in with_excluded}, "제외 카테고리 미포함"
    print(f"selfcheck ok — 표본 {DEFAULT_SIZE}건 · 카테고리 {len(counts)}종 · 필드 구조 원본 동일")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenAI 측정용 층화 표본 선정 (H15-2)")
    parser.add_argument(
        "--size", type=int, default=DEFAULT_SIZE, help=f"표본 크기(기본 {DEFAULT_SIZE})"
    )
    parser.add_argument("--seed", type=int, default=0, help="균등 간격의 위상(0~99, 결정적)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="출력 CSV 경로")
    parser.add_argument(
        "--set",
        dest="execution_set",
        default="critical",
        help="모집단 execution_set(기본 critical)",
    )
    parser.add_argument(
        "--include-excluded", action="store_true", help="측정 불가 카테고리도 포함(기본 제외)"
    )
    parser.add_argument("--selfcheck", action="store_true", help="자체 검증만 실행")
    args = parser.parse_args()
    if args.selfcheck:
        return selfcheck()
    if args.size < 1:
        parser.error("--size는 1 이상")

    with SOURCE_CSV.open(encoding="utf-8-sig", newline="") as fh:
        fieldnames = list(csv.DictReader(fh).fieldnames or [])
    population = load_rows(SOURCE_CSV, args.execution_set)
    if not population:
        parser.error(f"모집단 0건 — --set {args.execution_set} 확인")
    sample = pick_sample(
        population, size=args.size, seed=args.seed, include_excluded=args.include_excluded
    )
    ids_path = write_sample(sample, args.out, fieldnames)
    print_summary(sample, population)
    print(f"\n  CSV: {args.out}\n  케이스ID: {ids_path}")
    print(
        f"  러너 투입: node evals/rag500.mjs --set=all --case=$(cat {ids_path}) --label=<backend>\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
