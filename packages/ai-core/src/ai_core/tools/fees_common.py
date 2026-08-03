"""관리비 도구 공용 조각 — 범위(scope) 정규화와 원시 SELECT.

`get_fees`(library.py)와 `compare_fees`(fees_compare.py)가 **같은 SQL·같은 표본 하한**을
쓰게 만드는 단일 지점이다. 두 도구가 같은 달에 다른 숫자를 내면 사용자에겐 그냥 버그다
(규칙 5 — 관리비는 확정 데이터가 단일 출처).

library.py가 도구 등록부라 fees_compare.py를 import한다 — 공용 조각이 library.py에 남으면
순환 import가 된다. 그래서 조각만 이 모듈로 내렸다.

tenant_id·user_id는 항상 `ToolContext`에서 오며 LLM 인자로 받지 않는다(규칙 3·4).
"""

from __future__ import annotations

import datetime
import re
from typing import Any, NamedTuple

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

from ai_core.tools.registry import ToolContext, ToolDeps

# ponytail: orchestrator.py에도 같은 한 줄이 있다 — tz 상수 하나를 위해 공용 모듈을 새로
# 만들지 않는다(fees_common이 orchestrator를 import하면 순환).
KST = datetime.timezone(datetime.timedelta(hours=9))

# 같은 평형·동·단지 평균 비교의 표본 하한(ADR-0026 결정 3). 미달이면 비교를 생략한다 —
# 소표본 평균은 본인 값과 함께 특정 세대 금액을 역산시킨다(n=2면 상대 세대 금액이 그대로
# 나온다). 첫마을 4단지는 322세대이고 소수 평형(59C)도 수십 세대라, 10이면 역산은
# 불가능하면서 비교는 거의 항상 성립한다.
MIN_PEER_SAMPLE = 10

# 조회할 월 — 한 달(2026-06) 또는 쉼표로 나열한 여러 달(2026-06,2026-07).
# 배열 인자가 아니라 쉼표 문자열인 이유: 8B는 배열 인자 생성에 약하고, 인자 개수가 늘수록
# 라우팅이 함께 무너진다(R22 계열 — LongtermParkingArgs와 같은 판단).
PERIOD_PATTERN = r"^\d{4}-\d{2}(\s*,\s*\d{4}-\d{2})*$"

# 집계 범위(H20-1) — "전체"·"단지" 같은 사용자 어휘를 접어 넣는 내부 표기(동 이름과 절대
# 겹치지 않는 값). 이 값이면 동 조인 없이 단지 전체를 집계한다.
COMPLEX_SCOPE = "__complex__"
# 요청자 본인 세대(H20-1 후속) — get_fees는 이 갈래를 "미지정"으로 접고, compare_fees는
# 비교 대상 하나로 쓴다.
SELF_SCOPE = "__self__"

_COMPLEX_SCOPE_WORDS = frozenset(
    {
        "전체",
        "단지",
        "단지전체",
        "전체단지",
        "전체동",
        "모든동",
        "아파트전체",
        "우리단지",
        "전세대",
        # dev 실측: "아파트 관리비는?"가 본인 조회로 흘렀다 — 단독 "아파트"도 전체다
        # (동 이름은 "401" 형식이라 충돌 없음).
        "아파트",
        "아파트평균",
        "전체평균",
    }
)
# dev 실측: 모델이 본인 질문에도 scope="본인 세대"를 채운다 — 본인 동의어는 접어서 처리한다
# (설명의 "본인 질문에는 쓰지 않는다"만으로는 안 막혔다. 코드가 방어 — 규칙 8의 정신).
# 1인칭 대명사까지 넓힌 건 "나의 관리비는?"이 scope="나"(= 동 이름 취급)로 샌 실측 때문이다.
_SELF_SCOPE_WORDS = frozenset(
    {
        "본인",
        "본인세대",
        "우리집",
        "우리세대",
        "내집",
        "자기집",
        "세대",
        "나",
        "나의",
        "나의집",
        "저",
        "저희",
        "저희집",
        "우리",
        "내",
    }
)

_NULL_LITERALS = ("", "null", "none")


def fold_null_literal(value: object) -> object:
    """8B가 "생략"을 문자열 "null"로 넘긴다 — 리터럴 null/none/빈 값은 미지정(None)으로.

    2026-08-01 실측: {"period":"null"} → 패턴 검증 실패 → 카드 0 → no_evidence 폴백.
    """
    if isinstance(value, str) and value.strip().lower() in _NULL_LITERALS:
        return None
    return value


# 월 토큰 관용(H20-18) — "2026-07"·"2026-7"·"7월"·(period 필드 한정)"7".
# 8B는 여러 달을 나열할 때 **연도를 뺀다**: dev 3/3 실측 `period="7월,8월"` → PERIOD_PATTERN
# 검증 실패 → invalid_args → 폴백. 오늘 날짜를 프롬프트에 넣어도(H19-11) 이 자리는 안 막혔다.
_MONTH_TOKEN = re.compile(r"^(?:(\d{4})\s*-\s*)?(\d{1,2})\s*(월)?$")
_MONTHS_IN_YEAR = 12


