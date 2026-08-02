/**
 * 답변 과정 — 기본 접힘. `<details>` 를 쓰는 이유: 키보드 열고 닫기·스크린리더 상태 노출을
 * 브라우저가 공짜로 해준다(자체 토글 상태·aria-expanded 를 만들 이유가 없다).
 */
export function ProgressSteps({ steps }: { steps: readonly string[] }) {
  if (steps.length === 0) return null;
  return (
    <details className="ai-steps">
      <summary className="ai-steps__summary">답변 과정 {steps.length}단계</summary>
      <ol className="ai-steps__list">
        {steps.map((step, i) => (
          <li key={`${i}-${step}`}>{step}</li>
        ))}
      </ol>
    </details>
  );
}
