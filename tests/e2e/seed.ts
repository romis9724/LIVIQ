// E2E 멱등 시드 — Playwright globalSetup + 가입 여정 스펙 공용 헬퍼 (docs/09 §8.2·§8.8).
//
// superuser(liviq)로 접속하므로 RLS를 우회한다(시드는 격리 예외). 실제 격리 검증은
// pytest 통합 테스트가 런타임 role로 수행한다. 여기서는 결정론 여정에 필요한 최소 데이터만
// 고정 UUID로 심는다: E2E tenant·building·household·approved user·published notice 2건·
// 확정 fee(당월+전월)·needs_review 검수 메시지 1건, 그리고 시스템 테넌트 + E2E SYS_ADMIN.
//
// 멱등성: E2E tenant 하위 행을 FK 역순으로 전부 지우고 다시 넣는다(반복 실행 안전).
// 가입 여정 단지(name LIKE 'E2E-%')와 그 종속 행도 함께 정리해 반복 실행 누적을 막는다.
// SYS_ADMIN은 고정 UUID 계정만 정리·재삽입한다(공유 시스템 테넌트는 파괴하지 않는다).
//
// 여정 스펙(signup-journey)이 재사용하는 헬퍼도 여기서 export한다(superuser pg 연결·이메일
// HMAC·토큰 INSERT·세대 시드). login_id/토큰 해시 계산을 앱(pii.py·auth_tokens.py)과 일치시킨다.

import { createHash, createHmac, hkdfSync } from "node:crypto";

import { Client } from "pg";

import {
  BUILDING_NAME,
  E2E,
  FEE_BREAKDOWN,
  FEE_CURRENT_TOTAL,
  FEE_PREV_TOTAL,
  FLOOR,
  MISMATCH_PERSON,
  NOTICE1,
  NOTICE2,
  REVIEW,
  ROSTER_PERSON,
  SYS,
  UNIT_NO,
  currentMonth,
  prevMonth,
} from "./fixtures";

const DEFAULT_DSN = "postgresql://liviq:liviq@localhost:15432/liviq";

// KEK — playwright.config 이 api 에 주입하는 zeros 키(Buffer.alloc(32,0) base64)와 동일해야
// login_id(이메일 HMAC)가 일치한다. env 미설정이면 같은 기본값으로 폴백(config 와 동치).
const PII_MASTER_KEY_B64 = process.env.PII_MASTER_KEY ?? Buffer.alloc(32, 0).toString("base64");

// e2e-password-liviq-1 의 Argon2id 해시(app.password 로 사전 생성 — 재계산 금지, ADR-0014).
const PASSWORD_HASH =
  "$argon2id$v=19$m=65536,t=3,p=4$X7gU1W3GvYUm6bpNEiVbtA$aO9H/bv9kOKI/IblIAyJoSm6DQaZBGrQPJSHXBovcOY";

/** 이메일 → login_id 조회 키. apps/api/app/pii.py(HKDF salt=None + keyed HMAC-SHA256)와 동일. */
export function emailHash(email: string): string {
  const kek = Buffer.from(PII_MASTER_KEY_B64, "base64");
  // python cryptography HKDF(salt=None)는 zero-filled 32byte salt 와 동일.
  const hmacKey = Buffer.from(
    hkdfSync("sha256", kek, Buffer.alloc(32, 0), Buffer.from("pii-hmac"), 32),
  );
  return createHmac("sha256", hmacKey)
    .update(email.trim().toLowerCase().normalize("NFC"), "utf8")
    .digest("hex");
}

/** asyncpg 드라이버 접두사를 제거해 node-postgres가 이해하는 DSN으로 정규화. */
function toPgDsn(url: string): string {
  return url
    .replace("+asyncpg", "")
    .replace("postgresql+asyncpg", "postgresql");
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
  // 첨부는 notices FK(CASCADE)라 notices 삭제가 되쓸어가지만, 방어적으로 먼저 지운다(H8-1, ADR-0015).
  "notice_attachments",
  "notices",
  "fees",
  "excel_uploads",
  "audit_logs",
  "jobs",
  "outbox_events",
  "ai_eval_golden",
  "user_roles",
  "consents",
  // auth_tokens.user_id → users FK(ondelete 없음) — users보다 먼저 지운다(가입 여정이 검증·초대 토큰 생성).
  "auth_tokens",
  // users.pii_ref → pii_vault FK — users를 pii_vault보다 먼저 지워야 한다(가입 여정이 pii_ref 보유 계정 생성).
  "users",
  "pii_vault",
  "tenant_keys",
  "households",
  "unit_types",
  "buildings",
];

/** 한 tenant의 하위 행을 FK 역순으로 전부 지운 뒤 tenant 자체를 삭제(멱등). */
export async function wipeTenant(client: Client, tenantId: string): Promise<void> {
  for (const table of CHILD_TABLES) {
    await client.query(`DELETE FROM ${table} WHERE tenant_id = $1`, [tenantId]);
  }
  await client.query(`DELETE FROM tenants WHERE id = $1`, [tenantId]);
}

/** 가입 여정 단지(name LIKE 'E2E-%')와 종속 행 정리 — 반복 실행 누적 방지(고정 'E2E 단지' 미포함). */
export async function wipeJourneyTenants(client: Client): Promise<void> {
  const { rows } = await client.query<{ id: string }>(
    `SELECT id FROM tenants WHERE name LIKE 'E2E-%'`,
  );
  for (const { id } of rows) {
    await wipeTenant(client, id);
  }
}

