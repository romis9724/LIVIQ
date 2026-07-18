// E2E 멱등 시드 — Playwright globalSetup (docs/09 §8.2 H2-7).
//
// superuser(liviq)로 접속하므로 RLS를 우회한다(시드는 격리 예외). 실제 격리 검증은
// pytest 통합 테스트가 런타임 role로 수행한다. 여기서는 결정론 여정에 필요한 최소 데이터만
// 고정 UUID로 심는다: tenant·building·household·approved user·published notice 2건·
// 확정 fee(당월+전월)·needs_review 검수 메시지 1건.
//
// 멱등성: E2E tenant 하위 행을 FK 역순으로 전부 지우고 다시 넣는다(반복 실행 안전).

import { Client } from "pg";

import {
  BUILDING_NAME,
  E2E,
  FEE_BREAKDOWN,
  FEE_CURRENT_TOTAL,
  FEE_PREV_TOTAL,
  FLOOR,
  NOTICE1,
  NOTICE2,
  REVIEW,
  UNIT_NO,
  currentMonth,
  prevMonth,
} from "./fixtures";

const DEFAULT_DSN = "postgresql://liviq:liviq@localhost:15432/liviq";

/** asyncpg 드라이버 접두사를 제거해 node-postgres가 이해하는 DSN으로 정규화. */
function toPgDsn(url: string): string {
  return url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql");
}

// FK 역순 삭제 대상(전부 tenant_id 컬럼 보유 — 시드가 안 만드는 테이블도 방어적으로 포함해
// 런타임이 남긴 잔여 행에 wipe가 FK로 깨지지 않게 한다). tenants는 마지막에 id로.
const CHILD_TABLES = [
  "plan_devices",
  "floor_plans",
  "incidents",
  "maintenance_logs",
  "facilities",
  "document_chunks",
  "documents",
  "inquiry_events",
  "inquiries",
  "inquiry_categories",
  "notifications",
  "ai_feedback",
  "citations",
  "messages",
  "conversations",
  "notice_drafts",
  "notices",
  "fees",
  "excel_uploads",
  "audit_logs",
  "jobs",
  "outbox_events",
  "ai_eval_golden",
  "pii_vault",
  "user_roles",
  "consents",
  "users",
  "tenant_keys",
  "households",
  "unit_types",
  "buildings",
];

async function wipe(client: Client): Promise<void> {
  for (const table of CHILD_TABLES) {
    await client.query(`DELETE FROM ${table} WHERE tenant_id = $1`, [E2E.tenantId]);
  }
  await client.query(`DELETE FROM tenants WHERE id = $1`, [E2E.tenantId]);
}

async function insert(client: Client): Promise<void> {
  await client.query(
    `INSERT INTO tenants (id, name, status, settings)
     VALUES ($1, 'E2E 단지', 'active', '{"invite_code": "E2E-0000"}'::jsonb)`,
    [E2E.tenantId],
  );

  await client.query(
    `INSERT INTO buildings (id, tenant_id, name, floors) VALUES ($1, $2, $3, 15)`,
    [E2E.buildingId, E2E.tenantId, BUILDING_NAME],
  );

  await client.query(
    `INSERT INTO households (id, tenant_id, building_id, floor, unit_no, status)
     VALUES ($1, $2, $3, $4, $5, 'active')`,
    [E2E.householdId, E2E.tenantId, E2E.buildingId, FLOOR, UNIT_NO],
  );

  // 승인 완료 입주민(approved_at 과거) — 관리비 조회 스코프(FR-FEE-03)와 민원 접수 통과.
  // login_id = mock IdP sub — 세션 로그인(auth.setup.ts)이 이 행으로 신원을 확정한다.
  await client.query(
    `INSERT INTO users (id, tenant_id, household_id, status, roster_matched, approved_at, login_id)
     VALUES ($1, $2, $3, 'active', true, '2020-01-01T00:00:00Z', $4)`,
    [E2E.userId, E2E.tenantId, E2E.householdId, E2E.googleSub],
  );
  for (const role of ["RESIDENT", "MANAGER"]) {
    await client.query(
      `INSERT INTO user_roles (tenant_id, user_id, role) VALUES ($1, $2, $3)`,
      [E2E.tenantId, E2E.userId, role],
    );
  }

  const now = new Date().toISOString();
  await client.query(
    `INSERT INTO notices (id, tenant_id, title, body, status, audience, published_at, published_by)
     VALUES ($1, $2, $3, $4, 'published', 'ALL', $5, $6)`,
    [E2E.notice1Id, E2E.tenantId, NOTICE1.title, NOTICE1.body, now, E2E.userId],
  );
  await client.query(
    `INSERT INTO notices (id, tenant_id, title, body, status, audience, published_at, published_by)
     VALUES ($1, $2, $3, $4, 'published', 'ALL', $5, $6)`,
    // 두 번째 공지는 1분 앞서 발행(목록 정렬 published_at DESC — 최신이 notice1).
    [
      E2E.notice2Id,
      E2E.tenantId,
      NOTICE2.title,
      NOTICE2.body,
      new Date(Date.now() - 60_000).toISOString(),
      E2E.userId,
    ],
  );

  // 확정 관리비 — 당월·전월(전월 대비 렌더 확인). breakdown JSONB.
  await client.query(
    `INSERT INTO fees (id, tenant_id, household_id, period, breakdown, total_amount, source)
     VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'excel')`,
    [
      E2E.feeCurrentId,
      E2E.tenantId,
      E2E.householdId,
      currentMonth(),
      JSON.stringify(FEE_BREAKDOWN),
      FEE_CURRENT_TOTAL,
    ],
  );
  await client.query(
    `INSERT INTO fees (id, tenant_id, household_id, period, breakdown, total_amount, source)
     VALUES ($1, $2, $3, $4, $5::jsonb, $6, 'excel')`,
    [
      E2E.feePrevId,
      E2E.tenantId,
      E2E.householdId,
      prevMonth(),
      JSON.stringify(FEE_BREAKDOWN),
      FEE_PREV_TOTAL,
    ],
  );

  // 검수 큐 — 대화 + user 질문 + 저신뢰 assistant 답변(needs_review).
  await client.query(
    `INSERT INTO conversations (id, tenant_id, user_id, channel) VALUES ($1, $2, $3, 'resident')`,
    [E2E.conversationId, E2E.tenantId, E2E.userId],
  );
  await client.query(
    `INSERT INTO messages (id, tenant_id, conversation_id, role, content, created_at)
     VALUES ($1, $2, $3, 'user', $4, NOW() - interval '1 minute')`,
    [E2E.userMessageId, E2E.tenantId, E2E.conversationId, REVIEW.question],
  );
  await client.query(
    `INSERT INTO messages
       (id, tenant_id, conversation_id, role, content, status, confidence, review_status, created_at)
     VALUES ($1, $2, $3, 'assistant', $4, 'answered', $5, 'needs_review', NOW())`,
    [
      E2E.assistantMessageId,
      E2E.tenantId,
      E2E.conversationId,
      REVIEW.answer,
      REVIEW.confidence,
    ],
  );
}

async function globalSetup(): Promise<void> {
  const dsn = toPgDsn(process.env.DATABASE_URL ?? DEFAULT_DSN);
  const client = new Client({ connectionString: dsn });
  await client.connect();
  try {
    await client.query("BEGIN");
    await wipe(client);
    await insert(client);
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    await client.end();
  }
}

export default globalSetup;
