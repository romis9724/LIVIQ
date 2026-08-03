"""관리비 비교 도구 `compare_fees` (H20-1 후속) — 대상 2~4개를 한 카드에 나란히 놓는다.

비교 축은 둘이다(H20-18): **대상**(한 달·여러 대상) 또는 **기간**(대상 하나·두 달).
서로 다른 달이 둘 이상 들어오면 기간 축으로 전환한다 — "관리비 7월 8월 비교해줘"가
폴백났던 자리다(dev 실측: 달이 `targets`로 들어오고 연도가 빠져 검증에서 죽었다).

왜 별도 도구인가: "우리집 관리비와 아파트 관리비를 비교해주세요"가 dev에서 폴백났다.
비교는 도구 호출 **두 번**(본인 + 범위 평균)을 요구하는데 8B는 한 turn에 한 갈래만 고르고,
설명이 겹치는 도구 둘을 번갈아 부르지 못한다(R22 계열). 비교 어휘를 받는 앵커를 하나 두고
그 안에서 대상별 조회를 코드가 도는 편이 라우팅에 싸다.

숫자는 전부 확정값이다(규칙 5): 세대 값은 fees 행 그대로, 범위 값은 SQL 평균 그대로이고
파이썬이 하는 계산은 **확정값끼리의 뺄셈 한 번**뿐이다(H19-4 peer 비교와 같은 허용 범위).
집계 대상은 표본 하한(`MIN_PEER_SAMPLE`) 미만이면 비교에서 빠진다 — 소표본 평균은 본인
값과 함께 특정 세대 금액을 역산시킨다(ADR-0026 결정 3). 타 세대 개별 금액·식별자는 어떤
경로로도 나가지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple, cast

from pydantic import BaseModel, Field, field_validator, model_validator

from ai_core.tools.fees_common import (
    COMPARE_COMPLEX_ITEMS_SQL,
    COMPARE_DONG_ITEMS_SQL,
    COMPLEX_SCOPE,
    FEE_SQL,
    MIN_PEER_SAMPLE,
    PERIOD_PATTERN,
    SCOPE_COMPLEX_TOTAL_SQL,
    SCOPE_DONG_TOTAL_SQL,
    SELF_SCOPE,
    breakdown_items,
    fee_detail_items,
    fold_null_literal,
    fold_period_token,
    fold_periods,
    fold_scope,
    latest_confirmed_period,
    scope_params,
    self_household,
)
from ai_core.tools.registry import Tool, ToolCard, ToolContext, ToolDeps, ToolResult

# 대상 개수 경계 — 1개는 비교가 아니고(그건 get_fees), 5개부터는 quote가 길어져 8B가
# 표를 재작성하기 시작한다. 초과분을 조용히 버리지 않고 검증 오류로 돌려준다(경계 검증).
MIN_TARGETS = 2
MAX_TARGETS = 4
# 기간 축 전환 조건 — 서로 다른 달이 둘이면 비교는 달끼리다.
MIN_PERIODS = 2

_SELF_LABEL = "우리집"
_COMPLEX_LABEL = "단지 전체"


class CompareFeesArgs(BaseModel):
    targets: str | None = Field(
        default=None,
        description=(
            "비교할 대상들을 쉼표로 나열한다. 예: '우리집,전체' '401동,402동' '402동,단지 전체'. "
            "달끼리 비교할 때는 대상을 하나만 적거나 생략한다"
        ),
    )
    period: str | None = Field(
        default=None,
        pattern=PERIOD_PATTERN,
        description=(
            "비교할 월(YYYY-MM). 여러 달을 쉼표로 주면 그 달끼리 비교한다"
            "(예: 2026-07,2026-08). 생략 시 최근 확정 월"
        ),
    )
    item: str | None = Field(
        default=None,
        description="비교할 세부 항목명(예: 전기료, 청소비, 난방비). 생략 시 총액을 비교한다",
    )

    @model_validator(mode="before")
    @classmethod
    def _move_months_out_of_targets(cls, data: object) -> object:
        """`targets`에 실려온 달을 `period`로 옮긴다(H20-18 — dev 실측 3/3).

        모델은 "관리비 7월 8월 비교해줘"에 `{"targets":"7월,8월","period":"7월,8월"}`를 넘긴다.
        달을 대상으로 두면 `fold_scope`가 "7월"을 동 이름으로 접어 데이터 없는 동 두 개를
        비교하게 된다 — 사용자에겐 그냥 폴백이다. 표식(연도·"월") 있는 토큰만 달로 본다.
        """
        if not isinstance(data, dict):
            return data
        raw_targets = data.get("targets")
        if not isinstance(raw_targets, str):
            return data
        parts = [part for part in (p.strip() for p in raw_targets.split(",")) if part]
        months = [m for m in (fold_period_token(p, require_marker=True) for p in parts) if m]
        if not months:
            return data
        kept = [p for p in parts if fold_period_token(p, require_marker=True) is None]
        # period 쪽 리터럴 "null"을 먼저 접는다 — 안 접으면 합친 문자열이 패턴 검증에서 죽는다
        # (모델은 `{"targets":"7월,8월","period":"null"}`도 보낸다).
        merged = [*months, *(str(fold_null_literal(data.get("period")) or "").split(","))]
        return {
            **data,
            "targets": ",".join(kept) or None,
            # period 쪽 원문도 같은 달일 수 있다 — 중복은 requested_periods가 접는다.
            "period": ",".join(p for p in (m.strip() for m in merged) if p),
        }

    @field_validator("period", "item", mode="before")
    @classmethod
    def _fold_null_literal(cls, value: object) -> object:
        return fold_periods(fold_null_literal(value))

    @field_validator("targets", mode="before")
    @classmethod
    def _normalize_targets(cls, value: object) -> object:
        """대상 표기를 scope와 **같은 규칙**으로 접는다(중복은 접는다 — "우리집, 내집").

        개수 경계는 축이 정해진 뒤에 본다(`_require_targets_for_target_axis`).
        """
        if not isinstance(value, str):
            return value
        folded = [t for t in (fold_scope(part) for part in value.split(",")) if t]
        return ",".join(dict.fromkeys(folded)) or None

    @model_validator(mode="after")
    def _require_targets_for_target_axis(self) -> CompareFeesArgs:
        """대상 축은 서로 다른 2~4개를 요구한다 — 1개는 비교가 아니고(그건 get_fees),
        5개부터는 quote가 길어져 8B가 표를 재작성한다. 초과분을 조용히 버리지 않는다.

        기간 축(달이 둘 이상)은 대상이 0~1개다 — 그 갈래에서만 개수 조건이 풀린다.
        """
        if self.is_period_axis:
            return self
        if not MIN_TARGETS <= len(self.target_tokens()) <= MAX_TARGETS:
            raise ValueError(f"비교 대상은 서로 다른 {MIN_TARGETS}~{MAX_TARGETS}개여야 합니다")
        return self

    @property
    def is_period_axis(self) -> bool:
        """비교 축이 월인가 — 서로 다른 달이 둘 이상이면 그렇다."""
        return len(self.requested_periods()) >= MIN_PERIODS

    def target_tokens(self) -> list[str]:
        """정규화된 내부 토큰 목록(`__self__` · `__complex__` · "<동>동")."""
        return self.targets.split(",") if self.targets else []

    def requested_periods(self) -> list[str]:
        """요청 월 목록(중복 제거·오름차순) — get_fees와 같은 규칙."""
        if not self.period:
            return []
        return sorted({p.strip() for p in self.period.split(",")})

    def requested_period(self) -> str | None:
        """대상 축의 비교 월. 여러 달이면 가장 최근 달 하나(그 축의 비교 대상은 달이 아니다)."""
        periods = self.requested_periods()
        return periods[-1] if periods else None


class CompareRow(NamedTuple):
    """비교 대상 한 줄. 값을 못 낸 대상은 amount=None이고 사유를 note에 적는다(규칙 1)."""

    label: str
    kind: str  # self | dong | complex
    amount: int | None
    sample_size: int | None  # 집계 대상만(본인 세대는 None)
    note: str


class _Resolved(NamedTuple):
    """대상 1건 해석 결과 + 항목 매칭 부산물."""

    row: CompareRow
    item_name: str = ""
    # 항목명이 여러 후보에 걸리면 비교를 멈추고 되물을 재료로 쓴다.
    candidates: tuple[str, ...] = ()


def _label_of(token: str) -> str:
    if token == SELF_SCOPE:
        return _SELF_LABEL
    if token == COMPLEX_SCOPE:
        return _COMPLEX_LABEL
    return token


def _unavailable(label: str, kind: str, note: str) -> CompareRow:
    return CompareRow(label=label, kind=kind, amount=None, sample_size=None, note=note)


def _pick_item(
    query: str, items: Sequence[tuple[str, int]]
) -> tuple[tuple[str, int] | None, tuple[str, ...]]:
    """항목명 매칭 — 정확 일치 우선, 없으면 부분 일치.

    부분 일치가 여럿이면 고르지 않는다((None, 후보들)) — "전기"가 "공과금중 전기료"와
    "전기승강기유지비"에 함께 걸릴 때 아무거나 집으면 틀린 숫자를 확정값처럼 내놓게 된다.
    """
    compact = query.replace(" ", "")
    exact = [(name, amount) for name, amount in items if name.replace(" ", "") == compact]
    if exact:
        return exact[0], ()
    partial = [(name, amount) for name, amount in items if compact in name.replace(" ", "")]
    if len(partial) == 1:
        return partial[0], ()
    return None, tuple(name for name, _ in partial)


async def _self_target(
    deps: ToolDeps, ctx: ToolContext, period: str, item: str | None
) -> _Resolved:
    """본인 세대 값 — 소유권·승인월은 get_fees와 같은 규칙으로 검사한다."""
    me = await self_household(deps, ctx)
    if me is None:
        return _Resolved(_unavailable(_SELF_LABEL, "self", "세대 미배정으로 확인 불가"))
    if period < me.approved:
        return _Resolved(_unavailable(_SELF_LABEL, "self", "입주 승인 이전이라 확인 불가"))
    fee = (
        await deps.session.execute(
            FEE_SQL, {"tid": ctx.tenant_id, "hid": me.household_id, "period": period}
        )
    ).first()
    if fee is None or fee.total_amount is None:
        return _Resolved(_unavailable(_SELF_LABEL, "self", "관리비 내역 없음"))
    if item is None:
        return _Resolved(
            CompareRow(_SELF_LABEL, "self", int(fee.total_amount), None, ""),
        )
    picked, candidates = _pick_item(
        item, [*breakdown_items(fee.breakdown), *fee_detail_items(fee.breakdown)]
    )
    if picked is None:
        return _Resolved(
            _unavailable(_SELF_LABEL, "self", f"'{item}' 항목 없음"), candidates=candidates
        )
    return _Resolved(CompareRow(_SELF_LABEL, "self", picked[1], None, ""), item_name=picked[0])


async def _scope_target(
    deps: ToolDeps, ctx: ToolContext, token: str, period: str, item: str | None
) -> _Resolved:
    """동·단지 집계 값 — 나가는 것은 평균과 표본수뿐이다(개별 세대 금액 미노출)."""
    is_complex = token == COMPLEX_SCOPE
    label = _label_of(token)
    kind = "complex" if is_complex else "dong"
    params = scope_params(token, period, ctx.tenant_id)
    total_sql = SCOPE_COMPLEX_TOTAL_SQL if is_complex else SCOPE_DONG_TOTAL_SQL

    row = (await deps.session.execute(total_sql, params)).first()
    sample_size = int(row.sample_size) if row is not None and row.sample_size is not None else 0
    if row is None or row.avg_total is None or sample_size == 0:
        return _Resolved(_unavailable(label, kind, "관리비 데이터 없음"))
    if sample_size < MIN_PEER_SAMPLE:
        return _Resolved(_unavailable(label, kind, f"표본 {sample_size}세대로 적어 비교 제외"))
    if item is None:
        return _Resolved(CompareRow(label, kind, int(row.avg_total), sample_size, ""))

    items_sql = COMPARE_COMPLEX_ITEMS_SQL if is_complex else COMPARE_DONG_ITEMS_SQL
    rows = (await deps.session.execute(items_sql, params)).all()
    picked, candidates = _pick_item(
        item, [(str(r.name), int(r.avg_amount)) for r in rows if r.avg_amount is not None]
    )
    if picked is None:
        return _Resolved(_unavailable(label, kind, f"'{item}' 항목 없음"), candidates=candidates)
    return _Resolved(CompareRow(label, kind, picked[1], sample_size, ""), item_name=picked[0])


async def _resolve_target(
    deps: ToolDeps, ctx: ToolContext, token: str, period: str, item: str | None
) -> _Resolved:
    """대상 1건 해석 — 본인 세대와 집계 범위의 분기 한 곳(두 축이 공유한다)."""
    if token == SELF_SCOPE:
        return await _self_target(deps, ctx, period, item)
    return await _scope_target(deps, ctx, token, period, item)


def _ambiguous_note(item: str | None, resolved: Sequence[_Resolved]) -> str:
    """항목명이 여러 후보에 걸렸으면 되물을 문구, 아니면 빈 문자열."""
    candidates = next((r.candidates for r in resolved if r.candidates), ())
    if not candidates:
        return ""
    return (
        f"'{item}'에 해당하는 항목이 여러 개입니다: {', '.join(candidates)}. "
        "하나를 정확히 지정해 주세요."
    )


async def _compare_fees(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(CompareFeesArgs, args)
    if a.is_period_axis:
        return await _compare_periods(deps, ctx, a)

    period = a.requested_period() or await latest_confirmed_period(deps, ctx)
    if period is None:
        return ToolResult(note="조회 가능한 관리비 내역이 없습니다.")

    resolved = [
        await _resolve_target(deps, ctx, token, period, a.item) for token in a.target_tokens()
    ]
    ambiguous = _ambiguous_note(a.item, resolved)
    if ambiguous:
        return ToolResult(note=ambiguous)

    rows = [r.row for r in resolved]
    item_label = next((r.item_name for r in resolved if r.item_name), "")
    comparable = [r for r in rows if r.amount is not None]
    if not comparable:
        return ToolResult(
            note=f"{period} 관리비를 비교할 수 있는 대상이 없습니다({_reasons(rows)})."
        )

    base = comparable[0]
    diffs = [(r.label, cast(int, base.amount) - cast(int, r.amount)) for r in comparable[1:]]
    return ToolResult(
        card=ToolCard(
            title=f"{period} 관리비 비교",
            quote=_compare_quote(period, item_label, rows, base.label, diffs),
            source_kind="tool:compare_fees",
            data=_compare_data(period, item_label, rows, base.label, diffs),
        )
    )


async def _period_subject(deps: ToolDeps, ctx: ToolContext, a: CompareFeesArgs) -> str:
    """기간 축의 대상 하나 — 지정 대상 첫 개, 없으면 본인 세대(세대가 없으면 단지 평균).

    세대 배정이 없는 채널(관리자)에서 본인은 성립하지 않는다. 역할로 갈라지 않고 세대
    유무로 판정하는 이유는 이것이 도구가 실제로 필요한 조건이기 때문이다(규칙 4는
    소유권 검사이고, 여기서 세대 조회는 `self_household`가 이미 tenant·본인으로 묶는다).
    """
    targets = a.target_tokens()
    if targets:
        return targets[0]
    return SELF_SCOPE if await self_household(deps, ctx) is not None else COMPLEX_SCOPE


async def _compare_periods(deps: ToolDeps, ctx: ToolContext, a: CompareFeesArgs) -> ToolResult:
    """비교 축이 **월**인 갈래 — 대상 하나의 두 달을 나란히 놓고 증감을 낸다.

    셋 이상을 물으면 최근 두 달만 비교하고 **버린 달을 근거에 적는다**(H19-4 교훈 —
    빠진 달을 조용히 넘기면 "6,7월"을 물은 사용자에게 거짓말이 된다).
    """
    periods = a.requested_periods()
    window, dropped = periods[-MIN_PERIODS:], periods[:-MIN_PERIODS]
    token = await _period_subject(deps, ctx, a)
    subject = _label_of(token)

    resolved = [await _resolve_target(deps, ctx, token, period, a.item) for period in window]
    ambiguous = _ambiguous_note(a.item, resolved)
    if ambiguous:
        return ToolResult(note=ambiguous)

    # 행 라벨을 월로 바꿔 화면 표의 "대상" 열이 곧 월이 된다(프론트 무변경).
    rows = [r.row._replace(label=period) for r, period in zip(resolved, window, strict=True)]
    item_label = next((r.item_name for r in resolved if r.item_name), "")
    comparable = [r for r in rows if r.amount is not None]
    if not comparable:
        return ToolResult(
            note=(
                f"{subject} {' · '.join(window)} 관리비를 비교할 수 있는 자료가 "
                f"없습니다({_reasons(rows)})."
            )
        )

    # 기준은 **나중 달**이다 — diff 부호가 그대로 증감이 되고, 화면 문장도 증감으로 읽힌다.
    base = comparable[-1]
    earlier = comparable[:-1]
    diffs = [(r.label, cast(int, base.amount) - cast(int, r.amount)) for r in earlier]
    pct = _change_pct(earlier[0].amount, base.amount) if earlier else None
    period_label = " vs ".join(window)
    data = {
        **_compare_data(period_label, item_label, rows, base.label, diffs),
        "axis": "period",
        "subject": subject,
        "change_pct": pct,
    }
    return ToolResult(
        card=ToolCard(
            title=f"{period_label} 관리비 비교",
            quote=_period_quote(subject, item_label, rows, diffs, pct, dropped),
            source_kind="tool:compare_fees",
            data=data,
        )
    )


def _change_pct(before: int | None, after: int | None) -> float | None:
    """증감률 — 확정값 둘의 나눗셈 한 번(규칙 5: 계산은 코드가, AI는 근거를 읽을 뿐)."""
    if not before or after is None:
        return None
    return round((after - before) / before * 100, 1)


def _signed(amount: int) -> str:
    return f"{'+' if amount >= 0 else ''}{amount:,}원"


def _period_quote(
    subject: str,
    item_label: str,
    rows: Sequence[CompareRow],
    diffs: Sequence[tuple[str, int]],
    pct: float | None,
    dropped: Sequence[str],
) -> str:
    """LLM이 보는 유일한 텍스트 — 달별 확정값과 증감뿐이다."""
    head = f"{subject} " + " vs ".join(r.label for r in rows) + " 관리비 비교"
    quote = f"{head}{f'({item_label})' if item_label else ''} — " + " · ".join(
        _amount_text(row) for row in rows
    )
    if diffs:
        rate = f"({'+' if pct is not None and pct >= 0 else ''}{pct}%)" if pct is not None else ""
        quote += f" · 증감 {_signed(diffs[0][1])}{rate}"
    if dropped:
        quote += f" · 함께 물은 {', '.join(dropped)}은 이번 비교에서 제외(최근 두 달만 비교)"
    return quote


def _reasons(rows: Sequence[CompareRow]) -> str:
    return ", ".join(f"{r.label} {r.note}" for r in rows if r.note)


def _amount_text(row: CompareRow) -> str:
    """대상 한 줄의 표기 — 집계 대상은 평균임과 표본수를 문구에 못박는다."""
    if row.amount is None:
        return f"{row.label} {row.note}"
    if row.sample_size is None:
        return f"{row.label} {row.amount:,}원"
    return f"{row.label} 평균 {row.amount:,}원(표본 {row.sample_size}세대)"


def _compare_quote(
    period: str,
    item_label: str,
    rows: Sequence[CompareRow],
    base_label: str,
    diffs: Sequence[tuple[str, int]],
) -> str:
    """LLM이 보는 유일한 텍스트 — 대상별 확정값과 차액뿐이다."""
    head = f"{period} 관리비 비교" + (f"({item_label})" if item_label else "")
    body = " · ".join(_amount_text(row) for row in rows)
    quote = f"{head} — {body}"
    if len(diffs) == 1:
        quote += f" · 차이 {_signed(diffs[0][1])}"
    elif diffs:
        listed = ", ".join(f"{label} {_signed(diff)}" for label, diff in diffs)
        quote += f" · {base_label} 기준 차이: {listed}"
    return quote


def _compare_data(
    period: str,
    item_label: str,
    rows: Sequence[CompareRow],
    base_label: str,
    diffs: Sequence[tuple[str, int]],
) -> dict[str, Any]:
    """화면용 비교 표(ADR-0025 §6) — LLM은 보지 않는다. 값은 quote와 같은 확정값."""
    data: dict[str, Any] = {
        "kind": "fee_compare",
        "period": period,
        "rows": [
            {
                "label": r.label,
                "kind": r.kind,
                "amount": r.amount,
                "sample_size": r.sample_size,
                "note": r.note,
            }
            for r in rows
        ],
        "base_label": base_label,
        "diffs": [{"label": label, "diff": diff} for label, diff in diffs],
    }
    if item_label:
        data["item"] = item_label
    return data


compare_fees_tool = Tool(
    name="compare_fees",
    # 비교 어휘 전용 앵커 — get_fees 설명과 어휘가 겹치면 8B가 둘을 섞는다(R22 교훈).
    description=(
        "관리비를 서로 비교할 때만 쓴다 — 우리집과 단지 평균, 동과 동, 동과 전체, "
        "특정 항목(전기료 등)의 비교. 단일 대상 조회에는 쓰지 않는다(그건 관리비 조회 도구)."
    ),
    args_model=CompareFeesArgs,
    run=_compare_fees,
)
