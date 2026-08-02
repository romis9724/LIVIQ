"use client";

import { useState } from "react";

import { cx } from "../../lib/cx";
import type { AssistantCitation } from "./assistant-events";
import { citationDetail } from "./assistant-sources";

/**
 * 답변 본문의 인라인 출처 배지(H20-4) — `[n]` 마커 자리에 뜨는 번호 버튼.
 * 호버·키보드 포커스는 CSS 로, 탭(모바일)은 클릭 토글로 툴팁을 연다.
 * 툴팁 내용은 서버 citation 이벤트가 보낸 확정값 그대로다(제목·조항·인용문 — 규칙 1).
 */
export function CitationMark({ citation }: { citation: AssistantCitation }) {
  const [open, setOpen] = useState(false);
  const detail = citationDetail(citation);
  return (
    <span className={cx("cite", open && "cite--open")}>
      <button
        type="button"
        className="cite__badge"
        aria-label={`출처 ${citation.ref}: ${citation.documentTitle}`}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        onBlur={() => setOpen(false)}
      >
        {citation.ref}
      </button>
      <span className="cite__tip" role="tooltip">
        <span className="cite__tip-title">{citation.documentTitle}</span>
        {detail ? <span className="cite__tip-meta">{detail}</span> : null}
        {citation.quote ? <span className="cite__tip-quote">{citation.quote}</span> : null}
      </span>
    </span>
  );
}
