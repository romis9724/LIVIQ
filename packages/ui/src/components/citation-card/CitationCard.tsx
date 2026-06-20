import { cx } from "../../lib/cx";

export interface CitationCardProps {
  /** 문서명·조항 (예: "관리규약 제32조 (공사 시간 제한)") */
  title: string;
  /** 페이지·개정 정보 (예: "12페이지 · 2024.03 개정본") */
  meta?: string;
  /** 원문 링크 */
  href: string;
  className?: string;
}

/**
 * 출처 카드 — 모든 AI 답변에 항상 동반된다(출처 없는 답변 금지의 UI 표현).
 */
export function CitationCard({ title, meta, href, className }: CitationCardProps) {
  return (
    <div className={cx("citation-card", className)}>
      <div className="citation-card__head">
        <span className="citation-card__badge" aria-hidden="true">
          📄
        </span>
        <span className="citation-card__label">출처</span>
      </div>
      <div className="citation-card__title">{title}</div>
      {meta ? <div className="citation-card__meta">{meta}</div> : null}
      <a className="citation-card__link" href={href}>
        원문 보기 <span aria-hidden="true">→</span>
      </a>
    </div>
  );
}
