"""PII 마스킹/가명화 (ADR-0002 — LLM 경계 전 필수, self-hosted 포함).

정규식 기반 한국 PII 탐지 + 결정적 치환(동일 원문=동일 플레이스홀더).
이름은 정규식으로 일반 탐지가 불가능하다 — 호출자가 아는 이름 목록(`extra_names`:
로그인 사용자·대화 참여자·명부 대조 결과)을 정확 치환하는 MVP 방식이며,
자유 텍스트 속 미지의 인명은 커버하지 못한다(NER 도입은 후속 과제).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

# 우선순위 순서(먼저 매칭한 패턴이 승리 — 주민번호가 전화번호보다 먼저).
# 패턴은 단순·명확 우선, 오탐(일반 숫자·날짜) 억제는 테스트로 고정한다.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # 주민등록번호: 6자리-7자리(뒤 첫 자리 1~4)
    ("RRN", re.compile(r"\b\d{6}[-\s]?[1-4]\d{6}\b")),
    # 휴대폰·지역번호(구분자 있는 형태) + 010 붙여쓰기
    (
        "PHONE",
        re.compile(r"\b(?:01[016789][-\s]?\d{3,4}[-\s]?\d{4}|0\d{1,2}-\d{3,4}-\d{4}|010\d{8})\b"),
    ),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # 생년월일: 구분자 형태는 항상, 8자리 붙여쓰기는 문맥(생년월일/생일) 있을 때만
    (
        "BIRTH",
        re.compile(
            r"\b(?:19|20)\d{2}[./-](?:0?[1-9]|1[0-2])[./-](?:0?[1-9]|[12]\d|3[01])\b"
            r"|(?:생년월일|생일)\s*[:：]?\s*(?:19|20)\d{6}\b"
        ),
    ),
    # 동·호수: `101동 302호`는 항상, `101-302`는 문맥(동호수/호수) 있을 때만
    (
        "UNIT",
        re.compile(
            r"\b\d{1,4}\s*동\s*\d{1,4}\s*호|(?:동호수|호수)\s*[:：]?\s*\d{1,4}\s*-\s*\d{1,4}"
        ),
    ),
    # 계좌번호: 문맥(계좌) 있을 때만(일반 숫자열 오탐 방지)
    ("ACCOUNT", re.compile(r"계좌(?:번호)?\s*[:：]?\s*\d[\d-]{8,18}\d")),
)

_NAME_KIND = "NAME"


@dataclass(frozen=True)
class MaskResult:
    masked_text: str
    replacements: Mapping[str, str]  # placeholder → 원문
    found_kinds: frozenset[str] = field(default_factory=frozenset)


def mask(text: str, *, extra_names: Sequence[str] = ()) -> MaskResult:
    """PII를 플레이스홀더(`<PII:PHONE:1>`)로 치환. 동일 원문=동일 토큰(결정적)."""
    replacements: dict[str, str] = {}
    assigned: dict[tuple[str, str], str] = {}  # (kind, 원문) → placeholder
    counters: dict[str, int] = {}
    masked = text

    def _placeholder(kind: str, original: str) -> str:
        key = (kind, original)
        if key not in assigned:
            counters[kind] = counters.get(kind, 0) + 1
            token = f"<PII:{kind}:{counters[kind]}>"
            assigned[key] = token
            replacements[token] = original
        return assigned[key]

    for kind, pattern in _PATTERNS:

        def _substitute(match: re.Match[str], k: str = kind) -> str:
            return _placeholder(k, match.group(0))

        masked = pattern.sub(_substitute, masked)

    # 이름: 긴 이름 먼저(부분 문자열 오치환 방지), 정확 문자열 치환
    for name in sorted({n for n in extra_names if n}, key=len, reverse=True):
        if name in masked:
            masked = masked.replace(name, _placeholder(_NAME_KIND, name))

    return MaskResult(
        masked_text=masked,
        replacements=replacements,
        found_kinds=frozenset(kind for kind, _ in assigned),
    )


def detect_pii(text: str) -> frozenset[str]:
    """탐지만 수행(치환 없음) — 게이트의 잔존 재스캔용."""
    return frozenset(kind for kind, pattern in _PATTERNS if pattern.search(text))


def unmask(text: str, replacements: Mapping[str, str]) -> str:
    """플레이스홀더를 원문으로 복원(도구 결과 표시 등 내부 사용)."""
    restored = text
    for token, original in replacements.items():
        restored = restored.replace(token, original)
    return restored
