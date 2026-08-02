"""compare_fees — 관리비 비교 도구(H20-1 후속).

검증 축은 넷이다: ①대상 표기 정규화·개수 경계 ②확정값 비교(차액은 뺄셈 한 번)
③값을 못 낸 대상을 숨기지 않는다(규칙 1) ④타 세대 개별 금액 미노출(CRITICAL).
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
from ai_core.tools.fees_common import COMPLEX_SCOPE, MIN_PEER_SAMPLE, SELF_SCOPE
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
) -> Any:
    """대상별 응답을 흉내내는 가짜 세션.

    `aggregates`·`items`의 키는 동 이름(단지 전체는 `COMPLEX_SCOPE`)이다 — 집계 쿼리는
    params["dong"] 유무로 갈린다(실제 SQL과 같은 분기).
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
            avg_total, sample_size = aggs.get(_key(params), (None, 0))
            return [row(avg_total=avg_total, sample_size=sample_size)]
        if "jsonb_array_elements" in s:
            return [
                row(name=name, avg_amount=amount)
                for name, amount in item_rows.get(_key(params), ())
            ]
        if "breakdown, total_amount" in s:
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
    # 여러 달을 나열해 오면 가장 최근 달 하나로 비교한다(비교 축은 대상이지 월이 아니다).
    assert CompareFeesArgs(targets="우리집,전체", period="2026-06,2026-07").requested_period() == (
        "2026-07"
    )


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
