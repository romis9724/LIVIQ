/**
 * quality-cases-500 로더 — CSV 파싱 · fixture ID→UUID 규약 · 기대 인용 파싱.
 *
 * 파싱 규칙은 fixtures/rag-validation/verify_cases.py와 동일하게 유지한다(출처 토큰 정규식·
 * `|`/`,` 혼용 구분자). 규칙이 갈라지면 검수 스크립트가 통과한 케이스를 측정기가 오판한다.
 *
 * ID 규약(시드 스크립트와 공유): uuid5(NAMESPACE_URL, "liviq-rag-validation:" + fixtureId).
 * tenant·user·household·document 전부 동일 — 의존성 0으로 node crypto에서 직접 계산한다.
 */

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const FIXTURES = join(HERE, "fixtures", "rag-validation");
const NAMESPACE_URL = "6ba7b811-9dad-11d1-80b4-00c04fd430c8";
const ID_PREFIX = "liviq-rag-validation:";

// 출처 토큰: 문서ID(A-RULE-001-V2 등) 또는 fee_data. 세대 id(A-HH-*)는 fee 그룹 속성이지 출처가 아니다.
const SOURCE_RE = /^(?:[A-C]-(?!HH-)[A-Z]+-\d+(?:-V\d+)?|fee_data)$/;
const NO_CITATION_GATES = new Set(["금지", "없음", "해당 없음", "n/a", "N/A"]);
// 케이스셋 라벨 결함(질문 주제가 기대 출처 본문에 없음) — 파일 주석에 판정 근거가 있다.
const LABEL_DEFECTS = JSON.parse(
  readFileSync(join(FIXTURES, "citation-label-defects.json"), "utf8"),
).defects;

/** RFC4180 최소 파서 — 따옴표 필드·필드 내 개행·이스케이프("")·CRLF·BOM 처리. */
export function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let quoted = false;
  const src = text.charCodeAt(0) === 0xfeff ? text.slice(1) : text;
  for (let i = 0; i < src.length; i++) {
    const ch = src[i];
    if (quoted) {
      if (ch !== '"') field += ch;
      else if (src[i + 1] === '"') (field += '"'), i++;
      else quoted = false;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === ",") (row.push(field), (field = ""));
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && src[i + 1] === "\n") i++;
      row.push(field);
      field = "";
      if (row.length > 1 || row[0] !== "") rows.push(row);
      row = [];
    } else field += ch;
  }
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  const [header, ...body] = rows;
  return body.map((cells) =>
    Object.fromEntries(header.map((name, i) => [name, cells[i] ?? ""])),
  );
}

/** uuid5(name, ns) — SHA-1 기반(RFC 4122 §4.3). 의존성 없이 node crypto만 사용. */
export function uuid5(name, namespace = NAMESPACE_URL) {
  const ns = Buffer.from(namespace.replace(/-/g, ""), "hex");
  const digest = createHash("sha1")
    .update(Buffer.concat([ns, Buffer.from(name, "utf8")]))
    .digest();
  const bytes = Buffer.from(digest.subarray(0, 16));
  bytes[6] = (bytes[6] & 0x0f) | 0x50; // version 5
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // RFC 4122 variant
  const hex = bytes.toString("hex");
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20),
  ].join("-");
}

/** fixture ID(TENANT-A·SYN-USER-001·A-RULE-001-V2 …) → DB UUID. */
export function fixtureUuid(fixtureId) {
  return uuid5(`${ID_PREFIX}${fixtureId}`);
}

/**
 * 문서 fixture ID → Document UUID. `-V1`은 독립 문서가 아니라 현행판(`-V2`)의 구 버전으로
 * 적재된다 — seed_rag_validation.py document_uuid()와 같은 별칭 규칙(같은 UUID).
 */
export function documentUuid(documentId) {
  return fixtureUuid(documentId.endsWith("-V1") ? `${documentId.slice(0, -3)}-V2` : documentId);
}

/** manifest 문서 40건 → { [documentId]: { tenantId, title, uuid } }. */
export function loadManifest() {
  const manifest = JSON.parse(readFileSync(join(FIXTURES, "manifest.json"), "utf8"));
  return Object.fromEntries(
    manifest.documents.map((d) => [
      d.document_id,
      { tenantId: d.tenant_id, title: d.title, uuid: documentUuid(d.document_id) },
    ]),
  );
}

/** 합성 사용자 15명 → { [userId]: { email, tenantId, role } } (세션 로그인용). */
export function loadUsers() {
  const users = JSON.parse(readFileSync(join(FIXTURES, "seed", "users.json"), "utf8"));
  return Object.fromEntries(
    users.map((u) => [u.user_id, { email: u.email, tenantId: u.tenant_id, role: u.role }]),
  );
}

/** 출처 토큰이 나올 때마다 새 그룹 — 카테고리별 필드 수(3·4·가변)를 흡수(verify_cases.py 동일). */
export function splitCitationGroups(raw) {
  const groups = [];
  for (const token of raw.split("|").map((s) => s.trim())) {
    if (!token) continue;
    if (SOURCE_RE.test(token) || groups.length === 0) groups.push([token]);
    else groups[groups.length - 1].push(token);
  }
  return groups;
}

/** 기대 인용 → { documentIds, needsFeeData }. citation_gate가 "없음"류면 기대 인용 0. */
export function expectedSources(row) {
  if (NO_CITATION_GATES.has(row.citation_gate.trim())) {
    return { documentIds: [], needsFeeData: false };
  }
  const documentIds = [];
  let needsFeeData = false;
  for (const [source] of splitCitationGroups(row.expected_citations)) {
    if (source === "fee_data") needsFeeData = true;
    else if (SOURCE_RE.test(source) && !documentIds.includes(source)) documentIds.push(source);
  }
  // 라벨 결함 보정 — 질문 주제가 본문에 없는 기대 출처는 인용이 불가능하고, 남겨두면
  // 오답(급수 질문에 엘리베이터 문서 인용)을 정답화한다. 라벨이 다른 문서를 가리킨 경우는
  // 정답 출처(add)로 교체해 테스트를 살린다. 근거는 문서 본문이며 목록·이유는
  // fixtures/rag-validation/citation-label-defects.json(감사: audit_citation_labels.mjs).
  const defect = LABEL_DEFECTS[row.case_id];
  if (!defect) return { documentIds, needsFeeData, droppedIds: [], addedIds: [] };
  const drop = defect.drop ?? [];
  const add = (defect.add ?? []).filter((id) => !documentIds.includes(id));
  const kept = [...documentIds.filter((id) => !drop.includes(id)), ...add];
  return {
    documentIds: kept,
    needsFeeData,
    droppedIds: documentIds.filter((id) => drop.includes(id)),
    addedIds: add,
  };
}

/** 케이스 로드 + 필터. set은 execution_set 라벨(smoke|critical|full) 또는 all. */
export function loadCases({ set = "smoke", caseIds = [], limit = null } = {}) {
  const rows = parseCsv(readFileSync(join(FIXTURES, "quality-cases-500.csv"), "utf8"));
  const wanted = set.toLowerCase();
  const filtered = rows.filter((r) => {
    if (caseIds.length > 0) return caseIds.includes(r.case_id);
    return wanted === "all" || r.execution_set.toLowerCase() === wanted;
  });
  return limit === null ? filtered : filtered.slice(0, limit);
}

/** 케이스의 턴 목록(빈 턴 제외). */
export function turnsOf(row) {
  return [row.turn_1, row.turn_2, row.turn_3].map((t) => t.trim()).filter(Boolean);
}
