"""구조 인지 청킹 — 조/항·제목·문단 경계 우선, 토큰 상한 내 병합 (docs/01 §5.1, 08 §3).

오버랩은 두지 않는다(중복=토큰 낭비). 경계 우선순위:
1) 조항 마커(제N조)·마크다운 제목 → 새 섹션(제목 메타 유지)
2) 빈 줄(문단) → 병합 단위
3) 상한 초과 장문 문단 → 문장 단위 분할
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ai_core.llm.tokens import estimate_tokens

# 청크 토큰 상한(bge-m3 입력·컨텍스트 예산 균형 — 파일럿 보정 대상)
CHUNK_MAX_TOKENS = 400

# 섹션 경계: 마크다운 제목 또는 조항 마커로 시작하는 줄.
# 조항 마커는 실문서 표기 변형 수용: `제18조` · `[제18조]`(대괄호) · `Article 9`(영문 규정).
#
# 제목은 **표제까지만** 잡는다 — 줄 끝까지(`[^\n]*`) 삼키면 안 된다. PDF 추출문은 한 줄이
# 수천 자여서(첫마을 관리규약 실측: 줄 길이 중위 428자·최대 2,874자) 제목이 900토큰까지
# 커지고, _make_chunk가 그 제목을 매 청크에 붙여 청크가 상한의 3배가 됐다
# (실측 평균 1,217토큰 / 상한 400 — 188청크 중 186개 초과, H15-2 #3).
# 조항 표제: 괄호형(`제48조(주택관리업자 선정방법)`) 또는 공백형(`제18조 공사 시간`).
# 어느 쪽이든 **길이를 제한**한다 — 상한이 없던 것이 위 결함의 원인이다.
_CLAUSE_TITLE = r"(?:\s*[(（【][^)）】\n]{0,60}[)）】]|[ \t]{1,3}[^\n.。①]{1,40})?"
_SECTION_RE = re.compile(
    r"^(#{1,6}\s+[^\n]{1,120}"
    rf"|\[?제\s?\d+\s?조\]?{_CLAUSE_TITLE}"
    rf"|Article\s+\d+{_CLAUSE_TITLE})",
    re.MULTILINE,
)
# 문장 경계. PDF 추출문은 마침표 뒤 공백을 잃는다(`적용한다.2. [준칙]` — 실측 1,832곳)
# → 종결어미 뒤에는 공백을 요구하지 않는다. 항번호(①②③)는 규약의 실제 구조 단위라 경계로 쓴다.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|(?<=[다함음됨임])\.\s*|(?=[①②③④⑤⑥⑦⑧⑨⑩])")
# 목차 줄 — 점선 리더(가운뎃점 3개 이상 또는 마침표 6개 이상)가 있으면 목차·색인이지 본문이
# 아니다. **줄 전체를 버린다**: 리더만 지우면 목차 항목이 조항 제목으로 남아 가짜 섹션이 된다
# (첫마을 관리규약 실측 — 목차가 6줄에 조항 90개를 담고 있어 조항마다 중복 섹션이 생겼다).
# 마침표는 6개 이상만 본다 — 말줄임표(`...`)를 목차로 오인하면 본문이 사라진다.
_TOC_LINE_RE = re.compile(r"^.*(?:·{3,}|\.{6,}).*$", re.MULTILINE)
# 조항 제목은 **줄 중간에도** 온다 — PDF 추출문은 조 사이에 개행이 없다. 줄머리만 보면
# 우연히 줄머리에 걸린 조항 하나가 뒤따르는 수십 개 청크의 제목을 가로챈다(제1조 내용이
# 제64조로 라벨링됐다 — 인용이 틀린 조항을 가리키므로 NULL보다 나쁘다).
_CLAUSE_ANYWHERE_RE = re.compile(r"제\s?\d+조(?:의\d+)?\s*\([^)\n]{0,60}\)")
# 법령 참조(`법 제18조제2항`·`영 제19조`·`「공동주택관리법」제18조`)는 제목이 아니다.
_LEGAL_REF_TAIL_RE = re.compile(r"(?:법|영|규칙|법률|」|조례)\s*$")
_LEGAL_REF_LOOKBACK = 12
# 조항 제목만 clause로 승격한다 — 마크다운·일반 문단 제목은 조항이 아니다.
_CLAUSE_HEADING_RE = re.compile(r"^(?:제\s?\d+\s?조|Article\s+\d+)")


@dataclass(frozen=True)
class Chunk:
    index: int
    content: str
    heading: str | None
    token_count: int
    # 조항 제목(`제48조(주택관리업자 선정방법)`). 인용 출처 줄에 조항 번호를 붙이는 값으로,
    # 규칙 1이 요구하는 "문서 조항 인용"의 근거다(prompt.build_context_block).
    clause: str | None = None


def _clean_heading(raw: str) -> str:
    heading = raw.lstrip("# ").strip()
    return re.sub(r"^\[(제\s?\d+\s?조)\]", r"\1", heading)  # `[제18조]` → `제18조`


def _boundaries(text: str) -> list[tuple[int, int, str]]:
    """(시작, 끝, 제목) 경계 목록 — 줄머리 제목 + 줄 중간 조항 제목."""
    found: list[tuple[int, int, str]] = []
    for m in _SECTION_RE.finditer(text):
        found.append((m.start(), m.end(), _clean_heading(m.group(0))))
    for m in _CLAUSE_ANYWHERE_RE.finditer(text):
        before = text[max(0, m.start() - _LEGAL_REF_LOOKBACK) : m.start()]
        if _LEGAL_REF_TAIL_RE.search(before):
            continue
        found.append((m.start(), m.end(), _clean_heading(m.group(0))))
    # 겹치는 경계는 먼저 시작하는 것, 같은 위치면 더 긴 것을 택한다(줄머리 매치가 표제까지 담는다).
    found.sort(key=lambda b: (b[0], -b[1]))
    merged: list[tuple[int, int, str]] = []
    for boundary in found:
        if merged and boundary[0] < merged[-1][1]:
            continue
        merged.append(boundary)
    return merged


def _split_sections(text: str) -> list[tuple[str | None, str]]:
    """(제목, 본문) 섹션 목록. 첫 경계 이전 텍스트는 제목 None."""
    sections: list[tuple[str | None, str]] = []
    marks = _boundaries(text)
    if not marks:
        return [(None, text)]
    if marks[0][0] > 0:
        sections.append((None, text[: marks[0][0]]))
    for i, (_, end_of_heading, heading) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        sections.append((heading, text[end_of_heading:end]))
    return sections


def _split_oversized(paragraph: str, max_tokens: int) -> list[str]:
    """상한 초과 문단을 문장 단위로 분할(그래도 초과하는 단일 문장은 그대로 통과)."""
    if estimate_tokens(paragraph) <= max_tokens:
        return [paragraph]
    pieces: list[str] = []
    current = ""
    for sentence in _SENTENCE_SPLIT_RE.split(paragraph):
        if not sentence.strip():
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and estimate_tokens(candidate) > max_tokens:
            pieces.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, *, max_tokens: int = CHUNK_MAX_TOKENS) -> list[Chunk]:
    """텍스트를 구조 경계 우선으로 청킹. 빈 입력은 빈 목록."""
    chunks: list[Chunk] = []
    text = _TOC_LINE_RE.sub("", text)
    for heading, body in _split_sections(text):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        pieces: list[str] = []
        for paragraph in paragraphs:
            pieces.extend(_split_oversized(paragraph, max_tokens))

        current = ""
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if current and estimate_tokens(candidate) > max_tokens:
                chunks.append(_make_chunk(len(chunks), current, heading))
                current = piece
            else:
                current = candidate
        if current:
            chunks.append(_make_chunk(len(chunks), current, heading))
    return chunks


def _make_chunk(index: int, content: str, heading: str | None) -> Chunk:
    body = f"{heading}\n{content}" if heading else content
    clause = heading if heading and _CLAUSE_HEADING_RE.match(heading) else None
    return Chunk(
        index=index,
        content=body,
        heading=heading,
        token_count=estimate_tokens(body),
        clause=clause,
    )
