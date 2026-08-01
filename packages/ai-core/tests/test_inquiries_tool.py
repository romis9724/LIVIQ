"""search_similar_inquiries 도구 — 노출 범위 제한·발췌 상한·0건 카드 승격·역할 가시성.

SQL은 conftest.FakeSession(쿼리 텍스트 분기)으로 검증한다 — word_similarity 랭킹 자체는
PG의 몫이고 여기서는 포매팅·마스킹 경계·파라미터 출처를 본다(test_parking_tool 관례).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, cast

import httpx
from conftest import FakeSession, row
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool
from ai_core.tools.inquiries import SimilarInquiriesArgs

TENANT = uuid.uuid4()
USER = uuid.uuid4()

CTX = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

_OTHERS_ROW = row(
    title="화장실 천장 누수",
    status="done",
    category_label="누수",
    is_mine=False,
    reply_body="위층 배관 이음부를 교체했습니다.\n재발 시 재접수 바랍니다.",
)
_MINE_ROW = row(
    title="세탁실 배수 역류",
    status="in_progress",
    category_label=None,
    is_mine=True,
    reply_body=None,
)


# ── fakes ──────────────────────────────────────────────────────────────


def _handler(rows: list[Any]) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        assert "from inquiries i" in s
        # 읽기 전용(규칙 8) — 부수효과 SQL이 섞이면 즉시 실패.
        assert "insert" not in s and "update" not in s and "delete " not in s
        # 규칙 2 — 본문·작성자·동호수는 SELECT 목록에 없다(author_user_id는 본인 여부
        # boolean으로만 쓴다 — 식별자를 반환하지 않는다).
        select_list = s.split(" from inquiries")[0]
        assert "i.body" not in select_list
        assert "household" not in select_list
        assert select_list.count("author_user_id") == 1
        assert "(i.author_user_id = :uid) as is_mine" in select_list
        # 남의 민원은 완료 건만 + 본인 건은 진행중 포함.
        assert "i.status = 'done' or i.author_user_id = :uid" in s
        assert params["tid"] == TENANT and params["uid"] == USER
        return rows

    return handler


def _noop_llm(settings: AiCoreSettings) -> LlmClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"이 도구는 LLM을 호출하지 않는다: {request.url.path}")

    return LlmClient(settings, transport=httpx.MockTransport(handler), retry_backoff_s=0.0)


class _NoopRetriever:
    async def search(
        self,
        query_embedding: Any,
        *,
        tenant_id: uuid.UUID,
        visibilities: Any,
        top_k: int = 8,
        building_id: uuid.UUID | None = None,
    ) -> list[RetrievedChunk]:
        return []


def _deps(settings: AiCoreSettings, session: FakeSession) -> ToolDeps:
    return ToolDeps(
        session=cast(AsyncSession, session),
        llm=_noop_llm(settings),
        retriever=cast(Retriever, _NoopRetriever()),
        graph=cast(GraphClient, None),
    )


def _call(query: str = "화장실에서 물이 새요") -> ToolCallRequest:
    return ToolCallRequest(
        id="c-inq",
        name="search_similar_inquiries",
        arguments=json.dumps({"query": query}),
    )


# ── (1) 결과 있음 — 제목·카테고리·처리결과만, PII 없음 ─────────────────


async def test_returns_title_category_and_reply_summary(settings: AiCoreSettings) -> None:
    deps = _deps(settings, FakeSession(_handler([_OTHERS_ROW, _MINE_ROW])))
    result = (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result

    assert result.card is not None
    quote = result.card.quote
    assert result.card.source_kind == "tool:search_similar_inquiries"
    assert "[누수] 화장실 천장 누수" in quote
    assert "위층 배관 이음부를 교체했습니다. 재발 시 재접수 바랍니다." in quote
    # 본인 건은 상태 한글과 함께 구분 표기, 카테고리 없으면 "분류없음".
    assert "[분류없음] 세탁실 배수 역류 (내 접수 · 처리중)" in quote
    # 답변이 없는 건은 부정문 대신 상태를 긍정문으로 — 부정문이 섞이면 8B가 카드 전체를
    # 근거 없음으로 읽는다(2026-08-01 실측). 건수 머리말도 같은 이유로 붙인다.
    assert "관리사무소가 처리 중" in quote
    assert quote.startswith("비슷한 민원 2건:")


# ── (2) 0건 → note가 아니라 카드 승격 ───────────────────────────────────


async def test_no_match_promotes_to_card(settings: AiCoreSettings) -> None:
    deps = _deps(settings, FakeSession(_handler([])))
    result = (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result

    assert result.card is not None  # note면 인용 카드가 없어 폴백된다(⓪ 계약)
    assert result.note == ""
    assert "비슷한 민원 기록을 찾지 못했습니다" in result.card.quote


# ── (3) 담당자 답변 120자 절단 ──────────────────────────────────────────


async def test_reply_summary_truncated_at_120_chars(settings: AiCoreSettings) -> None:
    long_reply = "가" * 300
    deps = _deps(
        settings,
        FakeSession(
            _handler(
                [
                    row(
                        title="소음 민원",
                        status="done",
                        category_label="소음",
                        is_mine=False,
                        reply_body=long_reply,
                    )
                ]
            )
        ),
    )
    result = (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result

    assert result.card is not None
    assert "가" * 120 + "…" in result.card.quote
    assert "가" * 121 not in result.card.quote


# ── (4) 역할 가시성 — RESIDENT 전용 ─────────────────────────────────────


def test_resident_specs_include_similar_inquiries_tool() -> None:
    names = {
        s["function"]["name"]
        for s in default_registry().specs_for(("RESIDENT",), graph_available=True)
    }
    assert "search_similar_inquiries" in names


def test_manager_specs_exclude_similar_inquiries_tool() -> None:
    for role in ("MANAGER", "FACILITY", "SYS_ADMIN"):
        names = {
            s["function"]["name"]
            for s in default_registry().specs_for((role,), graph_available=True)
        }
        assert "search_similar_inquiries" not in names


# ── (5) tenant·user는 ToolContext에서만 온다(규칙 3·4 회귀) ─────────────


def test_args_model_has_no_tenant_or_user_fields() -> None:
    assert set(SimilarInquiriesArgs.model_fields) == {"query"}


async def test_sql_params_come_from_context_not_llm_args(settings: AiCoreSettings) -> None:
    session = FakeSession(_handler([]))
    # LLM이 tenant_id·user_id를 주입하려 해도 인자 모델이 흘려보내지 않는다.
    call = ToolCallRequest(
        id="c-inq",
        name="search_similar_inquiries",
        arguments=json.dumps({"query": "누수", "tenant_id": str(uuid.uuid4()), "user_id": "x"}),
    )
    await execute_tool(call, ctx=CTX, deps=_deps(settings, session), registry=default_registry())

    _, params = session.executed[0]
    assert params["tid"] == TENANT and params["uid"] == USER
    assert params["q"] == "누수"