def fold_period_token(value: str, *, require_marker: bool = False) -> str | None:
    """월 표기 하나 → "YYYY-MM". 월로 읽히지 않으면 None(호출부가 원문을 그대로 흘린다).

    연도가 없으면 단지 시간대(KST) 기준 **올해**로 읽는다 — "7월 관리비"는 올해 7월이다.
    `require_marker=True`면 연도나 "월" 표식이 있어야 월로 본다: 대상 목록에서 쓰는 갈래로,
    동 번호("401")를 월로 훔치지 않기 위한 조건이다.
    """
    matched = _MONTH_TOKEN.match(value.strip())
    if matched is None:
        return None
    year, month, marker = matched.group(1), int(matched.group(2)), matched.group(3)
    if require_marker and not (year or marker):
        return None
    if not 1 <= month <= _MONTHS_IN_YEAR:
        return None
    return f"{int(year) if year else datetime.datetime.now(KST).year:04d}-{month:02d}"


def fold_periods(value: object) -> object:
    """`period` 필드(쉼표 나열) 정규화 — 전 토큰이 월로 읽힐 때만 접는다.

    하나라도 못 읽히면 원문을 그대로 돌려준다(패턴 검증이 지금처럼 거부하게 둔다 —
    반쯤 접힌 값으로 엉뚱한 달을 조회하는 것보다 검증 실패가 낫다).
    """
    if not isinstance(value, str) or not value.strip():
        return value
    folded = [fold_period_token(part) for part in value.split(",")]
    if any(period is None for period in folded):
        return value
    return ",".join(period for period in folded if period is not None)


def fold_scope(value: str) -> str | None:
    """사용자 표기 → 내부 범위 토큰. 미지정(None) · 본인 · 단지 전체 · "<동>동" 네 갈래."""
    raw = value.strip()
    if raw.lower() in _NULL_LITERALS:
        return None
    compact = raw.replace(" ", "")
    if compact in _SELF_SCOPE_WORDS:
        return SELF_SCOPE
    if compact in _COMPLEX_SCOPE_WORDS:
        return COMPLEX_SCOPE
    return f"{raw}동" if raw.isdigit() else raw


def dong_names(scope: str) -> list[str]:
    """ "402동" → ["402", "402동"] — buildings.name 표기 흔들림을 둘 다 받는다."""
    bare = scope.removesuffix("동").strip()
    return [bare, scope] if bare and bare != scope else [scope]


# ── 본인 세대 조회 ───────────────────────────────────────────────────────────

USER_SQL = text("SELECT household_id, approved_at FROM users WHERE id = :uid AND tenant_id = :tid")
FEE_SQL = text(
    "SELECT breakdown, total_amount FROM fees "
    "WHERE tenant_id = :tid AND household_id = :hid AND period = :period"
)
# 범위 평균의 "최근 확정 월" — 본인 세대가 아니라 단지 전체의 최신 월이다.
LATEST_PERIOD_SQL = text("SELECT max(period) AS period FROM fees WHERE tenant_id = :tid")


class SelfHousehold(NamedTuple):
    """요청자 본인 세대 — 세대 식별자와 조회 허용 시작 월("YYYY-MM")."""

    household_id: Any
    approved: str


async def self_household(deps: ToolDeps, ctx: ToolContext) -> SelfHousehold | None:
    """요청자의 세대. 미배정이면 None — 승인월이 없으면 사실상 전 기간 차단("9999-12")."""
    row = (await deps.session.execute(USER_SQL, {"uid": ctx.user_id, "tid": ctx.tenant_id})).first()
    if row is None or row.household_id is None:
        return None
    approved = row.approved_at.strftime("%Y-%m") if row.approved_at else "9999-12"
    return SelfHousehold(household_id=row.household_id, approved=approved)


async def latest_confirmed_period(deps: ToolDeps, ctx: ToolContext) -> str | None:
    """단지에서 확정된 가장 최근 월. 관리비 데이터가 아예 없으면 None."""
    row = (await deps.session.execute(LATEST_PERIOD_SQL, {"tid": ctx.tenant_id})).first()
    return str(row.period) if row is not None and row.period else None


# ── breakdown 파싱 ───────────────────────────────────────────────────────────


