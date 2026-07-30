"""그래프 시드 상수 무결성 (G1b) — DB·Neo4j 없이 scripts/data 상수만 검증.

DB 연동(incident/maintenance upsert·LINKED_TO 재색인)은 dev에서 실행하므로 여기서
다루지 않는다. 이 테스트는 상수 자체의 정합성(개수·인과 순서·설비 이름·device_type
어휘)을 실행 없이 잡아낸다.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/는 패키지가 아니라 import path에 직접 추가(다른 스크립트 테스트와 동일 관행).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from data.facilities_kapt import FACILITIES  # noqa: E402
from data.floor_plan_annotations import ELEMENTS  # noqa: E402
from data.graph_seed import (  # noqa: E402
    INCIDENTS,
    LINKED_TO_MAP,
    MAINTENANCE,
    UNMAPPED_DEVICE_TYPES,
)

# facilities_kapt의 FACILITIES 이름 집합(생성된 승강기명 포함).
_FACILITY_NAMES = {row["name"] for row in FACILITIES}
# 세대 평면도 device_type 어휘(elements의 type + 방 마커 "room").
_DEVICE_VOCAB = {e["type"] for e in ELEMENTS} | {"room"}


def test_incident_and_maintenance_counts() -> None:
    assert len(INCIDENTS) == 16
    assert len(MAINTENANCE) == 22


def test_incident_keys_unique() -> None:
    keys = [inc.key for inc in INCIDENTS]
    assert len(keys) == len(set(keys))


def test_caused_by_references_existing_key() -> None:
    keys = {inc.key for inc in INCIDENTS}
    for inc in INCIDENTS:
        if inc.caused_by is not None:
            assert inc.caused_by in keys, f"미존재 caused_by: {inc.caused_by}"


def test_effect_not_before_cause() -> None:
    """인과 연쇄에서 결과는 원인보다 앞설 수 없다(occurred_at 순서 강제)."""
    by_key = {inc.key: inc for inc in INCIDENTS}
    chains = [(inc, by_key[inc.caused_by]) for inc in INCIDENTS if inc.caused_by]
    assert len(chains) == 4  # SEED-PLAN §1 인과 엣지 4건
    for effect, cause in chains:
        assert effect.occurred_at >= cause.occurred_at, (
            f"{effect.key}({effect.occurred_at}) < 원인 {cause.key}({cause.occurred_at})"
        )


def test_all_facility_names_exist() -> None:
    referenced = (
        {inc.facility_name for inc in INCIDENTS}
        | {mnt.facility_name for mnt in MAINTENANCE}
        | set(LINKED_TO_MAP.values())
    )
    missing = referenced - _FACILITY_NAMES
    assert not missing, f"facilities_kapt에 없는 이름: {sorted(missing)}"


def test_linked_to_keys_are_device_types() -> None:
    unknown = set(LINKED_TO_MAP) - _DEVICE_VOCAB
    assert not unknown, f"device_type 어휘 밖 키: {sorted(unknown)}"


def test_unmapped_device_types_not_wired() -> None:
    assert {"가스밸브", "에어컨 배관", "경량칸막이", "room"} == UNMAPPED_DEVICE_TYPES
    assert not (set(LINKED_TO_MAP) & UNMAPPED_DEVICE_TYPES)
