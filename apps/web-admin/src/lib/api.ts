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

// ── 공지 초안·발행 (docs/01 §13, 규칙 6 — 발송은 사람 확정) ────────────────────

export interface NoticeCitation {
  documentId: string;
  documentTitle: string;
  chunkId: string;
  quote: string;
}

export interface NoticeDraft {
  draftId: string;
  title: string;
  body: string;
  citations: NoticeCitation[];
  confidence: number;
}

export interface PublishNoticeInput {
  draftId: string;
  title: string;
  body: string;
}

interface RawCitation {
  document_id: string;
  document_title: string;
  chunk_id: string;
  quote: string;
}

interface RawDraft {
  draft_id: string;
  title: string;
  body: string;
  citations: RawCitation[];
  confidence: number;
}

function toDraft(raw: RawDraft): NoticeDraft {
  return {
    draftId: raw.draft_id,
    title: raw.title,
    body: raw.body,
    citations: raw.citations.map((c) => ({
      documentId: c.document_id,
      documentTitle: c.document_title,
      chunkId: c.chunk_id,
      quote: c.quote,
    })),
    confidence: raw.confidence,
  };
}

/** 키워드에서 AI 초안 생성. 422=근거 없음·503=LLM 불가는 ApiError.status 로 분기. */
export async function createNoticeDraft(keywords: string[]): Promise<NoticeDraft> {
  const response = await fetch(`${API_BASE_URL}/admin/notices/drafts`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ keywords }),
  });
  await ensureOk(response);
  return toDraft(await response.json());
}

/** 검수 완료한 초안을 발행(사람 확정). audience 는 현재 ALL 만. 409=이미 처리된 초안. */
export async function publishNotice(input: PublishNoticeInput): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/admin/notices`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      draft_id: input.draftId,
      title: input.title,
      body: input.body,
      audience: "ALL",
    }),
  });
  await ensureOk(response);
}

// ── 관리비 (docs/01 §13, 규칙 5 — 엑셀이 단일 출처·표시 전용) ──────────────────

export type FeeUploadStatus = "validated" | "failed";

export interface FeeRowError {
  row: number;
  reason: string;
}

export interface FeePreviewRow {
  buildingName: string;
  floor: number;
  unitNo: number;
  breakdown: Record<string, number>;
  total: number;
}

export interface FeeUploadResult {
  uploadId: string;
  status: FeeUploadStatus;
  period: string;
  rowCount: number;
  validRows: number;
  errors: FeeRowError[];
  preview: FeePreviewRow[];
}

export interface FeeApplyResult {
  uploadId: string;
  status: string;
  period: string;
  applied: number;
}

export interface AdminFeeRow {
  householdId: string;
  buildingName: string;
  floor: number;
  unitNo: number;
  total: number;
}

export interface AdminFeeList {
  period: string;
  households: AdminFeeRow[];
  totalSum: number;
  householdCount: number;
}

interface RawFeeUpload {
  upload_id: string;
  status: FeeUploadStatus;
  period: string;
  row_count: number;
  valid_rows: number;
  errors: FeeRowError[];
  preview: {
    building_name: string;
    floor: number;
    unit_no: number;
    breakdown: Record<string, number>;
    total: number;
  }[];
}

function toFeeUpload(raw: RawFeeUpload): FeeUploadResult {
  return {
    uploadId: raw.upload_id,
    status: raw.status,
    period: raw.period,
    rowCount: raw.row_count,
    validRows: raw.valid_rows,
    errors: raw.errors,
    preview: raw.preview.map((p) => ({
      buildingName: p.building_name,
      floor: p.floor,
      unitNo: p.unit_no,
      breakdown: p.breakdown,
      total: p.total,
    })),
  };
}

/** 관리비 엑셀 업로드·검증(저장은 apply까지 미반영). 413=용량초과·422=형식오류. */
export async function uploadFeeExcel(file: File, period: string): Promise<FeeUploadResult> {
  const form = new FormData();
  form.set("file", file);
  const response = await fetch(
    `${API_BASE_URL}/admin/fees/uploads?period=${encodeURIComponent(period)}`,
    { method: "POST", headers: DEV_HEADERS, body: form },
  );
  await ensureOk(response);
  return toFeeUpload(await response.json());
}

/** 검증된 업로드를 확정 적재(해당 월 전체 교체·MANAGER). 409=validated 아님. */
export async function applyFeeUpload(uploadId: string): Promise<FeeApplyResult> {
  const response = await fetch(`${API_BASE_URL}/admin/fees/uploads/${uploadId}/apply`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return {
    uploadId: body.upload_id,
    status: body.status,
    period: body.period,
    applied: body.applied,
  };
}

/** 월별 세대 부과 현황(관리자). */
export async function listAdminFees(period: string): Promise<AdminFeeList> {
  const response = await fetch(
    `${API_BASE_URL}/admin/fees?period=${encodeURIComponent(period)}`,
    { headers: DEV_HEADERS },
  );
  await ensureOk(response);
  const body = await response.json();
  return {
    period: body.period,
    households: (body.households as {
      household_id: string;
      building_name: string;
      floor: number;
      unit_no: number;
      total: number;
    }[]).map((h) => ({
      householdId: h.household_id,
      buildingName: h.building_name,
      floor: h.floor,
      unitNo: h.unit_no,
      total: h.total,
    })),
    totalSum: body.total_sum,
    householdCount: body.household_count,
  };
}
