"""민원 도구 2종 — 입주민 유사 사례(H17-1, ADR-0024) · 관리자 현황 요약(H19-3, ADR-0026).

`search_similar_inquiries`: `pg_trgm.word_similarity`로 제목+본문을 랭킹한다(임계는 아래
상수·상한 5건). 읽기 전용 SELECT뿐이고 **AI는 민원을 생성하지 않는다** — 접수는 사용자가
폼에서 한다(규칙 8, 딥링크 CTA).
노출은 제목·카테고리 라벨·담당자 답변 발췌(120자)로 제한한다. 작성자·동호수·본문은 컬럼
자체를 읽지 않는다 — 안 읽으면 마스킹 실패 경로도 없다(규칙 2). 남의 민원은 `status='done'`
(답이 확정된 건)만, 본인 민원은 진행중도 포함해 중복 접수를 막는다.

`summarize_inquiries`: 관리사무소(MANAGER·STAFF)용 기간·동별 집계. 집계는 SQL GROUP BY가
확정하고(화면·답변 숫자는 도구 확정값 — 규칙 8), 목록은 제목·분류·상태·경과일까지만
내보낸다. 본문·작성자·동호수는 여기서도 SELECT하지 않는다(같은 규칙 2 선례).

tenant_id·user_id는 ToolContext에서 오며 LLM 인자로 받지 않는다(규칙 3·4).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import text

# 관리사무소(소장·직원) — 민원 응대의 주체다. 설비 도구의 FACILITY_ROLES(FACILITY·MANAGER)와
# 다른 집합인 이유는 ADR-0026 결정 2: 민원 현황은 시설 담당이 아니라 사무소 업무이고,
# STAFF는 실제 users.role에 존재하는 반면 FACILITY는 H7-2에서 제거된 잔존 값이다.
# 정의는 floor_plan.py(역할 상수 정본, RESIDENT_ROLES와 같은 자리) — 여기서는 재수출만 한다.
from ai_core.tools.floor_plan import OFFICE_ROLES, RESIDENT_ROLES
from ai_core.tools.registry import Tool, ToolCard, ToolContext, ToolDeps, ToolResult

_SOURCE_KIND = "tool:search_similar_inquiries"
_CARD_TITLE = "유사 민원 처리 사례"
_LIMIT = 5
# 0.3 → 0.5 → 0.4로 두 번 옮겼다(2026-08-01). 근거는 실측 분포다(ADR-0024 §실측):
#   0.385  "엘리베이터가 덜컹거려요" ↔ "월패드에서 엘리베이터 호출이 안 됩니다"  = 무관
#   0.462  "지하 2층 조명이 깜빡여요" ↔ "지하 2층 조명이 계속 깜빡입니다"        = 유관
# 0.3은 무관 사례를 붙여 모델이 (옳게) NO_EVIDENCE를 냈고, 0.5는 그걸 고치면서 0.46~0.47대
# 유관 사례까지 잘라 회수를 죽였다. 경계는 그 사이 — 명사 하나만 겹치는 건 떨어지고 증상이
# 같은 건 남는 값이다. trigram은 의미검색이 아니라 어휘 겹침이라 이 경계는 데이터 의존적이며,
# 시드가 바뀌면 다시 재봐야 한다(임베딩 승격 조건은 ADR-0024).
_SIMILARITY_THRESHOLD = 0.4
_REPLY_MAX_CHARS = 120
_ELLIPSIS = "…"

_NO_MATCH_QUOTE = "비슷한 민원 기록을 찾지 못했습니다."
# 부정문("답변 기록 없음")을 쓰면 8B가 카드 전체를 근거 없음으로 읽고 NO_EVIDENCE를 뱉는다
# (2026-08-01 실측 — 카드 2건이 실제로 있었는데도 폴백). 상태를 긍정문으로 말해준다.
_STATUS_ONLY = {"done": "처리 완료(답변 기록 없음)"}
_IN_PROGRESS_NOTE = "관리사무소가 처리 중"

_STATUS_LABEL = {
    "received": "미배정",
    "assigned": "배정됨",
    "in_progress": "처리중",
    "done": "완료",
    "reopened": "재확인",
}

# 랭킹 식이 SELECT·WHERE·ORDER BY에 반복되므로 한 곳에서 만든다.
_SIMILARITY = "word_similarity(:q, i.title || ' ' || i.body)"

# `%` 연산자 대신 함수형 word_similarity + 명시 임계 — 세션 GUC
# (pg_trgm.word_similarity_threshold)에 기대면 세션 상태에 따라 결과가 달라진다.
# 담당자 답변은 최신 1건만 LATERAL로 붙인다(타임라인 전체는 노출 대상이 아니다).
_SIMILAR_SQL = text(
    "SELECT i.title, i.status, c.label AS category_label, "
    "(i.author_user_id = :uid) AS is_mine, r.body AS reply_body "
    "FROM inquiries i "
    "LEFT JOIN codes c ON c.id = i.category_code_id AND c.tenant_id = i.tenant_id "
    "LEFT JOIN LATERAL ("
    "  SELECT e.payload->>'body' AS body FROM inquiry_events e "
    "  WHERE e.inquiry_id = i.id AND e.tenant_id = i.tenant_id "
    "    AND e.type = 'comment' AND e.payload->>'kind' = 'reply' "
    "  ORDER BY e.created_at DESC LIMIT 1"
    ") r ON TRUE "
    "WHERE i.tenant_id = :tid AND i.deleted_at IS NULL "
    "  AND (i.status = 'done' OR i.author_user_id = :uid) "
    f"  AND {_SIMILARITY} >= :threshold "
    f"ORDER BY {_SIMILARITY} DESC LIMIT :lim"
)


class SimilarInquiriesArgs(BaseModel):
    # library.QueryArgs를 재사용하지 않는다 — library가 이 모듈을 import하므로 순환된다.
    query: str = Field(..., min_length=1, description="민원 내용·증상 요약")


def _summary(reply_body: str | None, status: str) -> str:
    """처리결과 한 줄 — 담당자 답변이 있으면 발췌, 없으면 상태를 긍정문으로."""
    if not reply_body:
        return _STATUS_ONLY.get(status, _IN_PROGRESS_NOTE)
    # 카드 quote는 한 줄 단위로 읽히므로 줄바꿈은 접는다.
    body = " ".join(reply_body.split())
    if len(body) <= _REPLY_MAX_CHARS:
        return body
    return body[:_REPLY_MAX_CHARS] + _ELLIPSIS


def _line(r: Any) -> str:
    category = r.category_label or "분류없음"
    mine = f" (내 접수 · {_STATUS_LABEL.get(r.status, r.status)})" if r.is_mine else ""
    return f"- [{category}] {r.title}{mine} — 처리결과: {_summary(r.reply_body, r.status)}"


async def _search_similar_inquiries(
    ctx: ToolContext, deps: ToolDeps, args: BaseModel
) -> ToolResult:
    a = cast(SimilarInquiriesArgs, args)
    rows = (
        await deps.session.execute(
            _SIMILAR_SQL,
            {
                "q": a.query,
                "tid": ctx.tenant_id,
                "uid": ctx.user_id,
                "threshold": _SIMILARITY_THRESHOLD,
                "lim": _LIMIT,
            },
        )
    ).all()
    # DB가 확인한 "없음"도 확정 근거 — note면 인용 카드가 없어 폴백된다(⓪ 계약, R22 실측).
    # 건수를 머리말로 세어준다 — 목록만 주면 8B가 근거의 존재를 놓치고 NO_EVIDENCE로 샜다.
    quote = (
        f"비슷한 민원 {len(rows)}건:\n" + "\n".join(_line(r) for r in rows)
        if rows
        else _NO_MATCH_QUOTE
    )
    return ToolResult(
        card=ToolCard(title=_CARD_TITLE, quote=quote, source_kind=_SOURCE_KIND, data=_data(rows))
    )


def _data(rows: Sequence[Any]) -> dict[str, Any]:
    """화면용 사례 목록(ADR-0025 §6) — quote와 같은 값을 필드로 쪼갠 것뿐.

    노출 범위는 quote와 동일하다(제목·분류·상태·처리결과 발췌). 작성자·동호수·본문은 SQL이
    읽지도 않으므로 여기에 들어올 수 없다(규칙 2 — 안 읽으면 마스킹 실패 경로도 없다).
    """
    return {
        "kind": "inquiry_cases",
        "cases": [
            {
                "title": r.title,
                "category": r.category_label or "분류없음",
                "status": _STATUS_LABEL.get(r.status, r.status),
                "resolution": _summary(r.reply_body, r.status),
                "is_mine": bool(r.is_mine),
            }
            for r in rows
        ],
    }


def search_similar_inquiries_tool() -> Tool:
    return Tool(
        name="search_similar_inquiries",
        # 초안은 "이전에 접수된 비슷한 **민원**"으로 시작하고 경계를 "…만 물으면
        # get_my_inquiries를 쓴다"로 달았는데, 실측(2026-08-01)에서 정확히 반대로 갈렸다:
        # 신고 4건은 전부 find_in_floor_plan/문서로 새고, "제가 접수한 민원" 질문만 이 도구를
        # 골랐다. '민원'이라는 단어가 설명 앞머리와 타 도구 이름에 함께 있어 그 단어가 든
        # 질문을 빨아들인 것 — R22의 "의미 중복이 라우팅을 무너뜨린다"와 같은 실패다.
        # 그래서 앞머리를 **증상 신고 상황**으로 바꾸고 '민원'·타 도구 이름은 뺐다.
        description=(
            "고장·누수·소음·냄새·하자처럼 불편한 상태를 겪고 있다고 말하거나 신고할 때 쓴다. "
            "같은 단지에서 앞서 같은 증상이 접수됐다면 어떻게 처리됐는지 찾아 알려준다. "
            "이미 접수한 건의 진행 상태를 묻는 질문에는 쓰지 않는다."
        ),
        args_model=SimilarInquiriesArgs,
        run=_search_similar_inquiries,
        allowed_roles=RESIDENT_ROLES,
    )


# ── summarize_inquiries — 기간·동별 집계 + 미처리 목록 (H19-3, ADR-0026 결정 2) ──

_SUMMARY_SOURCE_KIND = "tool:summarize_inquiries"
_SUMMARY_CARD_TITLE = "민원 현황 요약"
_SUMMARY_DEFAULT_DAYS = 7
_SUMMARY_MIN_DAYS = 1
_SUMMARY_MAX_DAYS = 90
_PENDING_LIMIT = 5
# "미처리" = 아직 손대지 않은 상태. 처리중(in_progress)·완료(done)는 상태별 집계 수치에는
# 나오지만 목록에는 넣지 않는다 — 담당자가 먼저 볼 것은 배정·착수가 안 된 건이다.
_PENDING_STATUSES = ("received", "assigned", "reopened")
_PENDING_IN = ", ".join(f"'{s}'" for s in _PENDING_STATUSES)

# 세 쿼리(상태 집계·유형 집계·미처리 목록)가 같은 범위를 본다 — 조건은 한 곳에서 만든다.
# households·buildings는 **동 필터를 위해서만** 조인한다(SELECT에는 넣지 않는다 — 규칙 2).
# 동 인자는 NULL 허용이라 asyncpg가 타입을 못 정한다 → 명시 CAST.
_SUMMARY_SCOPE = (
    "FROM inquiries i "
    "JOIN households h ON h.id = i.household_id AND h.tenant_id = i.tenant_id "
    "JOIN buildings b ON b.id = h.building_id AND b.tenant_id = i.tenant_id "
    "LEFT JOIN codes c ON c.id = i.category_code_id AND c.tenant_id = i.tenant_id "
    "WHERE i.tenant_id = :tid AND i.deleted_at IS NULL AND i.created_at >= :since "
    "AND (CAST(:dong AS text) IS NULL OR b.name = CAST(:dong AS text)) "
)

# 집계는 SQL이 확정한다 — 파이썬에서 다시 세지 않는다(규칙 8: 답변 숫자는 도구 확정값).
# ROLLUP의 status NULL 행이 총 건수다(inquiries.status는 NOT NULL이라 혼동 없음).
_STATUS_COUNT_SQL = text(
    "SELECT i.status AS status, count(*) AS cnt "
    + _SUMMARY_SCOPE
    + "GROUP BY ROLLUP(i.status) ORDER BY count(*) DESC"
)
_CATEGORY_COUNT_SQL = text(
    "SELECT c.label AS category_label, count(*) AS cnt "
    + _SUMMARY_SCOPE
    + "GROUP BY c.label ORDER BY count(*) DESC"
)
# 목록도 제목·분류·상태·접수일까지만 — 본문(i.body)·작성자(author_user_id)·동호수는 읽지
# 않는다. 시나리오 예시엔 동호수가 있었지만 규칙 2로 뺐다(ADR-0026: 담당자는 민원 화면에서
# 본다 — LLM 컨텍스트의 노출면을 넓힐 이유가 없다).
_PENDING_SQL = text(
    "SELECT i.title, i.status, c.label AS category_label, i.created_at "
    + _SUMMARY_SCOPE
    + f"AND i.status IN ({_PENDING_IN}) "
    + "ORDER BY i.created_at LIMIT :lim"
)


class SummarizeInquiriesArgs(BaseModel):
    # 인자는 둘뿐 — 8B는 인자가 늘수록 라우팅·인자 생성이 함께 무너진다(R22 계열).
    days: int = Field(
        _SUMMARY_DEFAULT_DAYS,
        ge=_SUMMARY_MIN_DAYS,
        le=_SUMMARY_MAX_DAYS,
        description="집계 기간(일). 이번 주면 7, 한 달이면 30. 생략 시 최근 7일",
    )
    dong: str | None = Field(
        None, description="특정 동만 볼 때 동 이름(예: '404'). 생략 시 전체 동"
    )


def _scope_label(days: int, dong: str | None) -> str:
    return f"최근 {days}일" + (f" · {dong}동" if dong else "")


def _counts(pairs: Iterable[tuple[str, int]]) -> str:
    """집계 한 줄 — 값은 SQL이 센 그대로 옮긴다(파이썬 재계산 없음)."""
    return ", ".join(f"{name} {cnt}건" for name, cnt in pairs)


def _pending_line(now: datetime, r: Any) -> str:
    category = r.category_label or "분류없음"
    status = _STATUS_LABEL.get(r.status, r.status)
    return f"- [{category}] {r.title} ({status} · {(now - r.created_at).days}일 경과)"


async def _summarize_inquiries(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    a = cast(SummarizeInquiriesArgs, args)
    now = datetime.now(UTC)
    scope = {"tid": ctx.tenant_id, "since": now - timedelta(days=a.days), "dong": a.dong}

    status_rows = (await deps.session.execute(_STATUS_COUNT_SQL, scope)).all()
    total = next((int(r.cnt) for r in status_rows if r.status is None), 0)
    label = _scope_label(a.days, a.dong)
    # 0건도 DB가 확인한 확정 근거 — note면 인용 카드가 없어 폴백된다(⓪ 계약, R22 실측).
    if total == 0:
        return ToolResult(
            card=ToolCard(
                title=_SUMMARY_CARD_TITLE,
                quote=f"{label}에 접수된 민원이 없습니다.",
                source_kind=_SUMMARY_SOURCE_KIND,
            )
        )

    category_rows = (await deps.session.execute(_CATEGORY_COUNT_SQL, scope)).all()
    pending_rows = (
        await deps.session.execute(_PENDING_SQL, {**scope, "lim": _PENDING_LIMIT})
    ).all()

    lines = [
        f"{label} 접수 민원 {total}건",
        "- 상태별: "
        + _counts(
            (_STATUS_LABEL.get(r.status, r.status), int(r.cnt))
            for r in status_rows
            if r.status is not None  # ROLLUP 총계 행 제외
        ),
        "- 유형별: " + _counts((r.category_label or "분류없음", int(r.cnt)) for r in category_rows),
    ]
    if pending_rows:
        # 여기에는 건수를 쓰지 않는다 — 목록은 상한 5건으로 잘리므로 "미처리 5건"이라고 쓰면
        # 상태별 집계(미배정 N건)와 어긋난 숫자가 답변에 섞인다. 총 건수는 첫 줄이 준다.
        lines.append("미처리 우선 목록(오래된 순):")
        lines.extend(_pending_line(now, r) for r in pending_rows)
    else:
        lines.append("미처리(미배정·배정됨·재확인) 민원은 없습니다.")
    return ToolResult(
        card=ToolCard(
            title=_SUMMARY_CARD_TITLE,
            quote="\n".join(lines),
            source_kind=_SUMMARY_SOURCE_KIND,
        )
    )


def summarize_inquiries_tool() -> Tool:
    return Tool(
        name="summarize_inquiries",
        # 민원 도구 3종의 경계가 이 설명의 전부다(R22 — 의미 중복이 라우팅을 무너뜨린다):
        # ①본인 건 진행 상황 = get_my_inquiries ②비슷한 사례 = search_similar_inquiries
        # ③단지 전체 현황·통계 = 이 도구. 그래서 '현황·통계·집계·몇 건' 어휘만 쓰고
        # 나머지 둘은 명시적으로 배제한다.
        description=(
            "단지 전체 민원의 현황 통계를 조회한다 — 기간·동별로 몇 건이 접수됐고 "
            "상태·유형별로 어떻게 나뉘는지, 아직 처리되지 않은 건이 무엇인지. "
            "'민원 현황', '이번 주 민원 몇 건', '404동 민원 요약'처럼 집계를 물을 때 쓴다 — "
            "내가 접수한 민원의 진행 상황이나 비슷한 사례를 찾는 질문에는 쓰지 않는다."
        ),
        args_model=SummarizeInquiriesArgs,
        run=_summarize_inquiries,
        allowed_roles=OFFICE_ROLES,
    )
