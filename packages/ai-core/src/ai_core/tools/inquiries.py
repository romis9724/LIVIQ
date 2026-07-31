"""search_similar_inquiries — 같은 단지의 유사 민원 처리 사례 (H17-1, ADR-0024).

`pg_trgm.word_similarity`로 제목+본문을 랭킹한다(임계 0.3·상한 5건). 읽기 전용 SELECT뿐이고
**AI는 민원을 생성하지 않는다** — 접수는 사용자가 폼에서 한다(규칙 8, 프론트가 딥링크 CTA).

노출은 제목·카테고리 라벨·담당자 답변 발췌(120자)로 제한한다. 작성자·동호수·본문은 컬럼
자체를 읽지 않는다 — 안 읽으면 마스킹 실패 경로도 없다(규칙 2). 남의 민원은 `status='done'`
(답이 확정된 건)만, 본인 민원은 진행중도 포함해 중복 접수를 막는다.

tenant_id·user_id는 ToolContext에서 오며 LLM 인자로 받지 않는다(규칙 3·4).
"""

from __future__ import annotations

from typing import Any, cast

from pydantic import BaseModel, Field
from sqlalchemy import text

from ai_core.tools.floor_plan import RESIDENT_ROLES
from ai_core.tools.registry import Tool, ToolCard, ToolContext, ToolDeps, ToolResult

_SOURCE_KIND = "tool:search_similar_inquiries"
_CARD_TITLE = "유사 민원 처리 사례"
_LIMIT = 5
# 조사·어미 변화를 흡수하는 최소선. 낮추면 무관한 민원이 근거로 붙는다(ADR-0024).
_SIMILARITY_THRESHOLD = 0.3
_REPLY_MAX_CHARS = 120
_ELLIPSIS = "…"

_NO_MATCH_QUOTE = "비슷한 민원 기록을 찾지 못했습니다."
_NO_REPLY = "담당자 답변 기록 없음"

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


def _summary(reply_body: str | None) -> str:
    if not reply_body:
        return _NO_REPLY
    # 카드 quote는 한 줄 단위로 읽히므로 줄바꿈은 접는다.
    body = " ".join(reply_body.split())
    if len(body) <= _REPLY_MAX_CHARS:
        return body
    return body[:_REPLY_MAX_CHARS] + _ELLIPSIS


def _line(r: Any) -> str:
    category = r.category_label or "분류없음"
    mine = f" (내 접수 · {_STATUS_LABEL.get(r.status, r.status)})" if r.is_mine else ""
    return f"- [{category}] {r.title}{mine} — 처리결과: {_summary(r.reply_body)}"


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
    quote = "\n".join(_line(r) for r in rows) if rows else _NO_MATCH_QUOTE
    return ToolResult(card=ToolCard(title=_CARD_TITLE, quote=quote, source_kind=_SOURCE_KIND))


def search_similar_inquiries_tool() -> Tool:
    return Tool(
        name="search_similar_inquiries",
        # get_my_inquiries와 의미가 겹치면 8B 라우팅이 무너진다(R22 선례) — 경계를
        # 마지막 문장으로 못 박는다. 고장·신고 용례는 시설 신고까지 이 도구가 받게 한다.
        description=(
            "단지에서 이전에 접수된 비슷한 민원이 어떻게 처리됐는지 찾는다. "
            "고장·누수·소음·하자 등 불편사항을 말하거나 신고하려 할 때 쓴다 — "
            "본인이 접수한 민원의 진행 상태만 물으면 get_my_inquiries를 쓴다."
        ),
        args_model=SimilarInquiriesArgs,
        run=_search_similar_inquiries,
        allowed_roles=RESIDENT_ROLES,
    )
