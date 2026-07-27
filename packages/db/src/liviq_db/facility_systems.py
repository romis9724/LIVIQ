"""시설 계통 약어 + 시설 코드 부여 규칙 — 단일 출처 (H14-2).

시설 코드는 A안 `{계통약어}-{위치약어}-{연번}`(예 `EL-401-01`)이다. 서버가 부여하고
사용자는 수정할 수 없다(입력 스키마에 노출 없음). 약어표는 `FACILITY_SYSTEMS` 하나에서
공통 코드 그룹 `FACILITY_SYSTEM` 시드(codes_seed)와 부여 규칙이 함께 파생한다.

여기 있는 것은 전부 순수 함수 — 마이그레이션 백필(alembic)과 런타임 부여
(apps/api/app/facility_code.py)가 같은 규칙을 공유하려면 DB 패키지에 있어야 한다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import NamedTuple


class FacilitySystem(NamedTuple):
    slug: str  # facilities.type 값
    abbr: str  # 코드 계통 약어
    label: str


FACILITY_SYSTEMS: tuple[FacilitySystem, ...] = (
    FacilitySystem("elevator", "EL", "승강기"),
    FacilitySystem("fire", "FR", "소방"),
    FacilitySystem("electric", "EC", "전기"),
    FacilitySystem("water", "WT", "급배수"),
    FacilitySystem("heating", "HT", "난방"),
    FacilitySystem("community", "CM", "커뮤니티"),
    FacilitySystem("security", "SC", "보안"),
    FacilitySystem("parking", "PK", "주차"),
    FacilitySystem("network", "NW", "통신"),
    FacilitySystem("sanitation", "SN", "위생"),
)

ABBR_BY_SLUG: dict[str, str] = {system.slug: system.abbr for system in FACILITY_SYSTEMS}

GENERAL_ABBR = "GN"  # type 미지정·미등록 계통
COMMON_LOCATION = "CMN"  # location에 숫자가 없거나 비어 있음(공용)

_LOCATION_DIGITS = re.compile(r"\d+")


def facility_code_prefix(type_: str | None, location: str | None) -> str:
    """`{계통약어}-{위치약어}` — 연번을 뺀 코드 앞부분("401동" → "401", 없으면 "CMN")."""
    abbr = ABBR_BY_SLUG.get(type_ or "", GENERAL_ABBR)
    digits = _LOCATION_DIGITS.search(location or "")
    return f"{abbr}-{digits.group() if digits else COMMON_LOCATION}"


def format_facility_code(prefix: str, seq: int) -> str:
    """연번은 2자리 0패딩 — 99를 넘으면 자릿수가 자연히 늘어난다(100 → `EL-401-100`)."""
    return f"{prefix}-{seq:02d}"


def next_facility_code(prefix: str, existing: Iterable[str]) -> str:
    """같은 prefix의 기존 코드 중 최대 연번 + 1(삭제분도 세어 재사용하지 않는다)."""
    head = f"{prefix}-"
    seqs = [
        int(code[len(head) :])
        for code in existing
        if code.startswith(head) and code[len(head) :].isdigit()
    ]
    return format_facility_code(prefix, max(seqs, default=0) + 1)
