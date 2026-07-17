// 문서 관리 — apps/api HTTP 클라이언트 (docs/01 §13).
// api-types 전환은 백로그 — 지금은 로컬 타입. dev 헤더 경로는 web-resident 와 동일 패턴.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// local dev 전용 컨텍스트(정식 세션 인증 도입 전). 시드된 tenant/user 와 일치해야 함.
// dev 헤더 경로는 roles=(RESIDENT,MANAGER,STAFF) 부여라 문서 관리(MANAGER·STAFF) 통과.
const DEV_TENANT_ID =
  process.env.NEXT_PUBLIC_DEV_TENANT_ID ?? "11111111-1111-1111-1111-111111111111";
// 배정 대상 사용자 목록 api 가 없어 "나에게 배정" 에 사용 — dev user 는 시드에서 MANAGER 역할 보유.
export const DEV_USER_ID =
  process.env.NEXT_PUBLIC_DEV_USER_ID ?? "22222222-2222-2222-2222-222222222222";

const DEV_HEADERS: Record<string, string> = {
  "X-Dev-Tenant-Id": DEV_TENANT_ID,
  "X-Dev-User-Id": DEV_USER_ID,
};

export type IndexStatus = "pending" | "indexing" | "indexed" | "failed";
export type SourceType = "규약" | "회의록" | "공지" | "지침" | "매뉴얼";
export type Visibility = "ALL" | "RESIDENT" | "ADMIN" | "COUNCIL";

export interface DocumentItem {
  id: string;
  title: string;
  sourceType: SourceType;
  visibility: Visibility;
  indexStatus: IndexStatus;
  createdAt: string;
}

export interface ListDocumentsParams {
  indexStatus?: IndexStatus;
  q?: string;
}

export interface UploadInput {
  file: File;
  title: string;
  sourceType: SourceType;
  visibility: Visibility;
}

export interface UploadResult {
  id: string;
  indexStatus: IndexStatus;
  duplicate: boolean;
}

export interface PatchInput {
  title?: string;
  visibility?: Visibility;
}

/** 상태코드를 담은 에러 — 화면에서 토스트/분기용. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** ListDocumentsParams → 쿼리스트링(빈 값 생략). 순수 함수 — 테스트 대상. */
export function buildListQuery(params: ListDocumentsParams): string {
  const search = new URLSearchParams();
  if (params.indexStatus) search.set("index_status", params.indexStatus);
  if (params.q && params.q.trim()) search.set("q", params.q.trim());
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

// api DocumentOut(snake_case) → DocumentItem(camelCase).
interface RawDocument {
  id: string;
  title: string;
  source_type: SourceType;
  visibility: Visibility;
  index_status: IndexStatus;
  created_at: string;
}

function toItem(raw: RawDocument): DocumentItem {
  return {
    id: raw.id,
    title: raw.title,
    sourceType: raw.source_type,
    visibility: raw.visibility,
    indexStatus: raw.index_status,
    createdAt: raw.created_at,
  };
}

async function ensureOk(response: Response): Promise<void> {
  if (response.ok) return;
  let detail = `요청 실패 (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // 본문 파싱 실패는 무시 — 상태코드 기반 기본 메시지 유지
  }
  throw new ApiError(response.status, detail);
}

export async function listDocuments(
  params: ListDocumentsParams = {},
): Promise<DocumentItem[]> {
  const response = await fetch(`${API_BASE_URL}/documents${buildListQuery(params)}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawDocument[]).map(toItem);
}

export async function uploadDocument(input: UploadInput): Promise<UploadResult> {
  const form = new FormData();
  form.set("file", input.file);
  form.set("title", input.title);
  form.set("source_type", input.sourceType);
  form.set("visibility", input.visibility);
  // Content-Type 는 브라우저가 multipart boundary 와 함께 설정 — 직접 지정하지 않음.
  const response = await fetch(`${API_BASE_URL}/documents`, {
    method: "POST",
    headers: DEV_HEADERS,
    body: form,
  });
  await ensureOk(response);
  const body = await response.json();
  return { id: body.id, indexStatus: body.index_status, duplicate: body.duplicate };
}

export async function patchDocument(
  id: string,
  input: PatchInput,
): Promise<DocumentItem> {
  const response = await fetch(`${API_BASE_URL}/documents/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  await ensureOk(response);
  return toItem(await response.json());
}

export async function reindexDocument(id: string): Promise<DocumentItem> {
  const response = await fetch(`${API_BASE_URL}/documents/${id}/reindex`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  return toItem(await response.json());
}

// ── 민원 관리 (docs/01 §13) ────────────────────────────────────────────────

export type InquiryStatus = "received" | "assigned" | "in_progress" | "done";
export type AiPriority = "urgent" | "normal" | "low";

export interface Inquiry {
  id: string;
  title: string;
  body: string;
  status: InquiryStatus;
  aiPriority: AiPriority | null;
  categoryId: string | null;
  aiSuggestedCategoryId: string | null;
  assigneeUserId: string | null;
  authorUserId: string;
  createdAt: string;
}

export interface AdminInquiryParams {
  status?: InquiryStatus;
  categoryId?: string;
}

interface RawInquiry {
  id: string;
  title: string;
  body: string;
  status: InquiryStatus;
  ai_priority: AiPriority | null;
  category_id: string | null;
  ai_suggested_category_id: string | null;
  assignee_user_id: string | null;
  author_user_id: string;
  created_at: string;
}

function toInquiry(raw: RawInquiry): Inquiry {
  return {
    id: raw.id,
    title: raw.title,
    body: raw.body,
    status: raw.status,
    aiPriority: raw.ai_priority,
    categoryId: raw.category_id,
    aiSuggestedCategoryId: raw.ai_suggested_category_id,
    assigneeUserId: raw.assignee_user_id,
    authorUserId: raw.author_user_id,
    createdAt: raw.created_at,
  };
}

/** AdminInquiryParams → 쿼리스트링(빈 값 생략). 순수 함수 — 테스트 대상. */
export function buildInquiryQuery(params: AdminInquiryParams): string {
  const search = new URLSearchParams();
  if (params.status) search.set("status", params.status);
  if (params.categoryId) search.set("category_id", params.categoryId);
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export async function listAdminInquiries(params: AdminInquiryParams = {}): Promise<Inquiry[]> {
  const response = await fetch(`${API_BASE_URL}/admin/inquiries${buildInquiryQuery(params)}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawInquiry[]).map(toInquiry);
}

export async function assignInquiry(id: string, assigneeUserId: string): Promise<Inquiry> {
  const response = await fetch(`${API_BASE_URL}/admin/inquiries/${id}/assign`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ assignee_user_id: assigneeUserId }),
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}

export async function updateInquiryStatus(id: string, status: InquiryStatus): Promise<Inquiry> {
  const response = await fetch(`${API_BASE_URL}/admin/inquiries/${id}/status`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}