/** 시스템 테넌트 확보(공유 — 파괴 금지) + 고정 UUID SYS_ADMIN 계정 정리·재삽입(멱등, H7-4). */
async function seedSysAdmin(client: Client): Promise<void> {
  await client.query(
    `INSERT INTO tenants (id, name, status) VALUES ($1, 'LIVIQ 시스템', 'active')
     ON CONFLICT (id) DO NOTHING`,
    [SYS.tenantId],
  );
  // 고정 계정만 정리(다른 시스템 계정·토큰은 보존). auth_tokens는 users FK라 먼저.
  await client.query(`DELETE FROM auth_tokens WHERE user_id = $1`, [SYS.userId]);
  await client.query(`DELETE FROM user_roles WHERE user_id = $1`, [SYS.userId]);
  await client.query(`DELETE FROM users WHERE id = $1`, [SYS.userId]);
  // pii_ref는 NULL — 로그인은 login_id만 쓰므로 SYS_ADMIN은 pii_vault 없이 충분.
  await client.query(
    `INSERT INTO users
       (id, tenant_id, status, login_id, password_hash, email_verified_at, must_change_password)
     VALUES ($1, $2, 'active', $3, $4, NOW(), false)`,
    [SYS.userId, SYS.tenantId, emailHash(SYS.email), PASSWORD_HASH],
  );
  await client.query(
    `INSERT INTO user_roles (tenant_id, user_id, role) VALUES ($1, $2, 'SYS_ADMIN')`,
    [SYS.tenantId, SYS.userId],
  );
}

/** superuser(liviq) pg 연결 — RLS 우회. 시드·여정 스펙 공용. */
export async function connectPg(): Promise<Client> {
  const client = new Client({
    connectionString: toPgDsn(process.env.DATABASE_URL ?? DEFAULT_DSN),
  });
  await client.connect();
  return client;
}

/** login_id(=이메일 HMAC)로 활성 사용자 조회 — 초대·가입 계정의 id·tenant를 여정 스펙이 얻는다. */
export async function findUserByEmail(
  client: Client,
  email: string,
): Promise<{ id: string; tenantId: string } | null> {
  const { rows } = await client.query<{ id: string; tenant_id: string }>(
    `SELECT id, tenant_id FROM users WHERE login_id = $1 AND deleted_at IS NULL`,
    [emailHash(email)],
  );
  const row = rows[0];
  return row ? { id: row.id, tenantId: row.tenant_id } : null;
}

/**
 * 원문을 아는 1회용 토큰을 직접 INSERT — 메일이 console(stdout)이라 E2E가 링크를 못 읽는 대신,
 * 원문의 sha256 hex를 저장해(auth_tokens.token_hash) 브라우저로 검증·초대 링크를 탄다(ADR-0014).
 */
export async function insertAuthToken(
  client: Client,
  opts: { tenantId: string; userId: string; purpose: string; raw: string },
): Promise<void> {
  const tokenHash = createHash("sha256").update(opts.raw).digest("hex");
  await client.query(
    `INSERT INTO auth_tokens (tenant_id, user_id, purpose, token_hash, expires_at)
     VALUES ($1, $2, $3, $4, NOW() + interval '1 hour')`,
    [opts.tenantId, opts.userId, opts.purpose, tokenHash],
  );
}

/** UI로 생성한 여정 단지에 building '101' + 세대(명부 일치 301·불일치 302) 시드 — 명부·온보딩 세대 조회 전제. */
export async function seedJourneyHouseholds(client: Client, tenantId: string): Promise<void> {
  const { rows } = await client.query<{ id: string }>(
    `INSERT INTO buildings (tenant_id, name, floors) VALUES ($1, $2, 15) RETURNING id`,
    [tenantId, ROSTER_PERSON.dong],
  );
  const buildingId = rows[0].id;
  for (const unit of [ROSTER_PERSON.ho, MISMATCH_PERSON.ho]) {
    await client.query(
      `INSERT INTO households (tenant_id, building_id, floor, unit_no, status)
       VALUES ($1, $2, $3, $4, 'active')`,
      [tenantId, buildingId, Math.floor(Number(unit) / 100), Number(unit)],
    );
  }
}

async function insert(client: Client): Promise<void> {
  await client.query(
    `INSERT INTO tenants (id, name, status) VALUES ($1, 'E2E 단지', 'active')`,
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

  // 2호 세대 — 가입 여정의 명부 불일치 신청자가 붙는 유효 세대(존재해야 세대 조회가 성공).
  await client.query(
    `INSERT INTO households (id, tenant_id, building_id, floor, unit_no, status)
     VALUES ($1, $2, $3, $4, $5, 'active')`,
    [
      E2E.household2Id,
      E2E.tenantId,
      E2E.buildingId,
      FLOOR,
      Number(MISMATCH_PERSON.ho),
    ],
  );

  // 승인 완료 입주민(approved_at 과거) — 관리비 조회 스코프(FR-FEE-03)와 민원 접수 통과.
  // login_id = 이메일 HMAC · password_hash = 고정 Argon2id · email_verified_at 기록으로
  // 검증 게이트(403) 통과 — auth.setup.ts 가 이 계정으로 /auth/login 해 세션을 확립한다(ADR-0014).
  await client.query(
    `INSERT INTO users
       (id, tenant_id, household_id, status, roster_matched, approved_at,
        login_id, password_hash, email_verified_at)
     VALUES ($1, $2, $3, 'active', true, '2020-01-01T00:00:00Z', $4, $5, NOW())`,
    [E2E.userId, E2E.tenantId, E2E.householdId, emailHash(E2E.email), PASSWORD_HASH],
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
  const client = await connectPg();
  try {
    await client.query("BEGIN");
    await wipeTenant(client, E2E.tenantId);
    await wipeJourneyTenants(client);
    await insert(client);
    await seedSysAdmin(client);
    await client.query("COMMIT");
  } catch (err) {
    await client.query("ROLLBACK");
    throw err;
  } finally {
    await client.end();
  }
}

export default globalSetup;
