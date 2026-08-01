import { cx } from "../../lib/cx";

export interface CitationCardProps {
  /** 문서명·조항 (예: "관리규약 제32조 (공사 시간 제한)") */
  title: string;
  /** 페이지·개정 정보 (예: "12페이지 · 2024.03 개정본") */
  meta?: string;
  className?: string;
}

/**
 * 출처 카드 — 모든 AI 답변에 항상 동반된다(출처 없는 답변 금지의 UI 표현).
 *
 * 원문 링크는 없다(H17 UI 정리). 문서 뷰어가 없어 모든 사용처가 `href="#"` 더미를 넘기고
 * 있었고, 눌러도 아무 일이 없는 링크가 카드 높이의 절반을 먹었다. 근거 표기는 제목·메타로 충분.
 *
 * "출처" 배지 줄도 뺐다(사용자 지적) — 카드가 놓이는 자리는 전부 이미 출처 영역이라
 * 같은 말이 두 번 나왔고, 그 줄이 카드 높이의 절반을 먹어 정작 제목이 좁아졌다. 시각
 * 표식은 📄 아이콘이 대신하고, 그 자리를 잃은 "출처"는 스크린리더용으로만 남긴다.
 */
export function CitationCard({ title, meta, className }: CitationCardProps) {
  return (
    <div className={cx("citation-card", className)}>
      <span className="citation-card__badge" aria-hidden="true">
        📄
      </span>
      <span className="sr-only">출처</span>
      <span className="citation-card__title">{title}</span>
      {meta ? <span className="citation-card__meta">{meta}</span> : null}
    </div>
  );
}
