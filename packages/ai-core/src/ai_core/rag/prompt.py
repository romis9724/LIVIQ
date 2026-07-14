"""프롬프트 빌더 — 출처 강제·간결 응답 (규칙 1, docs/08 §2.3·§5).

시스템 프롬프트는 캐시 가능한 공통 접두부로 고정하고, 변동부(근거·질문)는 뒤에 둔다.
근거에는 [n] 번호를 붙여 LLM이 인용하게 하고, 후처리에서 [n] 실재를 검증한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai_core.rag.retrieval import RetrievedChunk

# 공통 접두부 — 프롬프트 캐시 대상. 변경은 골든셋 회귀 평가 후(docs/07 §5).
SYSTEM_PROMPT = """당신은 아파트 관리사무소의 AI 도우미입니다. 규칙:
1. 아래 [근거]에 있는 내용만으로 답하십시오. 근거에 없는 내용은 절대 지어내지 마십시오.
2. 답변에 사용한 근거는 반드시 해당 문장 끝에 [번호] 형식으로 인용하십시오.
3. 근거로 답할 수 없으면 정확히 "NO_EVIDENCE"라고만 답하십시오.
4. 간결하게 답하십시오(불필요한 서론·반복 금지).
5. 한국어로 답하십시오."""

NO_EVIDENCE_MARKER = "NO_EVIDENCE"


def build_context_block(chunks: Sequence[RetrievedChunk]) -> str:
    """[n] 번호가 붙은 근거 블록. 번호는 1부터, 순서는 입력 순서(점수순) 유지."""
    lines = []
    for i, chunk in enumerate(chunks, start=1):
        source = chunk.document_title
        if chunk.clause:
            source += f" {chunk.clause}"
        if chunk.page is not None:
            source += f" p.{chunk.page}"
        lines.append(f"[{i}] ({source})\n{chunk.content}")
    return "\n\n".join(lines)


def build_user_message(question: str, chunks: Sequence[RetrievedChunk]) -> str:
    return f"[근거]\n{build_context_block(chunks)}\n\n[질문]\n{question}"
