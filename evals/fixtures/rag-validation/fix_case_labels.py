"""케이스 라벨 어긋남 교정 — 질문이 명시한 문서를 기대 출처에 반영 (H15-2).

생성 산물 결함: 질문은 특정 문서 제목("공용에너지 비용 안내에 따르면…")을 지목하는데 기대
출처(expected_citations)에는 다른 문서가 적혀 있는 케이스가 11건. AI가 질문이 지목한 문서를
인용해도 오답 처리되어 관리비·문서버전 카테고리 인용 적중률을 0%대로 끌어내렸다(R6·R7 실측).

교정 방식: **기존 기대 출처를 지우지 않고**, 질문이 명시한 문서를 앞에 덧붙인다(둘 다 허용).
채점기는 기대 문서 전부를 요구하므로, 라벨 오류를 정답 확대가 아니라 "질문이 지목한 문서를
인용하면 인정"으로 좁힌다 — 그래서 덧붙이는 대신 **명시 문서로 교체**한다.

실행: uv run --no-sync python evals/fixtures/rag-validation/fix_case_labels.py [--apply]
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent
CSV_PATH = BASE / "quality-cases-500.csv"


def load_docs() -> dict[str, dict]:
    manifest = json.loads((BASE / "manifest.json").read_text())
    return {d["document_id"]: d for d in manifest["documents"]}


def _titled_doc(question: str, docs: dict[str, dict]) -> tuple[str, dict] | None:
    """질문이 제목을 그대로 명시한 문서 — 가장 긴 제목 우선(부분 일치 오탐 방지)."""
    hits = [(did, d) for did, d in docs.items() if d["title"] in question]
    if not hits:
        return None
    return max(hits, key=lambda kv: len(kv[1]["title"]))


def _rewrite_citations(raw: str, doc_id: str, doc: dict) -> str:
    """명시 문서를 기대 출처의 문서 항목으로 교체. fee_data 등 비문서 출처는 보존."""
    parts = [s.strip() for s in raw.split("|") if s.strip()]
    kept: list[str] = []
    # fee_data 그룹(문서ID가 아닌 출처)은 그대로 남긴다 — 관리비 확정 데이터 요구는 유효할 수 있다.
    if parts and parts[0] == "fee_data":
        idx = next((i for i, p in enumerate(parts[1:], 1) if p.startswith(("A-", "B-", "C-"))), None)
        kept = parts[:idx] if idx else parts
    clause = doc["clauses"][0]["label"] if doc.get("clauses") else "문서 본문"
    tail = [doc_id, clause, doc.get("page_or_section", "문서 본문"), f"rev {doc['revision']}"]
    return " | ".join([*kept, *tail])


def main() -> int:
    apply = "--apply" in sys.argv
    docs = load_docs()
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows = list(reader)

    fixed = 0
    skipped: list[str] = []
    for r in rows:
        hit = _titled_doc(r["turn_1"], docs)
        if hit is None:
            continue
        doc_id, doc = hit
        if doc_id in r["expected_citations"]:
            continue
        # 구판·초안(is_current=false)을 기대 출처로 만들면 "stale 문서 인용 금지"(규칙 1·Hard
        # Gate)를 정답화한다 — 이 카테고리(문서 버전·충돌)는 질문이 구판 제목을 명시하는 것
        # 자체가 함정이므로 라벨을 고치지 않고 남긴다(현행 파이프라인 한계로 별도 기록).
        if not doc.get("is_current", True):
            skipped.append(f"{r['case_id']} [{r['category']}] {doc['title']} — 구판·초안이라 교정 제외")
            continue
        before = r["expected_citations"]
        r["expected_citations"] = _rewrite_citations(before, doc_id, doc)
        fixed += 1
        print(f"{r['case_id']} [{r['category']}] {doc['title']}")
        print(f"  before: {before}")
        print(f"  after : {r['expected_citations']}")

    for s in skipped:
        print(f"SKIP {s}")
    print(f"\n교정 대상 {fixed}건 · 제외 {len(skipped)}건 · apply={apply}")
    if apply and fixed:
        with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"기록: {CSV_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
