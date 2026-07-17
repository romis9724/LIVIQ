// 민원 — apps/api HTTP 클라이언트 (docs/01 §13). dev 헤더는 dev-context 공유.
// api-types 전환은 백로그 — 지금은 로컬 타입.

import { API_BASE_URL, DEV_HEADERS } from "@/lib/dev-context";

export type InquiryStatus = "received" | "assigned" | "in_progress" | "done";
export type AiPriority = "urgent" | "normal" | "low";
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
  aiPriority: AiPriority | null;
  categoryId: string | null;
  aiSuggestedCategoryId: string | null;
  assigneeUserId: string | null;
  authorUserId: string;
  createdAt: string;
  updatedAt: string;
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
  categoryId?: string | null;
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
  ai_priority: AiPriority | null;
  category_id: string | null;
  ai_suggested_category_id: string | null;
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
    aiPriority: raw.ai_priority,
    categoryId: raw.category_id,
    aiSuggestedCategoryId: raw.ai_suggested_category_id,
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
  const response = await fetch(`${API_BASE_URL}/inquiries`, {
    method: "POST",
    headers: { ...DEV_HEADERS, "Content-Type": "application/json" },
    body: JSON.stringify({
      title: input.title,
      body: input.body,
      category_id: input.categoryId ?? null,
    }),
  });
  await ensureOk(response);
  return toInquiry(await response.json());
}

export async function listMyInquiries(): Promise<Inquiry[]> {
  const response = await fetch(`${API_BASE_URL}/inquiries`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawInquiry[]).map(toInquiry);
}

export async function getInquiry(id: string): Promise<Inquiry> {
  const response = await fetch(`${API_BASE_URL}/inquiries/${id}`, { headers: DEV_HEADERS });
  await ensureOk(response);
  return toInquiry(await response.json());
}

export async function listInquiryEvents(id: string): Promise<InquiryEvent[]> {
  const response = await fetch(`${API_BASE_URL}/inquiries/${id}/events`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return (body.items as RawEvent[]).map(toEvent);
}
