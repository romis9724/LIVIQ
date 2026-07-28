"""quality-cases-500.csv ↔ fixture 정합 검수 (H15-2 선행).

LLM 생성 케이스셋의 흔한 결함을 자동 검출한다:
1. Expected Citations의 출처가 실제 존재하는가
   - 문서ID → manifest.documents · 조항 라벨까지 대조
   - `fee_data` → seed/fees.json의 세대·월 존재 대조 (관리비는 확정 데이터가 출처 — 규칙 5)
   - KG 문서 → kg/expected_truth.json evidence 대조
2. 인용 문서 tenant ↔ 케이스 tenant 일치 (격리 위반 라벨 검출)
3. Fixture IDs 존재 (구분자 `|`·`,` 혼용 허용 — 데이터 실태)
4. Expected Facts ↔ 인용 조항 원문 토큰 겹침 (낮으면 사람 확인 대상 — 오탐 감수)
5. case_id 중복·필수 필드 누락

실행: uv run --no-sync python evals/fixtures/rag-validation/verify_cases.py
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent
NO_CITATION_GATES = {"금지", "없음", "해당 없음", "n/a", "N/A"}
FACT_OVERLAP_WARN = 0.15  # 자카드 미만이면 사람 확인 대상
# 출처 토큰: 문서ID(A-RULE-001-V2 등) 또는 fee_data. 세대 id(A-HH-*)는 fee 그룹의 속성이지 출처가 아니다.
_SOURCE_RE = re.compile(r"^(?:[A-C]-(?!HH-)[A-Z]+-\d+(?:-V\d+)?|fee_data)$")
_HOUSEHOLD_RE = re.compile(r"^[A-C]-HH-\d+$")
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[가-힣a-zA-Z0-9]{2,}", text))


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _split_citation_groups(raw: str) -> list[list[str]]:
    """출처 토큰이 나올 때마다 새 그룹 — 카테고리별 필드 수(3·4·가변)를 흡수한다."""
    groups: list[list[str]] = []
    for token in (s.strip() for s in raw.split("|")):
        if not token:
            continue
        if _SOURCE_RE.match(token) or not groups:
            groups.append([token])
        else:
            groups[-1].append(token)
    return groups


def load_fixtures() -> tuple[dict, dict, set, dict]:
    manifest = json.loads((BASE / "manifest.json").read_text())
    docs = {d["document_id"]: d for d in manifest["documents"]}
    clauses = {
        d["document_id"]: {c["label"]: c["text"] for c in d.get("clauses", [])}
        for d in manifest["documents"]
    }
    fees = json.loads((BASE / "seed" / "fees.json").read_text())
    fee_keys = {(f["household_id"], f["period"]) for f in fees}
    truths = json.loads((BASE / "kg" / "expected_truth.json").read_text())
    kg_tokens: dict[str, set[str]] = {}
    for t in truths:
        bag = kg_tokens.setdefault(t["evidence_document_id"], set())
        bag |= _tokens(f"{t['subject']} {t['relation']} {t['object']}")
    return docs, clauses, fee_keys, kg_tokens


def main() -> int:
    docs, clauses, fee_keys, kg_tokens = load_fixtures()
    rows = list(csv.DictReader((BASE / "quality-cases-500.csv").open(encoding="utf-8-sig")))

    problems: list[str] = []
    fact_review: list[str] = []
    ids = Counter(r["case_id"] for r in rows)
    problems += [f"{cid}: case_id 중복 {n}회" for cid, n in ids.items() if n > 1]

    for r in rows:
        cid = r["case_id"]
        if not r["turn_1"].strip():
            problems.append(f"{cid}: turn_1 비어 있음")

        for fid in filter(None, (s.strip() for s in re.split(r"[|,]", r["fixture_ids"]))):
            if fid not in docs:
                problems.append(f"{cid}: fixture '{fid}' manifest에 없음")

        if r["citation_gate"].strip() in NO_CITATION_GATES:
            continue

        fact_tokens = _tokens(r["expected_facts"])
        clause_tokens: set[str] = set()
        has_fee_source = False
        for group in _split_citation_groups(r["expected_citations"]):
            source = group[0]
            if source == "fee_data":
                has_fee_source = True
                hh = next((t for t in group if _HOUSEHOLD_RE.match(t)), None)
                month = next((t for t in group if _MONTH_RE.match(t)), None)
                if hh and month and (hh, month) not in fee_keys:
                    problems.append(f"{cid}: fee_data {hh} {month} — seed/fees.json에 없음")
                continue
            if source not in docs:
                problems.append(f"{cid}: 인용 출처 '{source}' manifest에 없음")
                continue
            if docs[source]["tenant_id"] != r["tenant_id"]:
                problems.append(
                    f"{cid}: 인용 문서 {source}({docs[source]['tenant_id']})가 "
                    f"케이스 tenant({r['tenant_id']})와 불일치"
                )
            for label in (t for t in group[1:] if t.startswith("제")):
                if label not in clauses[source]:
                    problems.append(f"{cid}: {source}에 '{label}' 조항 없음")
            clause_tokens |= _tokens(" ".join(clauses[source].values()))
            clause_tokens |= kg_tokens.get(source, set())

        # 관리비 케이스의 기대 사실은 조항이 아니라 fee 시드에서 나온다 — 겹침 검사 제외
        if fact_tokens and clause_tokens and not has_fee_source:
            score = _jaccard(fact_tokens, clause_tokens)
            if score < FACT_OVERLAP_WARN:
                fact_review.append(f"{cid} [{r['category']}]: 겹침 {score:.2f}")

    print(f"케이스 {len(rows)}건 · 문서 {len(docs)}건 · fee 시드 {len(fee_keys)}건 검수")
    print(f"구조 결함: {len(problems)}건")
    for p in problems[:40]:
        print(" ✗", p)
    print(f"기대사실 겹침 낮음(사람 확인 대상): {len(fact_review)}건")
    for p in fact_review[:30]:
        print(" ?", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
