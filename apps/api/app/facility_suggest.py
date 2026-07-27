"""민원-시설 LLM 추천 — 후보 제시까지만 (H13-2, FR-FAC-05 ②, ADR-0022 결정 3).

읽기 전용 모듈이다. DB를 만지지 않고 어떤 부수효과도 내지 않는다 — 정식 연결(FK 쓰기)은
담당자 승인 액션(PUT /admin/inquiries/{id}/facility)만 수행한다(규칙 8).
민원 본문은 LLM 호출 직전 `ensure_masked`를 통과한다. 실패하면 예외로 중단하고 호출하지
않는다(규칙 2 fail-closed, ADR-0002). LLM이 목록에 없는 설비 id를 지어내면 버린다(규칙 1 계열).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ai_core.llm.client import LlmClient
from ai_core.masking import ensure_masked, unmask
from liviq_db.models import Facility

logger = logging.getLogger("app.facility_suggest")

MAX_CANDIDATES = 3
# ponytail: 프롬프트에 싣는 설비 상한(단지당 수십 개 전제). 넘치면 이름순 앞부분만 —
# 규모가 커지면 위치·계통으로 1차 필터 후 넘기는 방식으로 올린다.
MAX_PROMPT_FACILITIES = 60
MAX_REASON_LEN = 200
SUGGEST_MAX_TOKENS = 400

SUGGEST_SYSTEM_PROMPT = """당신은 아파트 민원을 담당 설비에 연결하는 분류 도우미입니다. 규칙:
1. 아래 [설비 목록]에 있는 설비만 후보로 고르십시오. 목록에 없는 id·이름을 지어내지 마십시오.
2. 관련 설비가 없으면 빈 배열을 반환하십시오. 억지로 채우지 마십시오.
3. 관련성이 높은 순으로 최대 3개까지 제시하십시오.
4. reason은 민원 내용과 설비를 잇는 근거를 한 문장(한국어)으로 적으십시오.
5. 다른 설명 없이 JSON만 출력하십시오:
{"candidates": [{"facility_id": "<목록의 id>", "reason": "<한 문장>"}]}"""


@dataclass(frozen=True)
class SuggestedFacility:
    """추천 후보 1건. name은 LLM 응답이 아니라 DB 행에서 가져온다(환각 차단)."""

    facility_id: uuid.UUID
    name: str
    reason: str


async def suggest_facilities(
    *,
    llm: LlmClient,
    title: str,
    body: str,
    facilities: Sequence[Facility],
) -> list[SuggestedFacility]:
    """민원 본문(마스킹 후)과 tenant 설비 목록으로 후보 최대 3개. 쓰기·부수효과 없음.

    MaskingFailedError·LlmError는 그대로 올려보낸다(호출자가 HTTP 상태로 변환).
    """
    known = {str(f.id): f for f in facilities[:MAX_PROMPT_FACILITIES]}
    if not known:
        return []

    masked = ensure_masked(f"{title}\n{body}")  # fail-closed — 실패 시 아래 호출까지 못 간다
    response = await llm.chat(
        [
            {"role": "system", "content": SUGGEST_SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(known.values(), masked.masked_text)},
        ],
        max_tokens=SUGGEST_MAX_TOKENS,
    )
    return _parse_candidates(response.text, known, masked.replacements)


def _user_prompt(facilities: Iterable[Facility], masked_text: str) -> str:
    lines = "\n".join(
        f"- id={f.id} | 이름={f.name} | 계통={f.type or '미지정'} | 위치={f.location or '미지정'}"
        for f in facilities
    )
    return f"[설비 목록]\n{lines}\n\n[민원]\n{masked_text}"


def _parse_candidates(
    text: str, known: Mapping[str, Facility], replacements: Mapping[str, str]
) -> list[SuggestedFacility]:
    payload = _json_object(text)
    if payload is None:
        logger.warning("시설 추천 응답 파싱 실패 — 후보 없음으로 처리")
        return []
    raw = payload.get("candidates")
    if not isinstance(raw, list):
        return []

    candidates: list[SuggestedFacility] = []
    seen: set[uuid.UUID] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        facility = known.get(str(item.get("facility_id")))
        if facility is None:  # 목록에 없는 id = 환각 → 버린다(규칙 1 계열)
            logger.warning("시설 추천 후보 폐기 — 알 수 없는 facility_id")
            continue
        if facility.id in seen:
            continue
        seen.add(facility.id)
        reason = unmask(str(item.get("reason") or "").strip(), replacements)[:MAX_REASON_LEN]
        candidates.append(
            SuggestedFacility(facility_id=facility.id, name=facility.name, reason=reason)
        )
        if len(candidates) == MAX_CANDIDATES:
            break
    return candidates


def _json_object(text: str) -> dict[str, Any] | None:
    """응답에서 JSON 객체만 추출(코드펜스·군더더기 허용). 실패는 None."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None
