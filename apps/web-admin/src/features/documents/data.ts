import { ApiError, type DocumentItem, type IndexStatus, type Visibility } from "@/lib/api";

// 색인 상태 표기 — 색만으로 전달하지 않고 아이콘·라벨 병기(WCAG 2.2 AA).
export const INDEX_META: Record<IndexStatus, { icon: string; label: string; spin?: boolean }> = {
  indexed: { icon: "✓", label: "색인 완료" },
  indexing: { icon: "↻", label: "색인 중", spin: true },
  pending: { icon: "•", label: "대기" },
  failed: { icon: "⚠", label: "색인 실패" },
};

export const VISIBILITY_META: Record<Visibility, { icon: string; label: string }> = {
  ALL: { icon: "🌐", label: "전체 공개" },
  RESIDENT: { icon: "🏠", label: "입주민" },
  ADMIN: { icon: "🔒", label: "관리자 전용" },
};

export const VISIBILITIES: readonly Visibility[] = ["ALL", "RESIDENT", "ADMIN"];

// 필터 탭 — "전체"는 상태 미지정.
export type StatusFilter = IndexStatus | "all";
export const STATUS_FILTERS: readonly { value: StatusFilter; label: string }[] = [
  { value: "all", label: "전체" },
  { value: "indexed", label: "완료" },
  { value: "indexing", label: "색인 중" },
  { value: "pending", label: "대기" },
  { value: "failed", label: "실패" },
];

export interface Summary {
  indexed: number;
  indexing: number;
  pending: number;
  failed: number;
}

/** 전체 목록에서 상태별 집계 — 필터 탭과 무관하게 항상 전체 기준. */
export function summarize(docs: readonly DocumentItem[]): Summary {
  const summary: Summary = { indexed: 0, indexing: 0, pending: 0, failed: 0 };
  for (const doc of docs) summary[doc.indexStatus] += 1;
  return summary;
}

/** 클라이언트 측 필터 — 상태 탭 + 제목 부분일치(대소문자 무시). */
export function filterDocs(
  docs: readonly DocumentItem[],
  status: StatusFilter,
  query: string,
): DocumentItem[] {
  const q = query.trim().toLowerCase();
  return docs.filter((doc) => {
    if (status !== "all" && doc.indexStatus !== status) return false;
    if (q && !doc.title.toLowerCase().includes(q)) return false;
    return true;
  });
}

/** 색인 미완(pending·indexing) 문서 존재 여부 — 폴링 지속 판단. */
export function hasActiveIndexing(docs: readonly DocumentItem[]): boolean {
  return docs.some((doc) => doc.indexStatus === "pending" || doc.indexStatus === "indexing");
}

/** ISO 문자열 → "YYYY.MM.DD" 표기(목록 수정일·버전 이력). 잘못된 값은 대시. */
export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const yy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yy}.${mm}.${dd}`;
}

// 첨부 화이트리스트 — api 파서 지원(.pdf/.txt/.md/.markdown)과 일치(ADR-0016, fail-closed).
export const ALLOWED_EXTENSIONS: readonly string[] = [".pdf", ".txt", ".md", ".markdown"];
export const FILE_ACCEPT = ALLOWED_EXTENSIONS.join(",");
export const MAX_FILE_MB = 20;
export const MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024;

/**
 * 첨부 파일 확장자·크기 클라 검증(서버가 최종 fail-closed). 통과 시 null, 실패 시 사용자 메시지.
 * File 뿐 아니라 { name, size } 로도 호출 가능 — 순수 함수(테스트 대상).
 */
export function validateAttachment(file: { name: string; size: number }): string | null {
  const name = file.name.toLowerCase();
  if (!ALLOWED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
    return `허용 형식(${ALLOWED_EXTENSIONS.join(", ")})만 업로드할 수 있습니다.`;
  }
  if (file.size === 0) return "빈 파일은 업로드할 수 없습니다.";
  if (file.size > MAX_FILE_BYTES) return `파일이 최대 ${MAX_FILE_MB}MB를 초과합니다.`;
  return null;
}

/** 바이트 → 사람이 읽는 용량 문자열(B/KB/MB). 순수 함수(테스트 대상). */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`;
}

/** 문서 API 오류 → 사용자 친화 메시지. 409=중복·413=용량·422=형식/입력. */
export function documentErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 409:
        return "동일한 파일이 이미 등록되어 있습니다.";
      case 413:
        return `파일이 최대 ${MAX_FILE_MB}MB를 초과합니다.`;
      case 422:
        return err.message || "지원하지 않는 파일 형식이거나 입력이 올바르지 않습니다.";
      default:
        return err.message;
    }
  }
  if (err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}
