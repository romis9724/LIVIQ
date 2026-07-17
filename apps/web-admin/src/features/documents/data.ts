import type { DocumentItem, IndexStatus, SourceType, Visibility } from "@/lib/api";

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
  COUNCIL: { icon: "👥", label: "입대의" },
};

export const SOURCE_TYPES: readonly SourceType[] = ["규약", "회의록", "공지", "지침", "매뉴얼"];
export const VISIBILITIES: readonly Visibility[] = ["ALL", "RESIDENT", "ADMIN", "COUNCIL"];

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

/** ISO 문자열 → "MM/DD" 짧은 업로드 표기. */
export function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${mm}/${dd}`;
}