def breakdown_items(raw: object) -> list[tuple[str, int]]:
    """fees.breakdown(H8-7 리스트 `[{name,level,amount}]`) → (항목명, 금액) 목록.

    상위 항목(level 0)만, '합계'는 total과 중복이라 제외. 구 dict 포맷도 방어적으로 수용
    (과거 시드·외부 적재 데이터가 남아 있을 수 있다).
    """
    if isinstance(raw, dict):
        return [(str(k), int(v)) for k, v in raw.items()]
    items: list[tuple[str, int]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        if not name or name == "합계" or int(entry.get("level", 0)) != 0:
            continue
        items.append((name, int(entry.get("amount", 0))))
    return items


# 세부 항목 질의("전기요금 얼마야?")는 하위 항목이 LLM에 보여야 답할 수 있다(사용자 요구 3).
# level 3(급여 세부 등)은 입주민 질의 어휘에 없고 토큰만 먹어 제외, 0원 항목도 제외.
_FEE_DETAIL_LEVELS = (1, 2)
# 항목 비교가 훑는 레벨 상한 — "전기료"는 level 2("공과금중 전기료")에 있다.
DETAIL_ITEM_LEVEL = 2
# 범위 평균 카드가 나열하는 레벨 — 상위 항목만(표가 길어지면 못 읽는다).
TOP_ITEM_LEVEL = 0


def fee_detail_items(raw: object) -> list[tuple[str, int]]:
    """fees.breakdown → 하위 항목(level 1~2, 0원 제외) 목록 — quote(LLM 경로) 전용."""
    items: list[tuple[str, int]] = []
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", ""))
        amount = int(entry.get("amount", 0))
        if not name or name == "합계" or amount <= 0:
            continue
        if int(entry.get("level", 0)) not in _FEE_DETAIL_LEVELS:
            continue
        items.append((name, amount))
    return items


# ── 동·단지 집계(개별 세대 금액·식별자 미노출) ───────────────────────────────

# 본인 세대와 무관한 **집계 전용** 쿼리다. SELECT에 세대 식별자도 개별 금액도 없고,
# 표본수가 함께 나와 소표본이면 호출부가 평균을 거부한다.
# buildings.name은 접미사 없는 "402"(seed_households_xlsx 규칙)라 "402동" 표기도 함께 받는다.
DONG_JOIN = (
    " JOIN households h ON h.tenant_id = :tid AND h.id = f.household_id"
    " JOIN buildings b ON b.tenant_id = :tid AND b.id = h.building_id"
    " AND b.name = ANY(:dong)"
)
_SCOPE_WHERE = " WHERE f.tenant_id = :tid AND f.period = :period"


def _total_sql(join: str) -> TextClause:
    """총액 평균 + 표본수 — 동 조인 유무만 다르다."""
    return text(
        "SELECT round(avg(f.total_amount))::bigint AS avg_total, count(*) AS sample_size"
        " FROM fees f" + join + _SCOPE_WHERE
    )


def _items_sql(join: str, max_level: int) -> TextClause:
    """항목별 평균 — breakdown(JSONB 배열)을 SQL이 직접 펼쳐 avg를 낸다(H19-4와 같은 계열).

    파이썬도 LLM도 더하거나 나누지 않는다(규칙 5). 구 dict 포맷 행은 unnest가 깨지므로
    `jsonb_typeof = 'array'`로 걸러내고, '합계'는 총액과 중복이라 뺀다(breakdown_items 규칙).
    `max_level`은 코드가 정하는 상수다(사용자 입력이 SQL에 들어가지 않는다).
    """
    return text(
        "SELECT elem->>'name' AS name,"
        " round(avg((elem->>'amount')::numeric))::bigint AS avg_amount"
        " FROM fees f"
        + join
        + " CROSS JOIN LATERAL jsonb_array_elements(f.breakdown) AS elem"
        + _SCOPE_WHERE
        + " AND jsonb_typeof(f.breakdown) = 'array'"
        + f" AND (elem->>'level')::int <= {int(max_level)} AND elem->>'name' <> '합계'"
        + " GROUP BY 1 ORDER BY 1"
    )


SCOPE_DONG_TOTAL_SQL = _total_sql(DONG_JOIN)
SCOPE_COMPLEX_TOTAL_SQL = _total_sql("")
SCOPE_DONG_ITEMS_SQL = _items_sql(DONG_JOIN, TOP_ITEM_LEVEL)
SCOPE_COMPLEX_ITEMS_SQL = _items_sql("", TOP_ITEM_LEVEL)
# 비교 도구는 세부 항목(전기료 등)까지 훑는다 — 나가는 값은 여전히 평균과 표본수뿐이다.
COMPARE_DONG_ITEMS_SQL = _items_sql(DONG_JOIN, DETAIL_ITEM_LEVEL)
COMPARE_COMPLEX_ITEMS_SQL = _items_sql("", DETAIL_ITEM_LEVEL)


def scope_params(scope: str, period: str, tenant_id: Any) -> dict[str, Any]:
    """집계 쿼리 바인드 — 단지 전체는 동 목록이 없다."""
    params: dict[str, Any] = {"tid": tenant_id, "period": period}
    if scope != COMPLEX_SCOPE:
        params["dong"] = dong_names(scope)
    return params
