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
  const response = await apiFetch(`${API_BASE_URL}/documents${buildListQuery(params)}`, {
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
  const response = await apiFetch(`${API_BASE_URL}/documents`, {
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
  const response = await apiFetch(`${API_BASE_URL}/documents/${id}`, {
    method: "PATCH",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  await ensureOk(response);
  return toItem(await response.json());
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
  const response = await apiFetch(`${API_BASE_URL}/admin/notices/drafts`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ keywords }),
  });
  await ensureOk(response);
  return toDraft(await response.json());
}

/** 검수 완료한 초안을 발행(사람 확정). audience 는 현재 ALL 만. 409=이미 처리된 초안. */
export async function publishNotice(input: PublishNoticeInput): Promise<void> {
  const response = await apiFetch(`${API_BASE_URL}/admin/notices`, {
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
