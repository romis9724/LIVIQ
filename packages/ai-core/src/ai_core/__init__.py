"""LIVIQ ai-core — RAG·오케스트레이션·LLM 어댑터·토큰예산 (프레임워크 비의존).

H1-1: llm(OpenAI-호환 클라이언트)·masking(fail-closed 게이트)·budget(컨텍스트 예산).
orchestrator·rag·agent·cache는 후속 단계에서 채운다(docs/02 §5).
"""

from ai_core.budget import ScoredChunk, budget_for_model, fit_chunks
from ai_core.config import AiCoreSettings, get_settings
from ai_core.llm import (
    ChatResponse,
    ChatUsage,
    LlmClient,
    LlmError,
    LlmUnavailableError,
    estimate_tokens,
)
from ai_core.masking import MaskingFailedError, MaskResult, ensure_masked, mask, unmask

__version__ = "0.1.0"

__all__ = [
    "AiCoreSettings",
    "ChatResponse",
    "ChatUsage",
    "LlmClient",
    "LlmError",
    "LlmUnavailableError",
    "MaskResult",
    "MaskingFailedError",
    "ScoredChunk",
    "budget_for_model",
    "ensure_masked",
    "estimate_tokens",
    "fit_chunks",
    "get_settings",
    "mask",
    "unmask",
]
