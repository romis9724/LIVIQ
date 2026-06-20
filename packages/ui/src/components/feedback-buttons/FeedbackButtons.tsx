"use client";

import { useState } from "react";
import { cx } from "../../lib/cx";

export type FeedbackVote = "up" | "down" | null;

export interface FeedbackButtonsProps {
  /** 비제어 초기값. */
  defaultValue?: FeedbackVote;
  /** 투표 변경 콜백 (품질 신호 수집). */
  onVote?: (vote: FeedbackVote) => void;
  className?: string;
}

/** 답변 품질 신호(👍/👎) 수집 버튼. 같은 버튼 재클릭 시 해제된다. */
export function FeedbackButtons({ defaultValue = null, onVote, className }: FeedbackButtonsProps) {
  const [vote, setVote] = useState<FeedbackVote>(defaultValue);

  const choose = (next: Exclude<FeedbackVote, null>) => {
    const value = vote === next ? null : next;
    setVote(value);
    onVote?.(value);
  };

  return (
    <div className={cx("feedback", className)}>
      <button
        type="button"
        className="feedback-btn feedback-btn--up"
        aria-pressed={vote === "up"}
        aria-label="도움이 됐어요"
        onClick={() => choose("up")}
      >
        <span aria-hidden="true">👍</span> 도움돼요
      </button>
      <button
        type="button"
        className="feedback-btn feedback-btn--down"
        aria-pressed={vote === "down"}
        aria-label="아쉬워요"
        onClick={() => choose("down")}
      >
        <span aria-hidden="true">👎</span> 아쉬워요
      </button>
    </div>
  );
}
