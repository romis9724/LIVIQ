"""PII 마스킹/가명화 — LLM 경계 전 필수 게이트 (ADR-0002)."""

from ai_core.masking.gate import MaskingFailedError, ensure_masked
from ai_core.masking.masker import MaskResult, detect_pii, mask, unmask

__all__ = [
    "MaskResult",
    "MaskingFailedError",
    "detect_pii",
    "ensure_masked",
    "mask",
    "unmask",
]
