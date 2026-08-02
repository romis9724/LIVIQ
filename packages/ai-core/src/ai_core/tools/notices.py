"""get_recent_notices — 게시판에 최근 올라온 공지 목록 (H18).

"공지사항", "최근에 뭐 올라왔어" 같은 **메타 질의**를 받는다. 유사도 검색은 이런 질문에
못 쓴다 — 그 단어가 어느 공지 본문에도 없어 `search_documents`가 빈손으로 폴백했다
(2026-08-01 사용자 실측). 같은 세션에서 "엘리베이터 점검일자"는 공지를 근거로 정상
답변했으니 색인 문제가 아니라 **질의 종류가 벡터 검색에 안 맞는 것**이다.

발행된 공지만(status='published' + published_at NOT NULL + 미삭제) 최신순 5건. 읽기 전용
SELECT뿐이다(규칙 8). tenant_id는 ToolContext에서 오며 LLM 인자로 받지 않는다(규칙 3·4).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from ai_core.tools.registry import Tool, ToolCard, ToolContext, ToolDeps, ToolResult

_SOURCE_KIND = "tool:get_recent_notices"
_CARD_TITLE = "최근 공지"
_LIMIT = 5
_EXCERPT_MAX_CHARS = 100
_ELLIPSIS = "…"

_EMPTY_QUOTE = "게시된 공지가 없습니다."

# 대상 동(target_buildings)은 필터하지 않는다 — 모델 주석대로 **표시용** 필드이지 게시
# 노출 제어가 아니다(알림 타게팅은 백로그). 게시판이 보여주는 것과 도구가 보여주는 것이
# 갈라지면 "앱엔 있는데 AI는 없다더라"가 된다.
_RECENT_SQL = text(
    "SELECT n.title, n.published_at, n.body, c.label AS category_label "
    "FROM notices n "
    "LEFT JOIN codes c ON c.id = n.category_code_id AND c.tenant_id = n.tenant_id "
    "WHERE n.tenant_id = :tid AND n.deleted_at IS NULL "
    "  AND n.status = 'published' AND n.published_at IS NOT NULL "
    "ORDER BY n.published_at DESC LIMIT :lim"
)


# 인자 없음 — 8B는 인자가 늘수록 라우팅·인자 생성이 함께 무너진다(R22 계열 실패). 이 도구가
# 받는 질문("공지 뭐 있어")에는 걸러낼 축이 없고, 최신 5건이면 답이 된다. 카테고리·기간
# 필터는 실제로 그런 질문이 관측되면 그때 붙인다(YAGNI).
class NoticesArgs(BaseModel):
    pass


def _excerpt(body: str) -> str:
    """본문 한 줄 발췌 — quote는 줄 단위로 읽히므로 줄바꿈은 접는다.

    notices.body는 NOT NULL이라 None 방어는 두지 않는다(모델 계약).
    """
    text_ = " ".join(body.split())
    if len(text_) <= _EXCERPT_MAX_CHARS:
        return text_
    return text_[:_EXCERPT_MAX_CHARS] + _ELLIPSIS


def _date(published_at: datetime | None) -> str:
    return f"{published_at:%Y-%m-%d}" if published_at else "발행일 미상"


def _line(r: Any) -> str:
    category = r.category_label or "일반"
    return f"- [{category}] {r.title} ({_date(r.published_at)}) — {_excerpt(r.body)}"


async def _get_recent_notices(ctx: ToolContext, deps: ToolDeps, args: BaseModel) -> ToolResult:
    rows = (await deps.session.execute(_RECENT_SQL, {"tid": ctx.tenant_id, "lim": _LIMIT})).all()
    # 0건도 DB가 확인한 확정 근거 — note면 인용 카드가 없어 폴백된다(⓪ 계약, R22 실측).
    # 건수 머리말은 inquiries.py와 같은 이유 — 목록만 주면 8B가 근거의 존재를 놓친다.
    quote = (
        f"최근 공지 {len(rows)}건:\n" + "\n".join(_line(r) for r in rows) if rows else _EMPTY_QUOTE
    )
    return ToolResult(
        card=ToolCard(title=_CARD_TITLE, quote=quote, source_kind=_SOURCE_KIND, data=_data(rows))
    )


def _data(rows: Sequence[Any]) -> dict[str, Any]:
    """화면용 공지 목록(ADR-0025 §6) — quote와 같은 값을 필드로 쪼갠 것뿐.

    LLM은 이 dict를 보지 않는다(ToolCard.data 불변식) — 화면 렌더 전용.
    """
    return {
        "kind": "notice_list",
        "notices": [
            {
                "title": r.title,
                "published_at": _date(r.published_at),
                "category": r.category_label or "일반",
                "excerpt": _excerpt(r.body),
            }
            for r in rows
        ],
    }


def get_recent_notices_tool() -> Tool:
    return Tool(
        name="get_recent_notices",
        # search_documents와의 경계가 이 도구의 전부다(R22 — 의미 중복이 라우팅을 무너뜨린다).
        # 가르는 축은 **목록이냐 내용이냐**다: "무엇이 올라왔는지"는 이 도구, "거기 뭐라고
        # 적혀 있는지"는 search_documents. 그래서 '규약·회의록' 같은 문서 어휘는 쓰지 않고
        # 게시판·최신순·목록만 말한다.
        # 배제 문장을 "특정 공지의 내용"에서 "특정 주제의 내용·일정"으로 넓힌 건 R36 실측 —
        # "이번 달 실내소독 언제야?"(0332)에는 '공지'라는 말이 없어 기존 문구가 안 걸렸다.
        # 주제어를 쓰고 일정을 명시해야 목록/내용 경계가 질문 어휘와 맞는다.
        description=(
            "게시판에 최근 올라온 공지 목록을 최신순으로 조회한다. "
            "'공지사항', '새로 올라온 공지', '요즘 무슨 공지 있어'처럼 어떤 공지가 있는지 "
            "자체를 물을 때 쓴다. 특정 주제의 내용·일정(점검 일자·소독 시기·규정 등)을 묻는 "
            "질문에는 쓰지 않는다 — 문서 검색을 쓴다."
        ),
        args_model=NoticesArgs,
        run=_get_recent_notices,
        # 공지는 입주민·직원 모두 본다 — 역할 제한 없음.
        allowed_roles=None,
    )
