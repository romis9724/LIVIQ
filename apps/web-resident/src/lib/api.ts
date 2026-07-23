// 민원 — apps/api HTTP 클라이언트 (docs/01 §13). dev 헤더는 dev-context 공유.
// api-types 전환은 백로그 — 지금은 로컬 타입.

import { API_BASE_URL, DEV_HEADERS, apiFetch } from "@/lib/dev-context";

export type InquiryStatus = "received" | "assigned" | "in_progress" | "done" | "reopened";
export type Priority = "urgent" | "normal" | "low";
export type InquiryEventType =
  | "created"
  | "ai_classified"
  | "assigned"
  | "status_changed"
  | "comment";

export interface Inquiry {
  id: string;
  title: string;
  body: string;
  status: InquiryStatus;
  priority: Priority | null;
  categoryCodeId: string | null;
  assigneeUserId: string | null;
  authorUserId: string;
  createdAt: string;
  updatedAt: string;
}

export interface InquiryCategory {
  id: string;
  label: string;
}

export interface InquiryEvent {
  id: string;
  type: InquiryEventType;
  actorUserId: string | null;
  payload: Record<string, unknown> | null;
  createdAt: string;
}

export interface CreateInquiryInput {
  title: string;
  body: string;
  categoryCodeId?: string | null;
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

// api InquiryOut(snake_case) → Inquiry(camelCase).
interface RawInquiry {
  id: string;
  title: string;
  body: string;
  status: InquiryStatus;
  priority: Priority | null;
  category_code_id: string | null;
  assignee_user_id: string | null;
  author_user_id: string;
  created_at: string;
  updated_at: string;
}

interface RawEvent {
  id: string;
  type: InquiryEventType;
  actor_user_id: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

function toInquiry(raw: RawInquiry): Inquiry {
  return {
    id: raw.id,
    title: raw.title,
    body: raw.body,
    status: raw.status,
    priority: raw.priority,
    categoryCodeId: raw.category_code_id,
    assigneeUserId: raw.assignee_user_id,
    authorUserId: raw.author_user_id,
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  };
}

function toEvent(raw: RawEvent): InquiryEvent {
  return {
    id: raw.id,
    type: raw.type,
    actorUserId: raw.actor_user_id,
    payload: raw.payload,
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

export async function createInquiry(input: CreateInquiryInput): Promise<Inquiry> {
  const response = await apiFetch(`${API_BASE_URL}/inquiries`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      body: input.body,
      category_code_id: input.categoryCodeId ?? null,
    }),
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}

export async function listInquiryCategories(): Promise<InquiryCategory[]> {
  const response = await apiFetch(`${API_BASE_URL}/inquiries/categories`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as InquiryCategory[]).map((item) => ({ id: item.id, label: item.label }));
}

export async function postInquiryFeedback(id: string, body: string): Promise<Inquiry> {
  const response = await apiFetch(`${API_BASE_URL}/inquiries/${id}/comments`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({ body }),
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}

// 재확인 요청 — 작성자 본인·status=done 일 때만 허용(그 외 404/422). done→reopened.
export async function reopenInquiry(id: string): Promise<Inquiry> {
  const response = await apiFetch(`${API_BASE_URL}/inquiries/${id}/reopen`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}

export async function listMyInquiries(): Promise<Inquiry[]> {
  const response = await apiFetch(`${API_BASE_URL}/inquiries`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawInquiry[]).map(toInquiry);
}

export async function getInquiry(id: string): Promise<Inquiry> {
  const response = await apiFetch(`${API_BASE_URL}/inquiries/${id}`, { headers: DEV_HEADERS });
  await ensureOk(response);
  return toInquiry(await response.json());
}

export async function listInquiryEvents(id: string): Promise<InquiryEvent[]> {
  const response = await apiFetch(`${API_BASE_URL}/inquiries/${id}/events`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawEvent[]).map(toEvent);
}

// ── 공지 (docs/01 §13) — 발행된 공지만 노출. pinned DESC→published_at DESC 서버 정렬 ──

export interface Attachment {
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
  audience: string;
  pinned: boolean;
  publishedAt: string | null;
  createdAt: string;
  attachments: Attachment[];
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
  audience: string;
  pinned: boolean;
  published_at: string | null;
  created_at: string;
  attachments: RawAttachment[];
}

function toAttachment(raw: RawAttachment): Attachment {
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
    audience: raw.audience,
    pinned: raw.pinned,
    publishedAt: raw.published_at,
    createdAt: raw.created_at,
    attachments: (raw.attachments ?? []).map(toAttachment),
  };
}

export async function listNotices(): Promise<Notice[]> {
  const response = await apiFetch(`${API_BASE_URL}/notices`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawNotice[]).map(toNotice);
}

/**
 * 첨부파일 다운로드 — 세션 쿠키 인가라 별도 오리진에선 <a download>가 강제 저장을 못 한다.
 * blob으로 받아 object URL을 만들어 a[download]로 저장한다(filename은 알려진 메타 사용).
 */
export async function downloadAttachment(
  noticeId: string,
  attachment: Attachment,
): Promise<void> {
  const response = await apiFetch(
    `${API_BASE_URL}/notices/${noticeId}/attachments/${attachment.id}`,
    { headers: DEV_HEADERS },
  );
  await ensureOk(response);
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = attachment.filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    URL.revokeObjectURL(url);
  }
}

// ── 알림함 (ADR-0012) — 인앱 함 조회·읽음. 외부 발송 아님 ──────────────────────

export type NotificationType = "notice" | "inquiry_status" | "approval" | "system";

export interface AppNotification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  link: string | null;
  readAt: string | null;
  createdAt: string;
}

interface RawNotification {
  id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

function toNotification(raw: RawNotification): AppNotification {
  return {
    id: raw.id,
    type: raw.type,
    title: raw.title,
    body: raw.body,
    link: raw.link,
    readAt: raw.read_at,
    createdAt: raw.created_at,
  };
}

export async function listNotifications(
  opts?: { limit?: number; page?: number },
): Promise<AppNotification[]> {
  const query = new URLSearchParams();
  if (opts?.limit !== undefined) query.set("limit", String(opts.limit));
  if (opts?.page !== undefined) query.set("page", String(opts.page));
  const suffix = query.toString() ? `?${query}` : "";
  const response = await apiFetch(`${API_BASE_URL}/notifications${suffix}`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawNotification[]).map(toNotification);
}

export async function markNotificationRead(id: string): Promise<AppNotification> {
  const response = await apiFetch(`${API_BASE_URL}/notifications/${id}/read`, {
    method: "POST",
    headers: DEV_HEADERS,
  });
  await ensureOk(response);
  return toNotification(await response.json());
}

// ── 온보딩·계정 상태 (docs/04 §2, ADR-0011) ─────────────────────────────────
// /onboarding/profile 은 온보딩 세션(역할 없음)으로만 접근 가능. /me 는 상태 무관.

/** POST /onboarding/profile 본문 — 서버 계약(snake_case). floor·unit_no 는 독립 필드. */
export interface ProfilePayload {
  consents: { purpose: string; granted: boolean }[];
  name: string;
  birth_date: string; // YYYY-MM-DD
  building_name: string;
  floor: number;
  unit_no: number;
}

export interface ProfileResult {
  userId: string;
  status: string;
  rosterMatched: boolean;
}

/** 가입 정보 제출. 성공 시 온보딩 세션 → pending 세션 승격(쿠키 재발급). 422/404/409=검증 실패. */
export async function submitProfile(payload: ProfilePayload): Promise<ProfileResult> {
  const response = await apiFetch(`${API_BASE_URL}/onboarding/profile`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  await ensureOk(response);
  const body = await response.json();
  return { userId: body.user_id, status: body.status, rosterMatched: body.roster_matched };
}

/**
 * 계정 상태(화면 분기 단일 출처, 자체 인증 ADR-0014).
 * status: registered=프로필 미제출(온보딩 필요) · pending=승인 대기 · active=정상 · rejected · inactive.
 */
export interface Me {
  status: string;
  userId: string | null;
  roles: string[];
  mustChangePassword: boolean; // true면 비밀번호 변경 강제(H7-2, 주민 흐름은 미사용)
  displayName: string | null; // 본인 실명(서버가 본인 vault만 복호, 미제출 시 null)
  unitLabel: string | null; // "{동}동 {호}호"(세대 미배정 시 null)
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
    displayName: body.display_name ?? null,
    unitLabel: body.unit_label ?? null,
  };
}
