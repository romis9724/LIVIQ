/**
 * 답변 본문의 최소 마크다운 처리 (H18-4).
 *
 * 프롬프트는 "목록은 `- ` 줄로만, 다른 기호 금지"로 못 박았지만(prompt.py 규칙 4) 8B는 샌다 —
 * H18-3 실측에서 `*`·`**`가 화면에 리터럴로 보였다. 그래서 프론트가 마지막 방어선이다.
 *
 * 하는 일은 둘뿐이다:
 *   1. 글머리 줄(`- `·`* `·`• `) 연속 → 목록 블록, 나머지 → 문단 블록
 *   2. 남은 강조 기호(`**굵게**`·`*기울임*`·`` `코드` ``·`#` 제목)는 **표시에서 벗긴다**
 *
 * 마크다운 라이브러리를 넣지 않는 이유: 부분 지원은 깨진 화면을 만든다. 렌더는 React
 * 엘리먼트로만 한다 — `dangerouslySetInnerHTML`은 쓰지 않는다(XSS).
 */

export type AnswerBlock =
  | { kind: "p"; text: string }
  | { kind: "ul"; items: string[] };

/** 글머리 줄. 프롬프트는 `- `만 요구하지만 모델이 `*`·`•`도 쓴다 — 셋 다 목록으로 본다. */
const BULLET_RE = /^\s*[-*•]\s+(.*)$/;
/** 제목 표기(`## 항목`) — 기호만 벗기고 본문은 문단으로 남긴다. */
const HEADING_RE = /^\s*#{1,6}\s+/;
/**
 * `**굵게**` — 안쪽에 `*`를 허용하지 않아 `****` 같은 기호 연속에는 걸리지 않는다.
 * 마스킹된 이름(`김*수`)을 훼손하지 않는 것이 이 정규식들의 제약 조건이다.
 */
const BOLD_RE = /\*\*(?=\S)([^*\n]+?)\*\*/g;
/** `*기울임*`·`_기울임_` — 여는 기호 앞이 공백/시작/여는괄호일 때만(`김*수`는 미매치). */
const EMPHASIS_RE = /(^|[\s([])[*_](?=\S)([^*_\n]+?)[*_](?=$|[\s).,!?\]])/g;
/** `` `코드` `` — 백틱은 이 도메인 평문에 나올 일이 없어 짝만 맞으면 벗긴다. */
const CODE_RE = /`([^`\n]+)`/g;
/**
 * 인용 마커 `[1]`·`[1][2]`·`[1, 2]` — 서버 텍스트에는 남긴다(검증·측정이 [n]을 본다).
 * **표시에서만** 벗긴다(사용자 지적 — 출처는 위 SourceStrip 카드가 이미 보여준다).
 * 숫자만 매치하므로 날짜·호수 표기 `[별관]` 같은 텍스트 대괄호에는 걸리지 않고,
 * 스트리밍 중 미완성 `[1`은 다음 청크에서 완성된 뒤 벗겨진다.
 */
const CITATION_MARKER_RE = /\s*\[\d+(?:\s*,\s*\d+)*\]/g;
/**
 * 프롬프트 내부 섹션 라벨 — 모델(특히 qwen3)이 답변에 그대로 따라 그리는 에코(사용자 지적).
 * 서버 프롬프트(`ai_core/rag/prompt.py`)의 근거 구획 이름이라 입주민에게는 무의미한 내부 용어다.
 * 인용 마커와 같은 원칙으로 **표시에서만** 벗긴다.
 */
const INTERNAL_LABEL_RE = /\[(?:문서 근거|확정 데이터·?도구 결과|확정 데이터|도구 결과)\]\s*/g;

/** 한 줄에서 강조 기호·인용 마커·내부 라벨만 제거. 텍스트 내용은 바꾸지 않는다. */
export function stripMarkers(line: string): string {
  return line
    .replace(HEADING_RE, "")
    .replace(BOLD_RE, "$1")
    .replace(EMPHASIS_RE, "$1$2")
    .replace(CODE_RE, "$1")
    .replace(CITATION_MARKER_RE, "")
    .replace(INTERNAL_LABEL_RE, "")
    .trimEnd();
}

/**
 * 답변 본문 → 렌더 블록. 빈 줄은 문단 경계, 연속 글머리 줄은 하나의 목록.
 * 스트리밍 중 잘린 텍스트에도 안전하다(짝이 안 맞는 기호는 그대로 남는다 — 다음 청크에서 완성).
 */
export function answerBlocks(text: string): AnswerBlock[] {
  const blocks: AnswerBlock[] = [];
  let paragraph: string[] = [];
  let items: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) blocks.push({ kind: "p", text: paragraph.join("\n") });
    paragraph = [];
  };
  const flushList = () => {
    if (items.length > 0) blocks.push({ kind: "ul", items });
    items = [];
  };

  for (const raw of text.split("\n")) {
    const bullet = BULLET_RE.exec(raw);
    if (bullet) {
      flushParagraph();
      const item = stripMarkers(bullet[1] ?? "").trim();
      if (item) items.push(item);
      continue;
    }
    const line = stripMarkers(raw).trim();
    if (!line) {
      flushList();
      flushParagraph();
      continue;
    }
    flushList();
    paragraph.push(line);
  }
  flushList();
  flushParagraph();
  return blocks;
}
