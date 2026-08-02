"use client";

export interface SuggestionChipsProps {
  chips: readonly string[];
  /** 칩 문구를 그대로 새 질문으로 보낸다. */
  onAsk: (question: string) => void;
}

/** 맥락 기반 후속 질문 칩 — 누르면 그 문구로 새 질문을 보낸다. 비면 아무것도 렌더하지 않는다. */
export function SuggestionChips({ chips, onAsk }: SuggestionChipsProps) {
  if (chips.length === 0) return null;
  return (
    <nav className="ai-chips" aria-label="이어서 물어보기">
      {chips.map((chip) => (
        <button key={chip} type="button" className="ai-chip" onClick={() => onAsk(chip)}>
          {chip}
        </button>
      ))}
    </nav>
  );
}
