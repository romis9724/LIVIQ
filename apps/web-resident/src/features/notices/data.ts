// 공지 목록·상세 순수 로직 — 날짜 포맷·본문 문단 분리. 테스트 대상.

/** ISO → "YYYY.MM.DD". 잘못된 값·null 은 빈 문자열. */
export function formatDate(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}.${mm}.${dd}`;
}

/** 본문을 빈 줄 기준으로 문단 배열로 분리(문단 내 줄바꿈은 pre-line 으로 유지). */
export function toParagraphs(body: string): string[] {
  return body
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter((p) => p.length > 0);
}

const SIZE_UNITS = ["KB", "MB", "GB", "TB"] as const;
const BYTES_PER_UNIT = 1024;

/** 바이트 → 사람이 읽는 크기(예: 940B · 1.2KB · 3.4MB). 1024 단위, 음수·비정상은 0B. */
export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0B";
  if (bytes < BYTES_PER_UNIT) return `${bytes}B`;
  let size = bytes / BYTES_PER_UNIT;
  let unit = 0;
  while (size >= BYTES_PER_UNIT && unit < SIZE_UNITS.length - 1) {
    size /= BYTES_PER_UNIT;
    unit += 1;
  }
  return `${size.toFixed(1)}${SIZE_UNITS[unit]}`;
}
