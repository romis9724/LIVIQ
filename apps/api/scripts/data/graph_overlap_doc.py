"""겹침 문서 렌더 상수 (G1c — GraphRAG 비교 pgvector 쪽).

같은 장애를 그래프(Neo4j incident)와 문서(pgvector 청크) 양쪽으로 넣어 동일 질의를
교차 비교하기 위한 겹침 문서 1건의 마크다운을 graph_seed.INCIDENTS 상수에서 **렌더**한다.
서술 문구를 새로 창작하지 않는다 — symptom·root_cause·resolution을 그대로 옮겨 문서
사실이 그래프 사실과 by construction 동일해지도록 한다(SEED-PLAN §3 공정성 통제).

청크 경계 고정: incident당 정확히 1청크가 되도록 각 장애를 `## {symptom}` 섹션 하나로
만든다(문서 1건→여러 청크의 top_k 편향 제거). 문서 제목은 마크다운 `#`가 아니라
Document.title 컬럼에 넣는다 — 그래야 `##` 섹션 수 = incident 수 = 청크 수로 딱 맞는다.

본문에 `제N조` 패턴·점선 리더(`···`·`......`)를 넣지 않는다 — 청커(chunking.py)가 각각
가짜 조항 경계·목차 줄로 오인해 청크를 쪼개거나 본문을 삭제한다.
"""

from __future__ import annotations

from data.graph_seed import INCIDENTS, IncidentSeed

# SEED-PLAN §3 병렬 10쌍 — 문서·그래프 교차 비교 대상 incident key.
INCLUDED_KEYS: tuple[str, ...] = ("1", "2", "4", "5", "6", "8", "9", "10", "12", "13")

# Document.title 컬럼 값(SEED-PLAN §3). 본문 마크다운에는 `#` 제목을 넣지 않는다.
OVERLAP_DOC_TITLE = "설비 장애·정비 이력 요약(2024~2026)"

_by_key: dict[str, IncidentSeed] = {inc.key: inc for inc in INCIDENTS}


def _render_section(inc: IncidentSeed) -> str:
    """장애 1건 → `## {증상}` 섹션(incident당 1청크). 본문은 원인·조치만."""
    return f"## {inc.symptom}\n\n원인: {inc.root_cause}. 조치: {inc.resolution}."


# INCLUDED_KEYS 순서로 렌더한 섹션들을 빈 줄로 결합(맨 앞에 `#` 제목 없음).
# 모든 key가 INCIDENTS에 존재하는지는 test_graph_overlap_doc.py가 검증한다.
OVERLAP_DOC_MD: str = "\n\n".join(_render_section(_by_key[key]) for key in INCLUDED_KEYS)
