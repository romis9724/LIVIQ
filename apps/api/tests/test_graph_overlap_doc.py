"""겹침 문서 청크 경계 자기검증 (G1c) — 실 청커로 SEED-PLAN §3 불변식 확인.

DB·MinIO 없이 로컬 실행. incident당 1청크(top_k 편향 제거)·토큰 상한·같은 사실·
가짜 조항 경계 없음을 실 청커(ai_core.rag.chunk_text)로 잡아낸다.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from ai_core.rag import chunk_text

# scripts/는 패키지가 아니라 import path에 직접 추가(다른 스크립트 테스트와 동일 관행).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from data.graph_overlap_doc import INCLUDED_KEYS, OVERLAP_DOC_MD  # noqa: E402
from data.graph_seed import INCIDENTS  # noqa: E402

_by_key = {inc.key: inc for inc in INCIDENTS}


def test_included_keys_exist() -> None:
    keys = {inc.key for inc in INCIDENTS}
    assert len(INCLUDED_KEYS) == 10
    assert set(INCLUDED_KEYS) <= keys, f"INCIDENTS에 없는 key: {set(INCLUDED_KEYS) - keys}"


def test_one_chunk_per_incident() -> None:
    """SEED-PLAN §3 핵심 불변식 — incident당 정확히 1청크."""
    chunks = chunk_text(OVERLAP_DOC_MD)
    assert len(chunks) == 10


def test_chunks_within_token_limit() -> None:
    for chunk in chunk_text(OVERLAP_DOC_MD):
        assert chunk.token_count <= 400, f"{chunk.token_count} > 400: {chunk.heading}"


def test_fairness_same_facts() -> None:
    """문서가 그래프와 같은 사실(symptom·root_cause·resolution)을 담는다."""
    contents = [chunk.content for chunk in chunk_text(OVERLAP_DOC_MD)]
    for key in INCLUDED_KEYS:
        inc = _by_key[key]
        for fact in (inc.symptom, inc.root_cause, inc.resolution):
            assert any(fact in content for content in contents), f"{key}: 누락 사실 '{fact}'"


def test_no_spurious_clause_boundary() -> None:
    """가짜 조항 경계 방지 — 본문에 `제N조` 패턴이 없어야 한다(청커가 섹션 경계로 오인)."""
    assert not re.search(r"제\s?\d+\s?조", OVERLAP_DOC_MD)
