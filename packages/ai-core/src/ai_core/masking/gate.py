"""LLM 경계 최종 게이트 — 마스킹 후 잔존 PII 재스캔 (규칙 2, fail-closed).

마스킹 수행 → 결과를 다시 스캔 → 잔존 PII가 검출되면 `MaskingFailedError`.
예외 = LLM 호출 중단이며, 상위(오케스트레이터)가 잡아 담당자 연결 폴백으로 전환한다.
게이트를 우회하는 LLM 호출 경로를 만들지 말 것.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_core.masking import masker
from ai_core.masking.masker import MaskResult


class MaskingFailedError(Exception):
    """마스킹 후에도 PII 잔존 — LLM 호출 금지(fail-closed)."""


def ensure_masked(text: str, *, extra_names: Sequence[str] = ()) -> MaskResult:
    """마스킹 + 잔존 재스캔. 통과 시 MaskResult, 실패 시 MaskingFailedError."""
    result = masker.mask(text, extra_names=extra_names)
    residual = masker.detect_pii(result.masked_text)
    if residual:
        raise MaskingFailedError(f"마스킹 후 PII 잔존: {sorted(residual)}")
    for name in extra_names:
        if name and name in result.masked_text:
            raise MaskingFailedError("마스킹 후 이름 잔존")
    return result
