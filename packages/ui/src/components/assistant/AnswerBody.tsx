import type { ReactNode } from "react";

import { CitationMark } from "./CitationMark";
import type { AssistantCitation } from "./assistant-events";
import { answerSegmentBlocks, type AnswerSegment } from "./assistant-markdown";

/**
 * 답변 본문 — 문단·목록만 렌더한다(assistant-markdown.ts). 마크다운 라이브러리도
 * `dangerouslySetInnerHTML` 도 쓰지 않는다: 모델 출력은 신뢰 경계 밖이다(XSS).
 *
 * `citations` 를 주면 본문의 `[n]` 마커가 인라인 출처 배지(툴팁)로 렌더된다(H20-4).
 * 대응하는 citation 이 없는 번호(스트리밍 초반·모델 오기입)는 기존대로 표시에서 벗긴다.
 */
export function AnswerBody({
  text,
  citations,
}: {
  text: string;
  citations?: readonly AssistantCitation[];
}) {
  const byRef = new Map((citations ?? []).map((c) => [c.ref, c]));

  const renderSegments = (segments: AnswerSegment[]): ReactNode =>
    segments.map((seg, i) => (
      <span key={`s-${i}`}>
        {seg.text}
        {seg.refs
          .map((ref) => byRef.get(ref))
          .filter((c): c is AssistantCitation => c !== undefined)
          .map((c, j) => (
            <CitationMark key={`c-${c.ref}-${j}`} citation={c} />
          ))}
      </span>
    ));

  return (
    <>
      {answerSegmentBlocks(text).map((block, i) =>
        block.kind === "ul" ? (
          <ul key={`ul-${i}`} className="answer-list">
            {block.items.map((item, j) => (
              <li key={`li-${j}`}>{renderSegments(item)}</li>
            ))}
          </ul>
        ) : (
          <p key={`p-${i}`} className="answer-text">
            {renderSegments(block.segments)}
          </p>
        ),
      )}
    </>
  );
}
