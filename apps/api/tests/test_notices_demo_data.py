"""공지 데모 시드 상수 무결성 — DB 없이 scripts/data/notices_demo.py만 검증.

시드 실행은 dev에서 하므로 여기서는 상수 정합성만 본다. 잡아야 할 실패는 둘이다.
①category가 NOTICE_CATEGORY 시드 라벨(liviq_db.codes_seed 단일 출처)에서 벗어나면
시드가 category_code_id=NULL로 들어간다(분류 필터·칩이 빈다).
②제목 중복은 멱등 upsert(제목 기준)를 깨뜨려 seed_demo의 개수 assert가 실패한다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from liviq_db.codes_seed import DEFAULT_CODE_GROUPS

# scripts/는 패키지가 아니라 import path에 직접 추가(다른 스크립트 테스트와 동일 관행).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from data.notices_demo import NOTICES  # noqa: E402

_NOTICE_CATEGORY_LABELS = {
    c.code for g in DEFAULT_CODE_GROUPS if g.group_key == "NOTICE_CATEGORY" for c in g.codes
}


def test_notice_count() -> None:
    assert len(NOTICES) == 86


def test_titles_unique() -> None:
    titles = [n.title for n in NOTICES]
    assert len(titles) == len(set(titles))


def test_categories_exist_in_code_seed() -> None:
    unknown = {n.category for n in NOTICES} - _NOTICE_CATEGORY_LABELS
    assert not unknown, f"NOTICE_CATEGORY 시드에 없는 분류: {sorted(unknown)}"


def test_event_period_is_ordered() -> None:
    for notice in NOTICES:
        if notice.event_start is not None and notice.event_end is not None:
            assert notice.event_start <= notice.event_end, notice.title
