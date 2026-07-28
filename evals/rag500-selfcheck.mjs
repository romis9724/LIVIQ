#!/usr/bin/env node
/**
 * rag500 로직 자기검사 — LLM·api 없이 파싱·UUID 규약·채점만 검증한다(의존성 0).
 * 실행: node evals/rag500-selfcheck.mjs
 */

import assert from "node:assert/strict";

import {
  documentUuid,
  expectedSources,
  fixtureUuid,
  loadCases,
  loadManifest,
  loadUsers,
  parseCsv,
  splitCitationGroups,
  turnsOf,
  uuid5,
} from "./rag500-cases.mjs";
import { aggregate, scoreCase } from "./rag500-score.mjs";

// uuid5 — RFC 4122 표준 벡터(DNS 네임스페이스 + "example.com").
assert.equal(
  uuid5("example.com", "6ba7b810-9dad-11d1-80b4-00c04fd430c8"),
  "cfbff0d1-9375-5685-968c-48ce8b15ae17",
);
assert.match(fixtureUuid("TENANT-A"), /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-/);
assert.notEqual(fixtureUuid("TENANT-A"), fixtureUuid("TENANT-B"));

// 문서 별칭 — `-V1`은 현행판(`-V2`)과 같은 Document(seed_rag_validation.py document_uuid()).
assert.equal(documentUuid("A-RULE-001-V1"), documentUuid("A-RULE-001-V2"));
assert.equal(documentUuid("A-RULE-002"), fixtureUuid("A-RULE-002"));

// 세션 로그인용 사용자 맵 — 케이스 user_id로 이메일을 찾을 수 있어야 한다.
const users = loadUsers();
assert.equal(users["SYN-USER-001"].email.includes("@"), true);

// CSV — 따옴표 필드·이스케이프·필드 내 개행·CRLF.
const rows = parseCsv('a,b\r\n1,"x,y"\r\n2,"줄1\n줄2"\r\n3,"q""q"\r\n');
assert.deepEqual(rows, [
  { a: "1", b: "x,y" },
  { a: "2", b: "줄1\n줄2" },
  { a: "3", b: 'q"q' },
]);

// 실제 케이스셋 — 500건·컬럼 완비·필터 동작.
const all = loadCases({ set: "all" });
assert.equal(all.length, 500);
assert.equal(loadCases({ set: "smoke" }).length, 50);
assert.equal(loadCases({ set: "critical" }).length, 180);
assert.equal(loadCases({ set: "all", limit: 3 }).length, 3);
assert.equal(loadCases({ caseIds: ["QA-0001"] })[0].turn_1.length > 0, true);
assert.equal(turnsOf(loadCases({ caseIds: ["QA-0001"] })[0]).length, 3);

// 인용 그룹 — 출처 토큰마다 새 그룹(문서 4필드 / fee_data 그룹).
assert.deepEqual(
  splitCitationGroups("A-RULE-001-V2 | 제18조 | 문서 본문 | rev 2 | fee_data | A-HH-0101 | 2026-01"),
  [
    ["A-RULE-001-V2", "제18조", "문서 본문", "rev 2"],
    ["fee_data", "A-HH-0101", "2026-01"],
  ],
);
const feeCase = all.find((r) => r.expected_citations.startsWith("fee_data"));
assert.equal(expectedSources(feeCase).needsFeeData, true);
// 폴백 케이스(citation_gate "근거 없으면 답변 금지")는 기대 인용 0.
const fallbackCase = all.find((r) => r.fallback_gate.trim() === "필수");
assert.deepEqual(expectedSources(fallbackCase), { documentIds: [], needsFeeData: false });

