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
      {/* 아이콘만 노출한다(글자 제거). 대신 aria-label 로 접근 가능한 이름을 남긴다 —
          이모지는 aria-hidden 이라 라벨이 없으면 스크린리더가 읽을 게 사라진다(WCAG 4.1.2).
          title 은 마우스 툴팁용. */}
      <button
        type="button"
        className="feedback-btn feedback-btn--up"
        aria-pressed={vote === "up"}
        aria-label="도움돼요"
        title="도움돼요"
        onClick={() => choose("up")}
      >
        <span aria-hidden="true">👍</span>
      </button>
      <button
        type="button"
        className="feedback-btn feedback-btn--down"
        aria-pressed={vote === "down"}
        aria-label="아쉬워요"
        title="아쉬워요"
        onClick={() => choose("down")}
      >
        <span aria-hidden="true">👎</span>
      </button>
    </div>
  );
}
