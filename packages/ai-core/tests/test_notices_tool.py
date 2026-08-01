"""get_recent_notices 도구 — 발행 공지만·발췌 상한·0건 카드 승격·전 역할 노출.

SQL은 conftest.FakeSession(쿼리 텍스트 분기)으로 검증한다 — 정렬·조인은 PG의 몫이고
여기서는 포매팅·필터 조건·파라미터 출처를 본다(test_inquiries_tool 관례).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from conftest import FakeSession, row
from sqlalchemy.ext.asyncio import AsyncSession

from ai_core.config import AiCoreSettings
from ai_core.graph import GraphClient
from ai_core.llm.client import LlmClient, ToolCallRequest
from ai_core.rag.retrieval import RetrievedChunk, Retriever
from ai_core.tools import ToolContext, ToolDeps, default_registry, execute_tool
from ai_core.tools.notices import NoticesArgs

TENANT = uuid.uuid4()
USER = uuid.uuid4()

CTX = ToolContext(TENANT, USER, roles=("RESIDENT",), visibilities=("ALL", "RESIDENT"))

_ROWS = [
    row(
        title="7월 승강기 정기점검 안내",
        published_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
        body="7월 22일 09:00~12:00 승강기 정기점검이 있습니다.\n점검 중 운행이 중단됩니다.",
        category_label="점검",
    ),
    row(
        title="주차장 청소 안내",
        published_at=datetime(2026, 7, 10, 9, 0, tzinfo=UTC),
        body="지하 1층 주차장을 청소합니다.",
        category_label=None,
    ),
]


# ── fakes ──────────────────────────────────────────────────────────────


def _handler(rows: list[Any]) -> Any:
    def handler(sql: str, params: dict[str, Any]) -> list[Any]:
        s = sql.lower()
        assert "from notices n" in s
        # 읽기 전용(규칙 8) — 부수효과 SQL이 섞이면 즉시 실패.
        assert "insert" not in s and "update" not in s and "delete " not in s
        # 발행된 공지만: 미발행·예약·삭제 건은 원천 배제(CRITICAL).
        assert "n.status = 'published'" in s
        assert "n.published_at is not null" in s
        assert "n.deleted_at is null" in s
        # 단지 격리(규칙 3) — tenant 조건은 쿼리와 파라미터 양쪽에.
        assert "n.tenant_id = :tid" in s
        assert params["tid"] == TENANT
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


def _call(arguments: str = "{}") -> ToolCallRequest:
    return ToolCallRequest(id="c-notice", name="get_recent_notices", arguments=arguments)


async def _run(settings: AiCoreSettings, rows: list[Any]) -> Any:
    deps = _deps(settings, FakeSession(_handler(rows)))
    return (await execute_tool(_call(), ctx=CTX, deps=deps, registry=default_registry())).result


# ── (1) 결과 있음 — 제목·발행일·발췌 + 건수 머리말 ──────────────────────


async def test_lists_title_date_and_excerpt_with_count_header(settings: AiCoreSettings) -> None:
    result = await _run(settings, list(_ROWS))

    assert result.card is not None
    quote = result.card.quote
    assert result.card.source_kind == "tool:get_recent_notices"
    assert quote.startswith("최근 공지 2건:")
    assert "[점검] 7월 승강기 정기점검 안내 (2026-07-15)" in quote
    # 본문 발췌는 줄바꿈을 접어 한 줄로.
    assert "7월 22일 09:00~12:00 승강기 정기점검이 있습니다. 점검 중 운행이 중단됩니다." in quote
    # 분류 없는 공지는 "일반".
    assert "[일반] 주차장 청소 안내 (2026-07-10)" in quote


# ── (2) 0건 → note가 아니라 카드 승격 ───────────────────────────────────


async def test_no_notices_promotes_to_card(settings: AiCoreSettings) -> None:
    result = await _run(settings, [])

    assert result.card is not None  # note면 인용 카드가 없어 폴백된다(⓪ 계약)
    assert result.note == ""
    assert result.card.quote == "게시된 공지가 없습니다."
    assert result.card.data == {"kind": "notice_list", "notices": []}


# ── (3) 본문 발췌 100자 절단 ────────────────────────────────────────────


async def test_excerpt_truncated_at_100_chars(settings: AiCoreSettings) -> None:
    long_body = "가" * 300
    result = await _run(
        settings,
        [
            row(
                title="긴 공지",
                published_at=datetime(2026, 7, 1, tzinfo=UTC),
                body=long_body,
                category_label="일반공지",
            )
        ],
    )

    assert result.card is not None
    assert "가" * 100 + "…" in result.card.quote
    assert "가" * 101 not in result.card.quote


# ── (4) data — notice_list 스키마 + quote와 값 일치 ─────────────────────


async def test_data_is_notice_list_matching_quote(settings: AiCoreSettings) -> None:
    result = await _run(settings, list(_ROWS))

    assert result.card is not None and result.card.data is not None
    data = result.card.data
    assert data == {
        "kind": "notice_list",
        "notices": [
            {
                "title": "7월 승강기 정기점검 안내",
                "published_at": "2026-07-15",
                "category": "점검",
                "excerpt": (
                    "7월 22일 09:00~12:00 승강기 정기점검이 있습니다. 점검 중 운행이 중단됩니다."
                ),
            },
            {
                "title": "주차장 청소 안내",
                "published_at": "2026-07-10",
                "category": "일반",
                "excerpt": "지하 1층 주차장을 청소합니다.",
            },
        ],
    }
    # 화면 값과 LLM에 준 값은 같은 출처여야 한다.
    for notice in data["notices"]:
        assert f"{notice['title']} ({notice['published_at']})" in result.card.quote
        assert notice["excerpt"] in result.card.quote


async def test_data_is_not_sent_to_llm(settings: AiCoreSettings) -> None:
    """불변식: data는 화면 전용 — llm_text()에 섞이지 않는다(ADR-0025 §6)."""
    result = await _run(settings, list(_ROWS))

    assert result.card is not None and result.card.data is not None
    assert json.dumps(result.card.data, ensure_ascii=False) not in result.llm_text()
    assert result.llm_text() == f"{result.card.title}: {result.card.quote}"


# ── (5) 역할 가시성 — 전 역할 ───────────────────────────────────────────


def test_visible_to_all_roles() -> None:
    for role in ("RESIDENT", "MANAGER", "FACILITY", "SYS_ADMIN"):
        names = {
            s["function"]["name"]
            for s in default_registry().specs_for((role,), graph_available=True)
        }
        assert "get_recent_notices" in names


# ── (6) tenant는 ToolContext에서만 온다(규칙 3·4 회귀) ──────────────────


def test_args_model_has_no_tenant_or_user_fields() -> None:
    assert NoticesArgs.model_fields == {}


async def test_sql_params_come_from_context_not_llm_args(settings: AiCoreSettings) -> None:
    session = FakeSession(_handler([]))
    # LLM이 tenant_id를 주입하려 해도 인자 모델이 흘려보내지 않는다.
    call = _call(json.dumps({"tenant_id": str(uuid.uuid4()), "user_id": "x"}))
    await execute_tool(call, ctx=CTX, deps=_deps(settings, session), registry=default_registry())

    _, params = session.executed[0]
    assert params["tid"] == TENANT
    assert set(params) == {"tid", "lim"}
