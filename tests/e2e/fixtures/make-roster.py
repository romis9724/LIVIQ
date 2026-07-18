"""가입 여정(H6-4) 명부 픽스처 생성 — roster-e2e.xlsx.

roster.py EXPECTED_HEADER(성함|생년월일|동|층|호)와 fixtures.ts ROSTER_PERSON 을 그대로 반영한다.
값을 바꾸면 fixtures.ts ROSTER_PERSON 도 함께 고쳐야 매칭(name_hash+birth_hash)이 유지된다.
재생성: `cd apps/api && uv run --no-sync python ../../tests/e2e/fixtures/make-roster.py`
"""

from __future__ import annotations

import datetime
from pathlib import Path

from openpyxl import Workbook

OUT = Path(__file__).with_name("roster-e2e.xlsx")

wb = Workbook()
ws = wb.active
ws.append(["성함", "생년월일", "동", "층", "호"])
# fixtures.ts ROSTER_PERSON 과 동일: 김입주 · 1990-05-15 · 101동 3층 301호.
ws.append(["김입주", datetime.date(1990, 5, 15), "101", 3, 301])
wb.save(OUT)
print(f"wrote {OUT}")