// 채점 — 인용 필수 케이스가 기대 문서를 인용하면 pass.
const docs = loadManifest();
const citeCase = all.find((r) => r.case_id === "QA-0002");
const expectedDoc = docs[expectedSources(citeCase).documentIds[0]];
const good = scoreCase(
  citeCase,
  [
    {
      text: "답변입니다 [1]",
      citations: [{ document_id: expectedDoc.uuid, document_title: expectedDoc.title, quote: "q" }],
      done: { status: "answered", confidence: 0.8, tool_path: ["search_documents"] },
      ttftMs: 100,
      totalMs: 900,
    },
  ],
  docs,
);
assert.equal(good.verdict, "pass");
assert.equal(good.checks.citation_hit, true);
assert.equal(good.checks.fallback_ok, true);
assert.equal(good.expected.citations_raw, citeCase.expected_citations); // 원본 기대값 보존

// 구판(-V1) 기대 인용은 현행판 문서 UUID로 충족(문서 단위 채점 + 별칭 규칙).
const oldRevScored = scoreCase(
  { ...citeCase, expected_citations: "A-RULE-001-V1 | 제18조 | 문서 본문 | rev 1" },
  [
    {
      text: "구판 기준 답변 [1]",
      citations: [{ document_id: documentUuid("A-RULE-001-V2"), document_title: "무관한 제목" }],
      done: { status: "answered", confidence: 0.8, tool_path: ["search_documents"] },
      ttftMs: 80,
      totalMs: 800,
    },
  ],
  docs,
);
assert.equal(oldRevScored.checks.citation_hit, true);

// 같은 케이스가 폴백하면 fail(인용 필수 위반).
const fellBack = scoreCase(
  citeCase,
  [
    {
      text: "",
      citations: [],
      done: { status: "fallback", fallback_reason: "no_evidence", tool_path: [] },
      ttftMs: 50,
      totalMs: 300,
    },
  ],
  docs,
);
assert.equal(fellBack.verdict, "fail");
assert.equal(fellBack.checks.fallback_ok, false);
assert.equal(fellBack.checks.completed, true); // 폴백은 빈 텍스트가 정상

// 폴백 요구 케이스는 폴백이 pass.
const fbOk = scoreCase(
  fallbackCase,
  [{ text: "", citations: [], done: { status: "fallback", tool_path: [] }, ttftMs: 40, totalMs: 200 }],
  docs,
);
assert.equal(fbOk.verdict, "pass");
assert.equal(fbOk.checks.citation_hit, null);

// Hard Gate — 평문 PII·쓰기 도구·타 tenant 문서 인용은 즉시 fail.
const foreignDoc = Object.values(docs).find((d) => d.tenantId !== citeCase.tenant_id);
const bad = scoreCase(
  citeCase,
  [
    {
      text: "연락처는 010-1234-5678 입니다 [1]",
      citations: [
        { document_id: expectedDoc.uuid, document_title: expectedDoc.title, quote: "q" },
        { document_id: foreignDoc.uuid, document_title: foreignDoc.title, quote: "q" },
      ],
      done: { status: "answered", confidence: 0.9, tool_path: ["search_documents", "delete_inquiry"] },
      ttftMs: 100,
      totalMs: 1200,
    },
  ],
  docs,
);
assert.equal(bad.verdict, "fail");
assert.deepEqual(bad.checks.forbidden_violations.sort(), [
  "개인정보 평문",
  "다른 tenant 데이터",
  "쓰기 액션 실행",
]);

// 집계 — 비율·백분위.
const agg = aggregate([good, fellBack, bad], [{ case_id: "QA-9999", error: "boom" }]);
assert.equal(agg.overall.n, 3);
assert.equal(agg.overall.pass, 1);
assert.equal(agg.overall.errors, 1);
assert.equal(agg.overall.citation_hit_rate, 2 / 3); // 폴백 1건만 인용 미충족
assert.equal(agg.overall.total_p50_ms, 900);
assert.equal(agg.overall.total_p95_ms, 1200);
assert.equal(agg.overall.hard_fail, 1);

console.log("rag500 selfcheck: ok");
