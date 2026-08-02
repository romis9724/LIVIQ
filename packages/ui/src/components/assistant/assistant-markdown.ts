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

/** 인용 마커를 **뺀** 나머지 기호 제거 — 인라인 배지 경로(H20-4)가 마커를 refs 로 살려 쓴다. */
function stripTextMarkers(line: string): string {
  return line
    .replace(HEADING_RE, "")
    .replace(BOLD_RE, "$1")
    .replace(EMPHASIS_RE, "$1$2")
    .replace(CODE_RE, "$1")
    .replace(INTERNAL_LABEL_RE, "")
    .trimEnd();
}

/** 한 줄에서 강조 기호·인용 마커·내부 라벨만 제거. 텍스트 내용은 바꾸지 않는다. */
export function stripMarkers(line: string): string {
  return stripTextMarkers(line).replace(CITATION_MARKER_RE, "").trimEnd();
}

/**
 * 텍스트 한 조각과 그 **직후에 붙은** 인용 번호들(H20-4 인라인 출처 배지).
 * refs 가 비면 그냥 텍스트다. 번호 순서는 모델 출력 순서를 유지한다.
 */
export interface AnswerSegment {
  text: string;
  refs: number[];
}

/** 인용 마커에서 번호를 뽑는 버전 — CITATION_MARKER_RE 와 같은 문법, 번호만 캡처. */
const CITATION_CAPTURE_RE = /\s*\[(\d+(?:\s*,\s*\d+)*)\]/g;

/** 한 줄 → 세그먼트. 마커가 없으면 세그먼트 1개(refs []). 빈 줄이면 []. */
function lineSegments(raw: string): AnswerSegment[] {
  const line = stripTextMarkers(raw).trim();
  const segments: AnswerSegment[] = [];
  let cursor = 0;
  for (const m of line.matchAll(CITATION_CAPTURE_RE)) {
    const refs = (m[1] ?? "").split(",").map((n) => Number(n.trim()));
    const text = line.slice(cursor, m.index).trimEnd();
    cursor = m.index + m[0].length;
    const prev = segments[segments.length - 1];
    // `[1][3]` 처럼 마커 사이에 텍스트가 없으면 앞 세그먼트의 refs 로 합친다.
    if (!text && prev) {
      segments[segments.length - 1] = { ...prev, refs: [...prev.refs, ...refs] };
      continue;
    }
    segments.push({ text, refs });
  }
  const rest = line.slice(cursor).trimEnd();
  if (rest) segments.push({ text: rest, refs: [] });
  // 마커만 있는 줄은 기존(빈 줄) 취급 — 텍스트 없는 배지는 앵커가 없다.
  return segments.every((s) => !s.text) ? [] : segments;
}

export type SegmentBlock =
  | { kind: "p"; segments: AnswerSegment[] }
  | { kind: "ul"; items: AnswerSegment[][] };

/**
 * 답변 본문 → 인라인 출처 배지용 블록. `answerBlocks` 와 같은 문단·목록 규칙이되
 * 인용 마커를 벗기는 대신 각 텍스트 조각의 refs 로 남긴다(H20-4).
 */
export function answerSegmentBlocks(text: string): SegmentBlock[] {
  const blocks: SegmentBlock[] = [];
  let paragraph: AnswerSegment[] = [];
  let items: AnswerSegment[][] = [];

  const flushParagraph = () => {
    if (paragraph.length > 0) blocks.push({ kind: "p", segments: paragraph });
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
      const segs = lineSegments(bullet[1] ?? "");
      if (segs.length > 0) items.push(segs);
      continue;
    }
    const segs = lineSegments(raw);
    if (segs.length === 0) {
      flushList();
      flushParagraph();
      continue;
    }
    flushList();
    // 문단 안의 줄바꿈은 첫 조각 앞에 남긴다 — 표시 텍스트가 기존 answerBlocks 와 같아진다.
    paragraph.push(
      ...(paragraph.length > 0 && segs[0]
        ? [{ ...segs[0], text: `\n${segs[0].text}` }, ...segs.slice(1)]
        : segs),
    );
  }
  flushList();
  flushParagraph();
  return blocks;
}

/** 세그먼트들의 표시 텍스트 — refs 를 버리면 기존 answerBlocks 표시와 같다. */
const segmentsText = (segments: AnswerSegment[]): string =>
  segments.map((s) => s.text).join("");

/**
 * 답변 본문 → 렌더 블록. 빈 줄은 문단 경계, 연속 글머리 줄은 하나의 목록.
 * 스트리밍 중 잘린 텍스트에도 안전하다(짝이 안 맞는 기호는 그대로 남는다 — 다음 청크에서 완성).
 * `answerSegmentBlocks` 의 파생 — 인용 마커(refs)만 버린다.
 */
export function answerBlocks(text: string): AnswerBlock[] {
  return answerSegmentBlocks(text).map((b) =>
    b.kind === "ul"
      ? { kind: "ul", items: b.items.map(segmentsText) }
      : { kind: "p", text: segmentsText(b.segments) },
  );
}
