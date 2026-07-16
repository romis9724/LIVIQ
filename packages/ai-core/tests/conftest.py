"""ai-core 테스트 공용 — 네트워크 금지, settings는 env 무관하게 직접 구성."""

from __future__ import annotations

import pytest

from ai_core.config import AiCoreSettings


@pytest.fixture
def settings() -> AiCoreSettings:
    return AiCoreSettings(  # type: ignore[call-arg]
        LLM_BASE_URL="http://llm.test/v1",
        LLM_MODEL="test-model",
        EMBEDDING_BASE_URL="http://embed.test/v1",
        EMBEDDING_MODEL="bge-m3",
    )
