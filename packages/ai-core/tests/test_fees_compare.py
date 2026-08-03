"""compare_fees — 관리비 비교 도구(H20-1 후속).

검증 축은 넷이다: ①대상 표기 정규화·개수 경계 ②확정값 비교(차액은 뺄셈 한 번)
③값을 못 낸 대상을 숨기지 않는다(규칙 1) ④타 세대 개별 금액 미노출(CRITICAL).
H20-18로 다섯째 축이 붙었다: ⑤비교 축이 **월**인 갈래(두 달 증감).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from conftest import FakeSession, row
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool
from ai_core.tools.fees_common import COMPLEX_SCOPE, KST, MIN_PEER_SAMPLE, SELF_SCOPE
from ai_core.tools.fees_compare import MAX_TARGETS, CompareFeesArgs

TENANT = uuid.uuid4()
USER = uuid.uuid4()
HOUSEHOLD = uuid.uuid4()

CTX_RESIDENT = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

# 본인 세대 확정값 / 단지 평균 — 차액 +8,390원이 나오는 조합.
SELF_TOTAL = 176_601
COMPLEX_AVG = 168_211
COMPLEX_SAMPLE = 322

SELF_BREAKDOWN = [
    {"name": "공용관리비", "level": 0, "amount": 91_362},
    {"name": "일반관리비", "level": 1, "amount": 47_281},
    {"name": "공과금중 전기료", "level": 2, "amount": 12_345},
    {"name": "합계", "level": 0, "amount": SELF_TOTAL},
]


def _deps(settings: AiCoreSettings, handler: Any) -> ToolDeps:
    session = FakeSession(handler)
    llm = LlmClient(
        settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        retry_backoff_s=0.0,
    )
    return ToolDeps(
        session=cast(AsyncSession, session),
        llm=llm,
        retriever=cast(Retriever, object()),
        graph=None,
    )


def _handler(
    *,
    self_row: Any = "default",
    latest: str | None = "2026-07",
    aggregates: dict[str, tuple[object, int]] | None = None,
    items: dict[str, Sequence[tuple[str, int]]] | None = None,
    self_totals: dict[str, int] | None = None,
    period_aggregates: dict[str, tuple[object, int]] | None = None,
) -> Any:
    """대상별 응답을 흉내내는 가짜 세션.

    `aggregates`·`items`의 키는 동 이름(단지 전체는 `COMPLEX_SCOPE`)이다 — 집계 쿼리는
    params["dong"] 유무로 갈린다(실제 SQL과 같은 분기).
    `self_totals`·`period_aggregates`의 키는 **월**이다(기간 축 비교용 — 달마다 다른 값).
    """
    aggs = aggregates if aggregates is not None else {COMPLEX_SCOPE: (COMPLEX_AVG, COMPLEX_SAMPLE)}
    item_rows = items or {}

    def _key(params: dict[str, Any]) -> str:
        dong = params.get("dong")
        return str(dong[-1]) if dong else COMPLEX_SCOPE

    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        if "from users" in s:
            if self_row == "default":
                return [row(household_id=HOUSEHOLD, approved_at=datetime(2020, 1, 1, tzinfo=UTC))]
            return [self_row] if self_row is not None else []
        if "max(period)" in s:
            return [row(period=latest)] if latest else []
        if "count(*) as sample_size" in s:
            if period_aggregates is not None:
                avg_total, sample_size = period_aggregates.get(str(params["period"]), (None, 0))
            else:
                avg_total, sample_size = aggs.get(_key(params), (None, 0))
            return [row(avg_total=avg_total, sample_size=sample_size)]
        if "jsonb_array_elements" in s:
            return [
                row(name=name, avg_amount=amount)
                for name, amount in item_rows.get(_key(params), ())
            ]
        if "breakdown, total_amount" in s:
            if self_totals is not None:
                total = self_totals.get(str(params["period"]))
                if total is None:
                    return []
                return [row(breakdown=SELF_BREAKDOWN, total_amount=total)]
            return [row(breakdown=SELF_BREAKDOWN, total_amount=SELF_TOTAL)]
        return []

    return handler


def _call(args: dict[str, Any]) -> ToolCallRequest:
    return ToolCallRequest(id="c-compare", name="compare_fees", arguments=json.dumps(args))


async def _result(settings: AiCoreSettings, handler: Any, args: dict[str, Any]) -> Any:
    return (
        await execute_tool(
            _call(args),
            ctx=CTX_RESIDENT,
            deps=_deps(settings, handler),
            registry=default_registry(),
        )
    ).result


# ── 인자 정규화·경계 ────────────────────────────────────────────────────


def test_targets_fold_to_internal_tokens() -> None:
    """대상 표기는 scope와 같은 규칙으로 접힌다 — 본인 동의어·전체 동의어·숫자 동."""
    assert CompareFeesArgs(targets="우리집,전체").target_tokens() == [SELF_SCOPE, COMPLEX_SCOPE]
    assert CompareFeesArgs(targets="401, 402").target_tokens() == ["401동", "402동"]
    assert CompareFeesArgs(targets="나의 집, 단지 전체").target_tokens() == [
        SELF_SCOPE,
        COMPLEX_SCOPE,
    ]


def test_targets_reject_out_of_range_counts() -> None:
    """1개는 비교가 아니고(중복을 접어 1개가 되는 경우 포함), 상한 초과는 조용히 안 버린다."""
    for bad in ("전체", "우리집, 내집", ",".join(f"{40 + i}0동" for i in range(MAX_TARGETS + 1))):
        with pytest.raises(ValidationError):
            CompareFeesArgs(targets=bad)


def test_period_null_literal_and_multi_month_fold() -> None:
    assert CompareFeesArgs(targets="우리집,전체", period="null").period is None
    # 대상이 여럿이면 달을 나열해 와도 대상 축이다 — 가장 최근 달 하나로 비교한다.
    assert CompareFeesArgs(targets="우리집,전체", period="2026-06,2026-07").requested_period() == (
        "2026-07"
    )


# ── 월 토큰 관용(H20-18 — dev 실측 인자) ────────────────────────────────


def test_month_tokens_in_targets_move_to_period() -> None:
    """dev 3/3 실측 인자 `{"targets":"7월,8월","period":"7월,8월"}`가 기간 축이 된다.

    모델은 달을 **대상**에 넣고 연도를 뺀다. `fold_scope`가 "7월"을 동 이름으로 접으면
    데이터 없는 동 두 개를 비교하게 되고, period는 패턴 검증에서 죽는다(invalid_args).
    """
    year = datetime.now(KST).year
    args = CompareFeesArgs.model_validate({"targets": "7월,8월", "period": "7월,8월"})

    assert args.target_tokens() == []
    assert args.requested_periods() == [f"{year}-07", f"{year}-08"]
    assert args.is_period_axis


def test_month_tokens_in_targets_survive_null_literal_period() -> None:
    """모델은 `{"targets":"7월,8월","period":"null"}`도 보낸다 — 합칠 때 null을 먼저 접는다."""
    year = datetime.now(KST).year
    args = CompareFeesArgs.model_validate({"targets": "7월,8월", "period": "null"})
    assert args.requested_periods() == [f"{year}-07", f"{year}-08"]


def test_month_tokens_keep_dong_numbers_as_targets() -> None:
    """동 번호를 월로 훔치지 않는다 — 월 표식("월")이나 연도가 있어야 월이다."""
    args = CompareFeesArgs(targets="401,402")
    assert args.target_tokens() == ["401동", "402동"]
    assert args.requested_periods() == []


def test_year_less_months_in_period_field_get_this_year() -> None:
    """연도 없는 월도 받는다 — 없으면 패턴 검증 실패로 도구가 죽는다(dev 실측)."""
    year = datetime.now(KST).year
    assert CompareFeesArgs(targets="우리집,전체", period="7월").requested_periods() == [
        f"{year}-07"
    ]
    assert CompareFeesArgs(targets="우리집,전체", period="2026-7").requested_periods() == [
        "2026-07"
    ]
    with pytest.raises(ValidationError):
        CompareFeesArgs(targets="우리집,전체", period="열세달")


def test_targets_may_be_omitted_only_for_period_axis() -> None:
    """대상 축은 여전히 2~4개를 요구한다 — 달이 둘일 때만 대상 생략이 성립한다."""
    assert CompareFeesArgs.model_validate({"period": "2026-07,2026-08"}).target_tokens() == []
    with pytest.raises(ValidationError):
        CompareFeesArgs.model_validate({"period": "2026-07"})
    with pytest.raises(ValidationError):
        CompareFeesArgs.model_validate({})


# ── 기간 축 비교(월 간) ─────────────────────────────────────────────────


async def test_compare_two_months_of_own_household(settings: AiCoreSettings) -> None:
    """ "관리비 7월 8월 비교해줘" — 본인 세대 두 달 확정값과 증감이 한 카드에."""
    handler = _handler(self_totals={"2026-07": 176_601, "2026-08": 181_000})
    result = await _result(settings, handler, {"targets": "7월,8월", "period": "2026-07,2026-08"})

    assert result.card is not None
    assert result.card.title == "2026-07 vs 2026-08 관리비 비교"
    assert "우리집" in result.card.quote
    assert "2026-07 176,601원" in result.card.quote
    assert "2026-08 181,000원" in result.card.quote
    # 증감은 나중 달 기준(+ = 늘었다). 뺄셈 한 번 + 퍼센트 한 번만 코드가 한다.
    assert "증감 +4,399원(+2.5%)" in result.card.quote
    assert result.card.data == {
        "kind": "fee_compare",
        "period": "2026-07 vs 2026-08",
        "rows": [
            {
                "label": "2026-07",
                "kind": "self",
                "amount": 176_601,
                "sample_size": None,
                "note": "",
            },
            {
                "label": "2026-08",
                "kind": "self",
                "amount": 181_000,
                "sample_size": None,
                "note": "",
            },
        ],
        "base_label": "2026-08",
        "diffs": [{"label": "2026-07", "diff": 4_399}],
        "axis": "period",
        "subject": "우리집",
        "change_pct": 2.5,
    }


async def test_compare_two_months_uses_latest_two_and_says_what_it_dropped(
    settings: AiCoreSettings,
) -> None:
    """셋 이상이면 최근 두 달만 비교하고 **버린 달을 적는다**(H19-4 교훈 — 조용히 빼지 않는다)."""
    handler = _handler(self_totals={"2026-06": 170_000, "2026-07": 176_601, "2026-08": 181_000})
    result = await _result(settings, handler, {"period": "2026-06,2026-07,2026-08"})

    assert result.card is not None
    assert result.card.title == "2026-07 vs 2026-08 관리비 비교"
    assert "2026-06" in result.card.quote  # 제외 사실이 근거에 남는다
    assert "170,000" not in result.card.quote


async def test_compare_two_months_blocks_month_before_approval(settings: AiCoreSettings) -> None:
    """FR-FEE-03은 달마다 적용된다 — 승인 이전 달은 값이 안 나가고 사유만 남는다."""
    handler = _handler(
        self_row=row(household_id=HOUSEHOLD, approved_at=datetime(2026, 8, 1, tzinfo=UTC)),
        self_totals={"2026-07": 176_601, "2026-08": 181_000},
    )
    result = await _result(settings, handler, {"period": "2026-07,2026-08"})

    assert result.card is not None
    assert "2026-07 입주 승인 이전이라 확인 불가" in result.card.quote
    assert "176,601" not in result.card.quote
    assert "2026-08 181,000원" in result.card.quote
    assert result.card.data is not None and result.card.data["diffs"] == []
    assert "증감" not in result.card.quote


async def test_compare_two_months_falls_back_to_complex_average_without_household(
    settings: AiCoreSettings,
) -> None:
    """세대가 없는 관리자 채널은 본인이 될 수 없다 — 단지 평균 두 달을 비교한다."""
    handler = _handler(
        self_row=None,
        period_aggregates={"2026-07": (168_211, COMPLEX_SAMPLE), "2026-08": (171_000, 320)},
    )
    result = await _result(settings, handler, {"period": "2026-07,2026-08"})

    assert result.card is not None
    assert "단지 전체" in result.card.quote
    assert "2026-07 평균 168,211원(표본 322세대)" in result.card.quote
    assert "증감 +2,789원(+1.7%)" in result.card.quote
    assert result.card.data is not None and result.card.data["subject"] == "단지 전체"


async def test_compare_two_months_of_one_named_target(settings: AiCoreSettings) -> None:
    """대상을 하나 지정하면 그 대상의 두 달 — 대상이 여럿이면 첫 대상만 쓴다."""
    handler = _handler(
        period_aggregates={"2026-07": (150_000, 60), "2026-08": (147_000, 60)},
    )
    result = await _result(settings, handler, {"targets": "401동", "period": "7월,8월"})

    assert result.card is not None
    assert "401동" in result.card.quote
    assert "증감 -3,000원(-2.0%)" in result.card.quote


async def test_compare_two_months_without_any_data_returns_note(settings: AiCoreSettings) -> None:
    handler = _handler(self_totals={})
    result = await _result(settings, handler, {"period": "2026-07,2026-08"})

    assert result.card is None
    assert "비교할 수 있는" in result.note and "관리비 내역 없음" in result.note


# ── 총액 비교 ───────────────────────────────────────────────────────────


async def test_compare_self_and_complex_puts_both_in_one_card(settings: AiCoreSettings) -> None:
    """ "우리집과 아파트 평균 비교" — 도구 한 번으로 양쪽 확정값과 차액이 한 카드에."""
    result = await _result(settings, _handler(), {"targets": "우리집,전체", "period": "2026-07"})

    assert result.card is not None
    assert result.card.source_kind == "tool:compare_fees"
    assert "우리집 176,601원" in result.card.quote
    assert "단지 전체 평균 168,211원(표본 322세대)" in result.card.quote
    assert "차이 +8,390원" in result.card.quote
    assert result.card.data == {
        "kind": "fee_compare",
        "period": "2026-07",
        "rows": [
            {"label": "우리집", "kind": "self", "amount": 176_601, "sample_size": None, "note": ""},
            {
                "label": "단지 전체",
                "kind": "complex",
                "amount": 168_211,
                "sample_size": 322,
                "note": "",
            },
        ],
        "base_label": "우리집",
        "diffs": [{"label": "단지 전체", "diff": 8_390}],
    }


async def test_compare_two_dongs_uses_latest_period_when_omitted(settings: AiCoreSettings) -> None:
    handler = _handler(aggregates={"401동": (150_000, 60), "402동": (141_034, 62)})
    result = await _result(settings, handler, {"targets": "401동,402동"})

    assert result.card is not None
    assert result.card.title == "2026-07 관리비 비교"  # 최근 확정 월
    assert "401동 평균 150,000원(표본 60세대)" in result.card.quote
    assert "차이 +8,966원" in result.card.quote  # 첫 대상 기준
    assert result.card.data is not None and result.card.data["base_label"] == "401동"


# ── 항목 비교 ───────────────────────────────────────────────────────────


async def test_compare_item_matches_partial_name(settings: AiCoreSettings) -> None:
    """ "전기료"는 세부 항목("공과금중 전기료")에 부분 일치로 걸린다 — 총액이 아니라 항목 비교."""
    handler = _handler(items={COMPLEX_SCOPE: [("공과금중 전기료", 11_000), ("청소비", 20_000)]})
    result = await _result(
        settings, handler, {"targets": "우리집,전체", "period": "2026-07", "item": "전기료"}
    )

    assert result.card is not None
    assert "(공과금중 전기료)" in result.card.quote
    assert "우리집 12,345원" in result.card.quote
    assert "단지 전체 평균 11,000원" in result.card.quote
    assert "차이 +1,345원" in result.card.quote
    assert result.card.data is not None and result.card.data["item"] == "공과금중 전기료"


async def test_compare_item_ambiguous_returns_candidates_note(settings: AiCoreSettings) -> None:
    """후보가 여럿이면 아무거나 집지 않는다 — 틀린 숫자를 확정값처럼 내놓는 게 최악이다."""
    handler = _handler(
        aggregates={"401동": (150_000, 60), "402동": (141_034, 62)},
        items={
            "401동": [("공과금중 전기료", 11_000), ("전기승강기유지비", 3_000)],
            "402동": [("공과금중 전기료", 10_000), ("전기승강기유지비", 2_800)],
        },
    )
    result = await _result(settings, handler, {"targets": "401동,402동", "item": "전기"})

    assert result.card is None
    assert "여러 개" in result.note
    assert "공과금중 전기료" in result.note and "전기승강기유지비" in result.note


# ── 값을 못 낸 대상 ─────────────────────────────────────────────────────


async def test_compare_excludes_small_sample_target_but_says_why(settings: AiCoreSettings) -> None:
    """표본 하한 미달 대상은 비교에서 빠지고 사유가 남는다(소표본 역산 방지)."""
    handler = _handler(
        aggregates={
            COMPLEX_SCOPE: (COMPLEX_AVG, COMPLEX_SAMPLE),
            "402동": (141_034, MIN_PEER_SAMPLE - 1),
        }
    )
    result = await _result(settings, handler, {"targets": "우리집,전체,402동"})

    assert result.card is not None
    assert "402동 표본 9세대로 적어 비교 제외" in result.card.quote
    assert "141,034" not in result.card.quote  # 소표본 평균은 어디에도 안 나간다
    assert result.card.data is not None
    assert [d["label"] for d in result.card.data["diffs"]] == ["단지 전체"]


async def test_compare_unknown_dong_says_no_data(settings: AiCoreSettings) -> None:
    """없는 동은 추측하지 않는다(규칙 1) — 다른 대상 값은 그대로 낸다."""
    result = await _result(settings, _handler(), {"targets": "우리집,999동"})

    assert result.card is not None
    assert "999동 관리비 데이터 없음" in result.card.quote
    assert "우리집 176,601원" in result.card.quote
    assert result.card.data is not None and result.card.data["diffs"] == []


async def test_compare_all_targets_unavailable_returns_note(settings: AiCoreSettings) -> None:
    handler = _handler(self_row=None, aggregates={})
    result = await _result(settings, handler, {"targets": "우리집,전체"})

    assert result.card is None
    assert "비교할 수 있는 대상이 없습니다" in result.note
    assert "세대 미배정" in result.note


async def test_compare_without_fee_data_at_all_returns_note(settings: AiCoreSettings) -> None:
    result = await _result(settings, _handler(latest=None), {"targets": "우리집,전체"})
    assert result.card is None and "조회 가능한 관리비 내역이 없습니다" in result.note


# ── 격리·미노출 ─────────────────────────────────────────────────────────


async def test_compare_sql_is_tenant_scoped_and_hides_other_households(
    settings: AiCoreSettings,
) -> None:
    """집계 SELECT에 세대 식별자·개별 금액이 없고, 모든 쿼리가 같은 단지로 제한된다."""
    deps = _deps(settings, _handler())
    await execute_tool(
        _call({"targets": "우리집,전체", "period": "2026-07"}),
        ctx=CTX_RESIDENT,
        deps=deps,
        registry=default_registry(),
    )
    session = cast(FakeSession, deps.session)
    assert session.executed
    for sql, params in session.executed:
        assert params["tid"] == TENANT
        if "avg(" not in sql:
            continue
        select_clause = sql.split("SELECT")[1].split("FROM")[0]
        assert "household_id" not in select_clause
        assert "f.total_amount" not in select_clause.replace("avg(f.total_amount)", "")


def test_compare_fees_is_visible_to_residents() -> None:
    specs = default_registry().specs_for(("RESIDENT",), graph_available=False)
    names = [s["function"]["name"] for s in specs]
    assert "compare_fees" in names
