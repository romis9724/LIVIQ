"""토크나이저 비의존 토큰 수 추정.

정확한 토크나이저는 모델마다 다르므로(qwen·llama·bge 등) 예산 계산용 **추정치**만 제공한다.
근사 규칙: 한글·CJK ≈ 문자당 1토큰, 그 외(라틴·숫자·공백) ≈ 4자당 1토큰.
과소 추정보다 과대 추정이 안전하다(예산 초과 방지) — 올림 처리.
"""

from __future__ import annotations

import math

# CJK 근사 범위: 한글 음절·자모, 한중일 통합 한자, 가나
_CJK_RANGES = (
    (0xAC00, 0xD7A3),  # 한글 음절
    (0x1100, 0x11FF),  # 한글 자모
    (0x3130, 0x318F),  # 호환 자모
    (0x4E00, 0x9FFF),  # CJK 통합 한자
    (0x3040, 0x30FF),  # 히라가나·가타카나
)

LATIN_CHARS_PER_TOKEN = 4


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return any(lo <= code <= hi for lo, hi in _CJK_RANGES)


def estimate_tokens(text: str) -> int:
    """텍스트의 토큰 수를 추정한다(예산 계산용 근사치)."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if _is_cjk(ch))
    other = len(text) - cjk
    return cjk + math.ceil(other / LATIN_CHARS_PER_TOKEN)
