// 문서 관리 — apps/api HTTP 클라이언트 (docs/01 §13).
// api-types 전환은 백로그 — 지금은 로컬 타입. dev 헤더 경로는 web-resident 와 동일 패턴.

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// dev 헤더는 NEXT_PUBLIC_DEV_TENANT_ID가 설정된 local 편의 환경에서만 부착한다.
// 기본(미설정)은 세션 쿠키 인증만 사용 — api는 local에서만 dev 헤더를 허용(deps.get_context).
const DEV_TENANT_ID = process.env.NEXT_PUBLIC_DEV_TENANT_ID;
// 배정 대상 사용자 목록 api 가 없어 "나에게 배정" 에 사용 — 미설정 시 빈 문자열.
export const DEV_USER_ID = process.env.NEXT_PUBLIC_DEV_USER_ID ?? "";

export const DEV_HEADERS: Record<string, string> =
  DEV_TENANT_ID && DEV_USER_ID
    ? { "X-Dev-Tenant-Id": DEV_TENANT_ID, "X-Dev-User-Id": DEV_USER_ID }
    : {};

/**
 * 세션 쿠키를 실어 api를 호출하는 fetch 래퍼.
 * - credentials:"include" — 교차 출처(3001→8000) 세션 쿠키 전송(ADR-0011).
 * - DEV_HEADERS 병합(local 보조) + 호출자 헤더가 우선.
 * - 401(미인증·만료)이면 로그인 화면으로 유도(이미 /login이면 루프 방지).
 *   403(권한 없음)은 그대로 반환 — 화면이 ApiError로 안내(MANAGER 아닌 세션).
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const response = await fetch(input, {
    ...init,
    credentials: "include",
    headers: { ...DEV_HEADERS, ...(init.headers as Record<string, string> | undefined) },
  });
  if (
    response.status === 401 &&
    typeof window !== "undefined" &&
    window.location.pathname !== "/login"
  ) {
    window.location.href = "/login";
  }
  return response;
}

export type IndexStatus = "pending" | "indexing" | "indexed" | "failed";
export type SourceType = "규약" | "회의록" | "공지" | "지침" | "매뉴얼";
export type Visibility = "ALL" | "RESIDENT" | "ADMIN";

// 문서 게시판(ADR-0016): 게시글 = 제목 + 본문(설명) + 첨부 1개(버전 관리).
export interface DocumentItem {
  id: string;
  title: string;
  sourceType: SourceType;
  visibility: Visibility;
  body: string | null;
  version: number;
  indexStatus: IndexStatus;
  createdAt: string;
  updatedAt: string;
}

/** 첨부 버전 이력 항목(내림차순 — 서버 정렬). 다운로드는 documentDownloadUrl 로. */
export interface DocumentVersion {
  version: number;
  filename: string;
  contentType: string;
  sizeBytes: number;
  createdAt: string;
}

export interface DocumentDetail extends DocumentItem {
  versions: DocumentVersion[];
}

export interface ListDocumentsParams {
  indexStatus?: IndexStatus;
  q?: string;
}

/** 게시글 작성 — 첨부 1개 필수, 본문은 선택. */
export interface CreateDocumentInput {
  file: File;
  title: string;
  sourceType: SourceType;
  visibility: Visibility;
  body?: string;
}

/** 메타 수정 — 파일 교체는 uploadDocumentVersion 으로 분리(새 버전). */
export interface PatchDocumentInput {
  title?: string;
  body?: string;
  sourceType?: SourceType;
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
  body?: string | null;
  version: number;
  index_status: IndexStatus;
  created_at: string;
  updated_at: string;
}

