// 공지 게시판 순수 로직 — 상태 매핑·정렬·첨부 클라 검증·폼 검증. 테스트 대상.

import type { Notice, NoticeStatus } from "@/lib/api";

// 상태 표기 — 색만으로 전달하지 않고 아이콘·라벨 병기(WCAG 2.2 AA).
export const STATUS_META: Record<NoticeStatus, { label: string; css: string; icon: string }> = {
  draft: { label: "임시저장", css: "draft", icon: "✎" },
  scheduled: { label: "예약", css: "scheduled", icon: "🕑" },
  published: { label: "발행", css: "published", icon: "📢" },
};

// 작성 폼의 저장 방식 → status. 예약은 scheduledAt 필수.
export type SaveMode = "draft" | "published" | "scheduled";
export const SAVE_MODES: readonly { id: SaveMode; label: string; help: string }[] = [
  { id: "draft", label: "임시저장", help: "입주민에게 보이지 않습니다. 나중에 이어서 작성합니다." },
  { id: "published", label: "즉시 발행", help: "저장하는 즉시 입주민에게 공개됩니다." },
  { id: "scheduled", label: "예약 발행", help: "지정한 시각에 자동으로 공개됩니다." },
];

export const MAX_TITLE = 200;
export const MAX_BODY = 20000;

// 첨부 — api 계약과 일치(pdf·hwp·hwpx·docx·xlsx·jpg·jpeg·png · 20MB · 5개).
export const ALLOWED_ATTACHMENT_EXTENSIONS = [
  "pdf",
  "hwp",
  "hwpx",
  "docx",
  "xlsx",
  "jpg",
  "jpeg",
  "png",
] as const;
export const ATTACHMENT_ACCEPT = ".pdf,.hwp,.hwpx,.docx,.xlsx,.jpg,.jpeg,.png";
export const MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;
export const MAX_ATTACHMENTS = 5;

/** 파일명에서 소문자 확장자 추출. 확장자 없으면 빈 문자열. */
export function fileExtension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/** 첨부 사전 검증 — 개수 상한·허용 확장자·빈 파일·용량. 통과면 null. */
export function validateAttachment(
  file: { name: string; size: number },
  currentCount: number,
): string | null {
  if (currentCount >= MAX_ATTACHMENTS) {
    return `첨부는 공지당 최대 ${MAX_ATTACHMENTS}개까지 가능합니다.`;
  }
  const ext = fileExtension(file.name);
  if (!ALLOWED_ATTACHMENT_EXTENSIONS.includes(ext as (typeof ALLOWED_ATTACHMENT_EXTENSIONS)[number])) {
    return `허용하지 않는 형식입니다. (${ALLOWED_ATTACHMENT_EXTENSIONS.join(", ")})`;
  }
  if (file.size === 0) return "빈 파일은 첨부할 수 없습니다.";
  if (file.size > MAX_ATTACHMENT_BYTES) {
    return `파일당 최대 ${MAX_ATTACHMENT_BYTES / (1024 * 1024)}MB까지 첨부할 수 있습니다.`;
  }
  return null;
}

/** 바이트 → "1.2 MB" 등 사람이 읽는 용량. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(kb < 10 ? 1 : 0)} KB`;
  const mb = kb / 1024;
  return `${mb.toFixed(mb < 10 ? 1 : 0)} MB`;
}

/** 목록 정렬 — 고정 우선, 그다음 작성일 내림차순(서버 규칙과 동일, 방어적 재정렬). 불변. */
export function sortNotices(notices: readonly Notice[]): Notice[] {
  return [...notices].sort((a, b) => {
    if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
    return b.createdAt.localeCompare(a.createdAt);
  });
}

export interface NoticeFormValues {
  title: string;
  body: string;
  pinned: boolean;
  saveMode: SaveMode;
  scheduledAt: string; // datetime-local 값("YYYY-MM-DDTHH:mm"), 없으면 ""
}

export interface NoticeFormErrors {
  title?: string;
  body?: string;
  scheduledAt?: string;
}

/** 작성/수정 폼 검증 — 제목·본문 필수, 예약은 미래 시각 필수. now 주입으로 테스트 가능. */
export function validateNoticeForm(
  values: Pick<NoticeFormValues, "title" | "body" | "saveMode" | "scheduledAt">,
  now: number = Date.now(),
): NoticeFormErrors {
  const errors: NoticeFormErrors = {};
  const title = values.title.trim();
  if (!title) errors.title = "제목을 입력하세요.";
  else if (title.length > MAX_TITLE) errors.title = `제목은 ${MAX_TITLE}자 이하여야 합니다.`;

  const body = values.body.trim();
  if (!body) errors.body = "본문을 입력하세요.";
  else if (body.length > MAX_BODY) errors.body = `본문은 ${MAX_BODY}자 이하여야 합니다.`;

  if (values.saveMode === "scheduled") {
    if (!values.scheduledAt) {
      errors.scheduledAt = "예약 발행 시각을 지정하세요.";
    } else {
      const ts = new Date(values.scheduledAt).getTime();
      if (Number.isNaN(ts)) errors.scheduledAt = "올바른 시각을 지정하세요.";
      else if (ts <= now) errors.scheduledAt = "예약 시각은 현재보다 미래여야 합니다.";
    }
  }
  return errors;
}

export function hasErrors(errors: NoticeFormErrors): boolean {
  return Object.keys(errors).length > 0;
}

/** datetime-local 값(로컬) → ISO(UTC). 빈 값이면 null. */
export function localInputToIso(local: string): string | null {
  if (!local) return null;
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** ISO(UTC) → datetime-local 값("YYYY-MM-DDTHH:mm", 로컬). 없으면 "". */
export function isoToLocalInput(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** ISO → "YYYY.MM.DD". 없으면 대시. */
export function shortDate(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}.${pad(date.getMonth() + 1)}.${pad(date.getDate())}`;
}

/** ISO → "YYYY.MM.DD HH:mm". 없으면 대시. */
export function shortDateTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${shortDate(iso)} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
