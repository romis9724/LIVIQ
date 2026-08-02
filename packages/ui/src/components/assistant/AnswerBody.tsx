import { answerBlocks } from "./assistant-markdown";

/**
 * 답변 본문 — 문단·목록만 렌더한다(assistant-markdown.ts). 마크다운 라이브러리도
 * `dangerouslySetInnerHTML` 도 쓰지 않는다: 모델 출력은 신뢰 경계 밖이다(XSS).
 */
export function AnswerBody({ text }: { text: string }) {
  return (
    <>
      {answerBlocks(text).map((block, i) =>
        block.kind === "ul" ? (
          <ul key={`ul-${i}`} className="answer-list">
            {block.items.map((item, j) => (
              <li key={`${j}-${item}`}>{item}</li>
            ))}
          </ul>
        ) : (
          <p key={`p-${i}`} className="answer-text">
            {block.text}
          </p>
        ),
      )}
    </>
  );
}