interface RawVersion {
  version: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

function toItem(raw: RawDocument): DocumentItem {
  return {
    id: raw.id,
    title: raw.title,
    sourceType: raw.source_type,
    visibility: raw.visibility,
    body: raw.body ?? null,
    version: raw.version,
    indexStatus: raw.index_status,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

function toVersion(raw: RawVersion): DocumentVersion {
  return {
    version: raw.version,
    filename: raw.filename,
    contentType: raw.content_type,
    sizeBytes: raw.size_bytes,
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
  const response = await apiFetch(`${API_BASE_URL}/documents${buildListQuery(params)}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawDocument[]).map(toItem);
}

export async function getDocument(id: string): Promise<DocumentDetail> {
  const response = await apiFetch(`${API_BASE_URL}/documents/${id}`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const raw = await response.json();
  return {
    ...toItem(raw as RawDocument),
    versions: ((raw.versions as RawVersion[] | undefined) ?? []).map(toVersion),
  };
}

/** 게시글 작성 — 첨부 1개 필수(v1) + 인제스트 큐. 409=중복 파일·413=용량·422=형식. */
export async function createDocument(input: CreateDocumentInput): Promise<DocumentItem> {
  const form = new FormData();
  form.set("file", input.file);
  form.set("title", input.title);
  form.set("source_type", input.sourceType);
  form.set("visibility", input.visibility);
  if (input.body && input.body.trim()) form.set("body", input.body.trim());
  // Content-Type 는 브라우저가 multipart boundary 와 함께 설정 — 직접 지정하지 않음.
  const response = await apiFetch(`${API_BASE_URL}/documents`, {
    method: "POST",
    headers: DEV_HEADERS,
    body: form,
  });
  await ensureOk(response);
  return toItem(await response.json());
}

/** 메타(제목·본문·유형·공개범위) 수정. 파일은 변경하지 않는다. */
export async function patchDocument(
  id: string,
  input: PatchDocumentInput,
): Promise<DocumentItem> {
  const payload: Record<string, string> = {};
  if (input.title !== undefined) payload.title = input.title;
  if (input.body !== undefined) payload.body = input.body;
  if (input.sourceType !== undefined) payload.source_type = input.sourceType;
  if (input.visibility !== undefined) payload.visibility = input.visibility;
  const response = await apiFetch(`${API_BASE_URL}/documents/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await ensureOk(response);
  return toItem(await response.json());
}

/** 새 버전 업로드 — version+1 + 재인제스트(index_status=pending). 409=현재 버전과 동일. */
export async function uploadDocumentVersion(id: string, file: File): Promise<DocumentItem> {
  const form = new FormData();
  form.set("file", file);
  const response = await apiFetch(`${API_BASE_URL}/documents/${id}/file`, {
    method: "POST",
    headers: DEV_HEADERS,
    body: form,
  });
  await ensureOk(response);
  return toItem(await response.json());
}

/** 버전 파일 다운로드 URL — 세션 쿠키 동봉 최상위 GET이라 <a download>로 바로 쓴다(명부 양식 패턴). */
export function documentDownloadUrl(id: string, version: number): string {
  return `${API_BASE_URL}/documents/${id}/versions/${version}/download`;
}

/** 게시글 삭제 — soft delete + 청크 즉시 삭제(ADR-0016). 204. */
export async function deleteDocument(id: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/documents/${id}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

export async function reindexDocument(id: string): Promise<DocumentItem> {
  const response = await apiFetch(`${API_BASE_URL}/documents/${id}/reindex`, {
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
  const response = await apiFetch(`${API_BASE_URL}/admin/inquiries${buildInquiryQuery(params)}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawInquiry[]).map(toInquiry);
}

export async function assignInquiry(id: string, assigneeUserId: string): Promise<Inquiry> {
  const response = await apiFetch(`${API_BASE_URL}/admin/inquiries/${id}/assign`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ assignee_user_id: assigneeUserId }),
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}

export async function updateInquiryStatus(id: string, status: InquiryStatus): Promise<Inquiry> {
  const response = await apiFetch(`${API_BASE_URL}/admin/inquiries/${id}/status`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}

// ── 공지사항 게시판 (docs/01 §13 · H8-1, 규칙 6 — 발송은 사람 확정) ───────────────

export type NoticeStatus = "draft" | "scheduled" | "published";

export interface NoticeAttachment {
  id: string;
  filename: string;
  contentType: string;
  sizeBytes: number;
  createdAt: string;
}

export interface Notice {
  id: string;
  title: string;
  body: string;
  status: NoticeStatus;
  pinned: boolean;
  audience: string;
  scheduledAt: string | null;
  publishedAt: string | null;
  publishedBy: string | null;
  createdAt: string;
  updatedAt: string;
  attachments: NoticeAttachment[];
}

export interface NoticeCreateInput {
  title: string;
  body: string;
  status: NoticeStatus;
  pinned: boolean;
  scheduledAt?: string | null; // 예약(status=scheduled)일 때만 ISO 시각
}

export interface NoticePatchInput {
  title?: string;
  body?: string;
  pinned?: boolean;
  status?: NoticeStatus;
  scheduledAt?: string | null;
}

interface RawAttachment {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

interface RawNotice {
  id: string;
  title: string;
  body: string;
  status: NoticeStatus;
  pinned: boolean;
  audience: string;
  scheduled_at: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
  attachments: RawAttachment[];
}

function toAttachment(raw: RawAttachment): NoticeAttachment {
  return {
    id: raw.id,
    filename: raw.filename,
    contentType: raw.content_type,
    sizeBytes: raw.size_bytes,
    createdAt: raw.created_at,
  };
}

function toNotice(raw: RawNotice): Notice {
  return {
    id: raw.id,
    title: raw.title,
    body: raw.body,
    status: raw.status,
    pinned: raw.pinned,
    audience: raw.audience,
    scheduledAt: raw.scheduled_at,
    publishedAt: raw.published_at,
    publishedBy: raw.published_by,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
    attachments: (raw.attachments ?? []).map(toAttachment),
  };
}

/** 공지 목록(전 상태) — 서버가 고정 우선·작성일 내림차순으로 정렬해 반환. */
export async function listNotices(): Promise<Notice[]> {
  const response = await apiFetch(`${API_BASE_URL}/admin/notices`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawNotice[]).map(toNotice);
}

/** 공지 상세(첨부 포함). */
export async function getNotice(id: string): Promise<Notice> {
  const response = await apiFetch(`${API_BASE_URL}/admin/notices/${id}`, { headers: DEV_HEADERS });
  await ensureOk(response);
  return toNotice(await response.json());
}

/** 공지 작성 — audience 는 현재 ALL 고정. 422=예약 시각 누락/과거. */
export async function createNotice(input: NoticeCreateInput): Promise<Notice> {
  const response = await apiFetch(`${API_BASE_URL}/admin/notices`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      body: input.body,
      audience: "ALL",
      status: input.status,
      pinned: input.pinned,
      scheduled_at: input.scheduledAt ?? null,
    }),
  });
  await ensureOk(response);
  return toNotice(await response.json());
}

/** 공지 부분 수정. 409=발행된 공지를 초안·예약으로 역행 시도. */
export async function patchNotice(id: string, input: NoticePatchInput): Promise<Notice> {
  const body: Record<string, unknown> = {};
  if (input.title !== undefined) body.title = input.title;
  if (input.body !== undefined) body.body = input.body;
  if (input.pinned !== undefined) body.pinned = input.pinned;
  if (input.status !== undefined) body.status = input.status;
  if (input.scheduledAt !== undefined) body.scheduled_at = input.scheduledAt;
  const response = await apiFetch(`${API_BASE_URL}/admin/notices/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await ensureOk(response);
  return toNotice(await response.json());
}

/** 공지 삭제(soft delete). 204. */
export async function deleteNotice(id: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/notices/${id}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 첨부 업로드 — multipart(file). 413=용량 초과·422=개수 초과/빈 파일. */
export async function uploadNoticeAttachment(
  id: string,
  file: File,
): Promise<NoticeAttachment> {
  const form = new FormData();
  form.set("file", file);
  // Content-Type 은 브라우저가 multipart boundary 와 함께 설정 — 직접 지정하지 않음.
  const response = await apiFetch(`${API_BASE_URL}/admin/notices/${id}/attachments`, {
    method: "POST",
    headers: DEV_HEADERS,
    body: form,
  });
  await ensureOk(response);
  return toAttachment(await response.json());
}

/** 첨부 삭제. 204. */
export async function deleteNoticeAttachment(id: string, attachmentId: string): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/notices/${id}/attachments/${attachmentId}`,
    { method: "DELETE", headers: DEV_HEADERS },
  );
  await ensureOk(response);
}

/**
 * 첨부 다운로드 URL — published 공지에서만 유효(서버 계약). 세션 쿠키 동봉 최상위 GET이라
 * <a download>로 바로 쓴다(ROSTER_TEMPLATE_URL 과 동일 접근).
 */
export function noticeAttachmentDownloadUrl(id: string, attachmentId: string): string {
  return `${API_BASE_URL}/notices/${id}/attachments/${attachmentId}`;
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
  const response = await apiFetch(
    `${API_BASE_URL}/admin/fees/uploads?period=${encodeURIComponent(period)}`,
    { method: "POST", headers: DEV_HEADERS, body: form },
  );
  await ensureOk(response);
  return toFeeUpload(await response.json());
}

/** 검증된 업로드를 확정 적재(해당 월 전체 교체·MANAGER). 409=validated 아님. */
export async function applyFeeUpload(uploadId: string): Promise<FeeApplyResult> {
  const response = await apiFetch(`${API_BASE_URL}/admin/fees/uploads/${uploadId}/apply`, {
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
  const response = await apiFetch(
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

// ── AI 검수 큐 (docs/01 §13, 규칙 6 — 사후 검수·회수 없음) ─────────────────────

export type ReviewStatus = "needs_review" | "approved" | "rejected";
export type ReviewAction = "approve" | "reject";

export interface ReviewCitation {
  documentTitle: string | null;
  quote: string | null;
}

export interface ReviewItem {
  messageId: string;
  question: string | null;
  answer: string;
  confidence: number | null; // 0~1
  status: string | null; // answered|fallback|handed_off
  citations: ReviewCitation[];
  createdAt: string;
  reviewStatus: ReviewStatus;
  reviewedAt: string | null;
  reviewNote: string | null;
}

export interface ReviewList {
  items: ReviewItem[];
  total: number;
  page: number;
  limit: number;
}

interface RawReviewCitation {
  document_title: string | null;
  quote: string | null;
}

interface RawReviewItem {
  message_id: string;
  question: string | null;
  answer: string;
  confidence: number | null;
  status: string | null;
  citations: RawReviewCitation[];
  created_at: string;
  review_status: ReviewStatus;
  reviewed_at: string | null;
  review_note: string | null;
}

function toReviewItem(raw: RawReviewItem): ReviewItem {
  return {
    messageId: raw.message_id,
    question: raw.question,
    answer: raw.answer,
    confidence: raw.confidence,
    status: raw.status,
    citations: raw.citations.map((c) => ({
      documentTitle: c.document_title,
      quote: c.quote,
    })),
    createdAt: raw.created_at,
    reviewStatus: raw.review_status,
    reviewedAt: raw.reviewed_at,
    reviewNote: raw.review_note,
  };
}

export async function listReviewQueue(
  status: ReviewStatus = "needs_review",
  page = 1,
  limit = 20,
): Promise<ReviewList> {
  const search = new URLSearchParams({
    status,
    page: String(page),
    limit: String(limit),
  });
  const response = await apiFetch(`${API_BASE_URL}/admin/review-queue?${search.toString()}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return {
    items: (body.items as RawReviewItem[]).map(toReviewItem),
    total: body.total,
    page: body.page,
    limit: body.limit,
  };
}

/** 승인/반려 결정(MANAGER). 반려는 note 필수. 409=이미 처리됨·403=권한 없음. */
export async function decideReview(
  messageId: string,
  action: ReviewAction,
  note?: string,
): Promise<ReviewItem> {
  const response = await apiFetch(`${API_BASE_URL}/admin/review-queue/${messageId}/decide`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ action, note: note ?? null }),
  });
  await ensureOk(response);
  return toReviewItem(await response.json());
}

// ── 시설 관리 (docs/01 §13, 규칙 8 — 쓰기는 전부 사람 폼) ──────────────────────

export type FacilityStatus = "normal" | "check" | "fault" | "risk";

export interface Facility {
  id: string;
  name: string;
  location: string | null;
  type: string | null;
  status: FacilityStatus;
  nextCheckAt: string | null;
  createdAt: string;
}

export interface Incident {
  id: string;
  facilityId: string;
  occurredAt: string | null;
  symptom: string;
  resolution: string | null;
  rootCause: string | null;
  createdAt: string;
}

export interface MaintenanceLog {
  id: string;
  facilityId: string;
  performedAt: string | null;
  work: string;
  performer: string | null;
  parts: Record<string, unknown> | null;
  createdAt: string;
}

export interface FacilityDetail extends Facility {
  incidents: Incident[];
  maintenanceLogs: MaintenanceLog[];
}

export interface FacilityCreateInput {
  name: string;
  location?: string;
  type?: string;
  status: FacilityStatus;
}

export interface FacilityPatchInput {
  name?: string;
  location?: string;
  type?: string;
  status?: FacilityStatus;
}

export interface IncidentInput {
  symptom: string;
  resolution?: string;
  rootCause?: string;
}

export interface MaintenanceInput {
  work: string;
  performer?: string;
}

export interface FacilityFilter {
  status?: FacilityStatus;
  type?: string;
}

interface RawFacility {
  id: string;
  name: string;
  location: string | null;
  type: string | null;
  status: FacilityStatus;
  next_check_at: string | null;
  created_at: string;
}

interface RawIncident {
  id: string;
  facility_id: string;
  occurred_at: string | null;
  symptom: string;
  resolution: string | null;
  root_cause: string | null;
  created_at: string;
}

interface RawMaintenance {
  id: string;
  facility_id: string;
  performed_at: string | null;
  work: string;
  performer: string | null;
  parts: Record<string, unknown> | null;
  created_at: string;
}

function toFacility(raw: RawFacility): Facility {
  return {
    id: raw.id,
    name: raw.name,
    location: raw.location,
    type: raw.type,
    status: raw.status,
    nextCheckAt: raw.next_check_at,
    createdAt: raw.created_at,
  };
}

function toIncident(raw: RawIncident): Incident {
  return {
    id: raw.id,
    facilityId: raw.facility_id,
    occurredAt: raw.occurred_at,
    symptom: raw.symptom,
    resolution: raw.resolution,
    rootCause: raw.root_cause,
    createdAt: raw.created_at,
  };
}

function toMaintenance(raw: RawMaintenance): MaintenanceLog {
  return {
    id: raw.id,
    facilityId: raw.facility_id,
    performedAt: raw.performed_at,
    work: raw.work,
    performer: raw.performer,
    parts: raw.parts,
    createdAt: raw.created_at,
  };
}

/** FacilityFilter → 쿼리스트링(빈 값 생략). 순수 함수 — 테스트 대상. */
export function buildFacilityQuery(filter: FacilityFilter): string {
  const search = new URLSearchParams();
  if (filter.status) search.set("status", filter.status);
  if (filter.type && filter.type.trim()) search.set("type", filter.type.trim());
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export async function listFacilities(filter: FacilityFilter = {}): Promise<Facility[]> {
  const response = await apiFetch(`${API_BASE_URL}/admin/facilities${buildFacilityQuery(filter)}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawFacility[]).map(toFacility);
}

export async function getFacility(id: string): Promise<FacilityDetail> {
  const response = await apiFetch(`${API_BASE_URL}/admin/facilities/${id}`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const raw = await response.json();
  return {
    ...toFacility(raw as RawFacility),
    incidents: (raw.incidents as RawIncident[]).map(toIncident),
    maintenanceLogs: (raw.maintenance_logs as RawMaintenance[]).map(toMaintenance),
  };
}

export async function createFacility(input: FacilityCreateInput): Promise<Facility> {
  const response = await apiFetch(`${API_BASE_URL}/admin/facilities`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      name: input.name,
      location: input.location ?? null,
      type: input.type ?? null,
      status: input.status,
    }),
  });
  await ensureOk(response);
  return toFacility(await response.json());
}

export async function patchFacility(id: string, input: FacilityPatchInput): Promise<Facility> {
  const response = await apiFetch(`${API_BASE_URL}/admin/facilities/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  await ensureOk(response);
  return toFacility(await response.json());
}

export async function createIncident(facilityId: string, input: IncidentInput): Promise<Incident> {
  const response = await apiFetch(`${API_BASE_URL}/admin/facilities/${facilityId}/incidents`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      symptom: input.symptom,
      resolution: input.resolution ?? null,
      root_cause: input.rootCause ?? null,
    }),
  });
  await ensureOk(response);
  return toIncident(await response.json());
}

export async function createMaintenance(
  facilityId: string,
  input: MaintenanceInput,
): Promise<MaintenanceLog> {
  const response = await apiFetch(`${API_BASE_URL}/admin/facilities/${facilityId}/maintenance`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ work: input.work, performer: input.performer ?? null }),
  });
  await ensureOk(response);
  return toMaintenance(await response.json());
}

// ── 가입 승인 (docs/01 §13, docs/06 §2 · MANAGER 전용) ─────────────────────────
// 이름은 서버가 마스킹해서 준다 — 웹에서 재마스킹하지 않는다(원문 미보유).

export interface Approval {
  userId: string;
  nameMasked: string;
  rosterMatched: boolean;
  // 불일치 사유(H7-9): no_household_roster | person_mismatch | all_consumed
  mismatchReason: string | null;
  buildingName: string | null;
  floor: number | null;
  unitNo: number | null;
  requestedAt: string;
}

interface RawApproval {
  user_id: string;
  name_masked: string;
  roster_matched: boolean;
  mismatch_reason?: string | null;
  building_name: string | null;
  floor: number | null;
  unit_no: number | null;
  requested_at: string;
}

function toApproval(raw: RawApproval): Approval {
  return {
    userId: raw.user_id,
    nameMasked: raw.name_masked,
    rosterMatched: raw.roster_matched,
    mismatchReason: raw.mismatch_reason ?? null,
    buildingName: raw.building_name,
    floor: raw.floor,
    unitNo: raw.unit_no,
    requestedAt: raw.requested_at,
  };
}

// ── 명부 목록 (H7-9) ─────────────────────────────────────────────────────────

export interface RosterEntry {
  userId: string;
  nameMasked: string;
  buildingName: string | null;
  floor: number | null;
  unitNo: number | null;
  state: string; // unregistered | joined | moved_out
}

export interface RosterCounts {
  total: number;
  unregistered: number;
  joined: number;
  movedOut: number;
}

export interface RosterList {
  items: RosterEntry[];
  total: number; // 필터 적용 후 건수(페이지네이션 분모)
  counts: RosterCounts;
  lastUpload: { uploadedAt: string; rowCount: number; errorCount: number } | null;
}

/** 명부 목록(MANAGER) — 검색(q=동·호)·상태 필터·페이지네이션. */
export async function listRoster(
  params: { q?: string; state?: string; page?: number; size?: number } = {},
): Promise<RosterList> {
  const search = new URLSearchParams();
  if (params.q) search.set("q", params.q);
  if (params.state) search.set("state", params.state);
  if (params.page) search.set("page", String(params.page));
  if (params.size) search.set("size", String(params.size));
  const response = await apiFetch(`${API_BASE_URL}/admin/roster?${search.toString()}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return {
    items: (
      body.items as {
        user_id: string;
        name_masked: string;
        building_name: string | null;
        floor: number | null;
        unit_no: number | null;
        state: string;
      }[]
    ).map((raw) => ({
      userId: raw.user_id,
      nameMasked: raw.name_masked,
      buildingName: raw.building_name,
      floor: raw.floor,
      unitNo: raw.unit_no,
      state: raw.state,
    })),
    total: body.total,
    counts: {
      total: body.counts.total,
      unregistered: body.counts.unregistered,
      joined: body.counts.joined,
      movedOut: body.counts.moved_out,
    },
    lastUpload: body.last_upload
      ? {
          uploadedAt: body.last_upload.uploaded_at,
          rowCount: body.last_upload.row_count,
          errorCount: body.last_upload.error_count,
        }
      : null,
  };
}

/** 가입 대기 목록(MANAGER). 403=권한 없음. */
export async function listApprovals(status = "pending"): Promise<Approval[]> {
  const response = await apiFetch(
    `${API_BASE_URL}/admin/approvals?status=${encodeURIComponent(status)}`,
    { headers: DEV_HEADERS },
  );
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawApproval[]).map(toApproval);
}

/** 가입 승인 — RESIDENT 역할 부여·세션 폐기(재로그인 시 반영). 409=대기 중 아님. */
export async function approveSignup(userId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/approvals/${userId}/approve`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 가입 거절 — 사유 필수(신청자에게 알림함으로 전달). 409=대기 중 아님. */
export async function rejectSignup(userId: string, reason: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/approvals/${userId}/reject`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  });
  await ensureOk(response);
}

// ── 명부 업로드 (docs/01 §13, docs/03 §4.1 diff 병합 · MANAGER 전용) ────────────

export interface RosterRowError {
  row: number;
  reason: string;
}

export interface RosterUploadResult {
  uploadId: string;
  applied: number; // 신규 사전등록된 행 수
  markedInactive: number; // 명부에서 사라져 inactive 표시된 행 수
  errors: RosterRowError[];
}

function toRosterResult(raw: {
  upload_id: string;
  applied: number;
  marked_inactive: number;
  errors: RosterRowError[];
}): RosterUploadResult {
  return {
    uploadId: raw.upload_id,
    applied: raw.applied,
    markedInactive: raw.marked_inactive,
    errors: raw.errors,
  };
}

/** 명부 행 상태 수동 변경 — 미가입(unregistered) ↔ 전출 후보(moved_out). 404=명부 행 아님. */
export async function updateRosterState(userId: string, state: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/roster/${userId}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ state }),
  });
  await ensureOk(response);
}

/** 명부 행 삭제 — 사전등록 행을 PII vault째 완전 삭제(가입 계정 아님). */
export async function deleteRosterRow(userId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/roster/${userId}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 명부 업로드 양식 다운로드 URL — 세션 쿠키 동봉 최상위 GET이라 <a download>로 바로 쓴다(H7-7). */
export const ROSTER_TEMPLATE_URL = `${API_BASE_URL}/admin/roster/template`;

/** 명부 엑셀 업로드 — 신규만 추가, 기존 세대 불변, 사라진 세대는 inactive. 413=용량·422=형식오류. */
export async function uploadRoster(file: File): Promise<RosterUploadResult> {
  const form = new FormData();
  form.set("file", file);
  const response = await apiFetch(`${API_BASE_URL}/admin/roster/upload`, {
    method: "POST",
    headers: DEV_HEADERS,
    body: form,
  });
  await ensureOk(response);
  return toRosterResult(await response.json());
}

// ── 계정 (ADR-0011) — 로그인 세션의 자기 신원. '나에게 배정' 등에 사용 ────────────

export interface Me {
  // 자체 인증(ADR-0014) — kind 폐기. status: registered|pending|active|rejected|inactive.
  status: string;
  userId: string | null;
  roles: string[];
  mustChangePassword: boolean; // true면 비밀번호 변경 화면으로 강제(H7-2)
  email: string | null; // 로그인 이메일(세션 저장분) — 구세션은 null(H7-5)
}

export async function getMe(): Promise<Me> {
  const response = await apiFetch(`${API_BASE_URL}/me`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return {
    status: body.status,
    userId: body.user_id,
    roles: body.roles,
    mustChangePassword: body.must_change_password ?? false,
    email: body.email ?? null,
  };
}

// ── 단지 관리 (SYS_ADMIN 전용 · H7-2, ADR-0014) ───────────────────────────────

export interface TenantManager {
  userId: string;
  email: string | null;
  status: string; // invited=수락 대기 · active=활동 중
}

export interface Tenant {
  id: string;
  name: string;
  createdAt: string;
  status: string; // active | inactive(비활성화 — 소속 로그인 차단, H7-6)
  manager: TenantManager | null; // 단지당 1명(H7-6)
}

interface TenantRaw {
  id: string;
  name: string;
  created_at: string;
  status?: string;
  manager?: { user_id: string; email?: string | null; status: string } | null;
}

function toTenant(raw: TenantRaw): Tenant {
  return {
    id: raw.id,
    name: raw.name,
    createdAt: raw.created_at,
    status: raw.status ?? "active",
    manager: raw.manager
      ? { userId: raw.manager.user_id, email: raw.manager.email ?? null, status: raw.manager.status }
      : null,
  };
}

/** 단지 목록(생성 순) — 상태·현재 소장 포함(H7-6). 403=권한 없음. */
export async function listTenants(): Promise<Tenant[]> {
  const response = await apiFetch(`${API_BASE_URL}/admin/tenants`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as TenantRaw[]).map(toTenant);
}

/** 현재 소장 삭제(소프트 삭제+PII 비식별) — 교체·오초대 해소(H7-6). */
export async function removeTenantManager(tenantId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/tenants/${tenantId}/manager`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 빈 단지 완전 삭제. 409=계정·데이터 존재(H7-6). */
export async function deleteTenant(tenantId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/tenants/${tenantId}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 단지 비활성화/재활성화 — 비활성화는 소속 로그인 차단+세션 즉시 종료(H7-6). */
export async function setTenantActive(tenantId: string, active: boolean): Promise<void> {
  const action = active ? "activate" : "deactivate";
  const response = await apiFetch(`${API_BASE_URL}/admin/tenants/${tenantId}/${action}`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 단지 생성(이름). 응답에는 created_at이 없어 목록 재조회로 갱신한다. */
export async function createTenant(name: string): Promise<{ id: string; name: string }> {
  const response = await apiFetch(`${API_BASE_URL}/admin/tenants`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  await ensureOk(response);
  const body = await response.json();
  return { id: body.id, name: body.name };
}

/** 대상 단지에 소장(MANAGER) 초대 메일 발송. 202. 409=이미 등록된 이메일. */
export async function inviteManager(tenantId: string, email: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/tenants/${tenantId}/invite-manager`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  await ensureOk(response);
}

// ── 직원 관리 (MANAGER 전용 · H7-2, ADR-0014) ─────────────────────────────────
// 목록에 이메일 표시(ADR-0014 개정, H7-5) — 서버가 MANAGER 인가 뒤에서 복호해 반환.

export interface StaffMember {
  userId: string;
  roles: string[];
  status: string; // invited|active|inactive
  invitedAt: string;
  email: string | null; // 복호 실패·PII 부재 시 null
}

function toStaff(raw: {
  user_id: string;
  roles: string[];
  status: string;
  invited_at: string;
  email?: string | null;
}): StaffMember {
  return {
    userId: raw.user_id,
    roles: raw.roles,
    status: raw.status,
    invitedAt: raw.invited_at,
    email: raw.email ?? null,
  };
}

/** 직원 목록(소장·직원, 생성 순). 403=권한 없음. */
export async function listStaff(): Promise<StaffMember[]> {
  const response = await apiFetch(`${API_BASE_URL}/admin/staff`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (
    body.items as {
      user_id: string;
      roles: string[];
      status: string;
      invited_at: string;
      email?: string | null;
    }[]
  ).map(toStaff);
}

/** 자기 단지에 직원(STAFF) 초대 메일 발송. 202. 409=이미 등록된 이메일. */
export async function inviteStaff(email: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/staff/invite`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  await ensureOk(response);
}

/** 직원 비활성화 + 세션 즉시 revoke. 400=자기 자신·소장 대상·직원 아님. */
export async function deactivateStaff(userId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/staff/${userId}/deactivate`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 직원·타 소장 삭제 — 소프트 삭제+PII 비식별, 복구 불가(H7-6). 자기 자신 400. */
export async function deleteStaff(userId: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/staff/${userId}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

// ── 초대 수락·비밀번호 변경 (공개/세션 · H7-2) ────────────────────────────────
// apiFetch(401→로그인 리다이렉트)를 쓰지 않는다 — 초대는 세션 없이, 비밀번호 변경은
// 401(현재 비밀번호 오류)을 화면에서 직접 안내해야 하므로 plain fetch로 상태코드를 보존.

/** 초대 토큰 + 새 비밀번호로 계정 활성화. 204. 400=만료·사용됨. */
export async function acceptInvite(token: string, password: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/invite/accept`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });
  await ensureOk(response);
}

/** 현재·새 비밀번호로 교체(세션 재발급). 204. 401=현재 비밀번호 오류. */
export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/auth/password-change`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  await ensureOk(response);
}

// ── 운영 대시보드 (docs/01 §13, FR-ADM-06 · MANAGER 전용) ──────────────────────
// 비율(0~1 분수·null)은 서버 값 그대로 — 표기 변환은 features/dashboard/data.ts.

export interface DashboardStats {
  days: number;
  ai: {
    queryCount: number;
    avgTokenInput: number | null;
    avgTokenOutput: number | null;
    answerRate: number | null;
    fallbackRate: number | null;
    needsReviewRate: number | null;
  };
  cache: { hits: number; misses: number; hitRate: number | null };
  budget: { enabled: boolean; budget: number; usedToday: number; exceeded: boolean };
  inquiries: Record<string, number>;
  facilities: Record<string, number>;
}

interface RawDashboardStats {
  days: number;
  ai: {
    query_count: number;
    avg_token_input: number | null;
    avg_token_output: number | null;
    answer_rate: number | null;
    fallback_rate: number | null;
    needs_review_rate: number | null;
  };
  cache: { hits: number; misses: number; hit_rate: number | null };
  budget: { enabled: boolean; budget: number; used_today: number; exceeded: boolean };
  inquiries: Record<string, number>;
  facilities: Record<string, number>;
}

export async function getDashboardStats(days: number): Promise<DashboardStats> {
  const response = await apiFetch(`${API_BASE_URL}/admin/dashboard/stats?days=${days}`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const raw = (await response.json()) as RawDashboardStats;
  return {
    days: raw.days,
    ai: {
      queryCount: raw.ai.query_count,
      avgTokenInput: raw.ai.avg_token_input,
      avgTokenOutput: raw.ai.avg_token_output,
      answerRate: raw.ai.answer_rate,
      fallbackRate: raw.ai.fallback_rate,
      needsReviewRate: raw.ai.needs_review_rate,
    },
    cache: { hits: raw.cache.hits, misses: raw.cache.misses, hitRate: raw.cache.hit_rate },
    budget: {
      enabled: raw.budget.enabled,
      budget: raw.budget.budget,
      usedToday: raw.budget.used_today,
      exceeded: raw.budget.exceeded,
    },
    inquiries: raw.inquiries,
    facilities: raw.facilities,
  };
}

// ── 코드 관리 (H8-4, docs/adr/0017) ─────────────────────────────────────────

/** 그룹에 속한 단일 코드. parentId 로 2단계 계층을 구성(프론트가 트리화). */
export interface Code {
  id: string;
  groupId: string;
  code: string;
  label: string;
  parentId: string | null;
  sortOrder: number;
  active: boolean;
}

/** 공통 코드 그룹 + 소속 코드(평면). isSystem 이면 삭제·그룹 키 수정 불가. */
export interface CodeGroup {
  id: string;
  groupKey: string;
  name: string;
  description: string | null;
  isSystem: boolean;
  codes: Code[];
}

export interface CreateCodeGroupInput {
  groupKey: string;
  name: string;
  description?: string;
}

export interface UpdateCodeGroupInput {
  name?: string;
  description?: string | null;
}

export interface CreateCodeInput {
  groupId: string;
  code: string;
  label: string;
  parentId?: string | null;
  sortOrder?: number;
}

export interface UpdateCodeInput {
  label?: string;
  sortOrder?: number;
  active?: boolean;
  parentId?: string | null;
}

interface RawCode {
  id: string;
  group_id: string;
  code: string;
  label: string;
  parent_id: string | null;
  sort_order: number;
  active: boolean;
}

interface RawCodeGroup {
  id: string;
  group_key: string;
  name: string;
  description: string | null;
  is_system: boolean;
  codes?: RawCode[] | null;
}

function toCode(raw: RawCode): Code {
  return {
    id: raw.id,
    groupId: raw.group_id,
    code: raw.code,
    label: raw.label,
    parentId: raw.parent_id,
    sortOrder: raw.sort_order,
    active: raw.active,
  };
}

function toCodeGroup(raw: RawCodeGroup): CodeGroup {
  return {
    id: raw.id,
    groupKey: raw.group_key,
    name: raw.name,
    description: raw.description ?? null,
    isSystem: raw.is_system,
    codes: (raw.codes ?? []).map(toCode),
  };
}

/** 그룹 목록 + 각 그룹의 코드(평면 배열). MANAGER·STAFF. */
export async function listCodeGroups(): Promise<CodeGroup[]> {
  const response = await apiFetch(`${API_BASE_URL}/admin/code-groups`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawCodeGroup[]).map(toCodeGroup);
}

/** 그룹 생성 — group_key(대문자 스네이크)·name·설명. 409=중복 키. MANAGER. */
export async function createCodeGroup(input: CreateCodeGroupInput): Promise<CodeGroup> {
  const payload: Record<string, string> = { group_key: input.groupKey, name: input.name };
  if (input.description !== undefined) payload.description = input.description;
  const response = await apiFetch(`${API_BASE_URL}/admin/code-groups`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await ensureOk(response);
  return toCodeGroup(await response.json());
}

/** 그룹 수정 — name·description 만(group_key 불변). MANAGER. */
export async function updateCodeGroup(
  id: string,
  input: UpdateCodeGroupInput,
): Promise<CodeGroup> {
  const payload: Record<string, string | null> = {};
  if (input.name !== undefined) payload.name = input.name;
  if (input.description !== undefined) payload.description = input.description;
  const response = await apiFetch(`${API_BASE_URL}/admin/code-groups/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await ensureOk(response);
  return toCodeGroup(await response.json());
}

/** 그룹 삭제 — 하위 코드 CASCADE. is_system 이면 409. MANAGER. 204. */
export async function deleteCodeGroup(id: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/code-groups/${id}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 코드 생성 — group_id·code·label·(부모·정렬). 409=중복 코드. MANAGER. */
export async function createCode(input: CreateCodeInput): Promise<Code> {
  const response = await apiFetch(`${API_BASE_URL}/admin/codes`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      group_id: input.groupId,
      code: input.code,
      label: input.label,
      parent_id: input.parentId ?? null,
      sort_order: input.sortOrder ?? 0,
    }),
  });
  await ensureOk(response);
  return toCode(await response.json());
}

/** 코드 수정 — label·sort_order·active·parent_id. 지정한 필드만 전송. MANAGER. */
export async function updateCode(id: string, input: UpdateCodeInput): Promise<Code> {
  const payload: Record<string, string | number | boolean | null> = {};
  if (input.label !== undefined) payload.label = input.label;
  if (input.sortOrder !== undefined) payload.sort_order = input.sortOrder;
  if (input.active !== undefined) payload.active = input.active;
  if (input.parentId !== undefined) payload.parent_id = input.parentId;
  const response = await apiFetch(`${API_BASE_URL}/admin/codes/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await ensureOk(response);
  return toCode(await response.json());
}

/** 코드 삭제 — 자식이 있거나 도메인 참조 시 409. MANAGER. 204. */
export async function deleteCode(id: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/codes/${id}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

// ── 동/호수 관리 (H8-5) ────────────────────────────────────────────────────────

export interface Building {
  id: string;
  name: string;
  floors: number | null;
  householdCount: number;
}

export interface Household {
  id: string;
  floor: number;
  unitNo: number;
  status: string;
}

export interface HouseholdList {
  building: { id: string; name: string; floors: number | null };
  items: Household[];
}

export interface BulkHouseholdInput {
  floorStart: number;
  floorEnd: number;
  unitStart: number;
  unitEnd: number;
  status?: string;
}

export interface BulkHouseholdResult {
  created: number;
  skipped: number;
}

interface RawBuilding {
  id: string;
  name: string;
  floors: number | null;
  household_count?: number;
}

interface RawHousehold {
  id: string;
  floor: number;
  unit_no: number;
  status: string;
}

function toBuilding(raw: RawBuilding): Building {
  return {
    id: raw.id,
    name: raw.name,
    floors: raw.floors,
    householdCount: raw.household_count ?? 0,
  };
}

function toHousehold(raw: RawHousehold): Household {
  return { id: raw.id, floor: raw.floor, unitNo: raw.unit_no, status: raw.status };
}

/** 동 목록(+세대 수 집계). 403=권한 없음. */
export async function listBuildings(): Promise<Building[]> {
  const response = await apiFetch(`${API_BASE_URL}/admin/buildings`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawBuilding[]).map(toBuilding);
}

/** 동 생성. 409=같은 이름의 동 존재. */
export async function createBuilding(input: {
  name: string;
  floors?: number | null;
}): Promise<Building> {
  const response = await apiFetch(`${API_BASE_URL}/admin/buildings`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ name: input.name, floors: input.floors ?? null }),
  });
  await ensureOk(response);
  return toBuilding(await response.json());
}

/** 동 수정 — name·floors. 409=이름 중복. */
export async function updateBuilding(
  id: string,
  input: { name?: string; floors?: number | null },
): Promise<Building> {
  const body: Record<string, unknown> = {};
  if (input.name !== undefined) body.name = input.name;
  if (input.floors !== undefined) body.floors = input.floors;
  const response = await apiFetch(`${API_BASE_URL}/admin/buildings/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await ensureOk(response);
  return toBuilding(await response.json());
}

/** 동 삭제. 409=소속 세대 존재. */
export async function deleteBuilding(id: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/buildings/${id}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}

/** 동의 세대 목록(층·호 오름차순). 404=동 없음. */
export async function listHouseholds(buildingId: string): Promise<HouseholdList> {
  const response = await apiFetch(`${API_BASE_URL}/admin/buildings/${buildingId}/households`, {
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  const body = await response.json();
  return {
    building: {
      id: body.building.id,
      name: body.building.name,
      floors: body.building.floors,
    },
    items: (body.items as RawHousehold[]).map(toHousehold),
  };
}

/** 세대 일괄 생성(층·호 범위, 단일은 start==end). 이미 있는 (층,호)는 건너뜀. 422=범위 오류. */
export async function createHouseholds(
  buildingId: string,
  input: BulkHouseholdInput,
): Promise<BulkHouseholdResult> {
  const response = await apiFetch(`${API_BASE_URL}/admin/buildings/${buildingId}/households`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      floor_start: input.floorStart,
      floor_end: input.floorEnd,
      unit_start: input.unitStart,
      unit_end: input.unitEnd,
      status: input.status ?? "active",
    }),
  });
  await ensureOk(response);
  return (await response.json()) as BulkHouseholdResult;
}

/** 세대 수정 — floor·unit_no·status. 409=같은 동 층·호 중복. */
export async function updateHousehold(
  id: string,
  input: { floor?: number; unitNo?: number; status?: string },
): Promise<Household> {
  const body: Record<string, unknown> = {};
  if (input.floor !== undefined) body.floor = input.floor;
  if (input.unitNo !== undefined) body.unit_no = input.unitNo;
  if (input.status !== undefined) body.status = input.status;
  const response = await apiFetch(`${API_BASE_URL}/admin/households/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await ensureOk(response);
  return toHousehold(await response.json());
}

/** 세대 삭제. 409=입주민·명부·민원·관리비 연결 중. */
export async function deleteHousehold(id: string): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/households/${id}`, {
    method: "DELETE",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
}
