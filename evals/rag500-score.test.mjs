/**
 * 채점기 v2 경로 단위 테스트 (node --test). 순수함수라 인프라 불필요.
 * v2 채점의 계약을 고정한다: behavior·도구선택 별도집계·빈결과 카드 answered·as_of 경고.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { aggregate, deriveBackend, scoreCase } from "./rag500-score.mjs";

const DOCS = {}; // 문서 매칭 없는 케이스는 docs 비어도 됨

// v2 CSV 행 최소 형태(scoreCase가 읽는 컬럼만).
function v2row(over = {}) {
  return {
    case_id: "V2-QA-0001",
    category: "관리규약 조항",
    execution_set: "Smoke",
    priority: "P2",
    conversation_type: "단일",
    tenant_id: "11111111-1111-1111-1111-111111111111",
    forbidden_content: "",
    expected_citations: "",
    expected_tool: "",
    acceptable_tools: "",
    expected_behavior: "answered",
    as_of: "",
    expected_facts: "",
    turn_1: "질문",
    ...over,
  };
}

function turn(over = {}) {
  return {
    text: "답변입니다 [1]",
    citations: [],
    done: { status: "answered", tool_path: [] },
    ttftMs: 10,
    totalMs: 100,
    ...over,
  };
}

test("v2 감지 — expected_behavior 있으면 v2 경로(as_of 컬럼 반영)", () => {
  const r = scoreCase(v2row({ as_of: "2026-07" }), [turn()], DOCS, { asOf: "2026-07-30" });
  assert.equal(r.checks.behavior_ok, true);
  assert.equal(r.checks.as_of_stale, false);
});

test("behavior_ok — answered 기대에 fallback이면 실패", () => {
  const r = scoreCase(v2row({ expected_behavior: "answered" }), [
    turn({ done: { status: "fallback", tool_path: [] } }),
  ], DOCS);
  assert.equal(r.checks.behavior_ok, false);
  assert.equal(r.verdict, "fail");
});

test("빈 결과 카드 승격 — fallback 기대에 answered면 실패(없음도 answered가 정답)", () => {
  // 시설 '없음' 케이스: expected_behavior=answered(카드 승격). 폴백하면 실패.
  const r = scoreCase(
    v2row({ expected_behavior: "answered", expected_tool: "get_overdue_checks" }),
    [turn({ done: { status: "answered", tool_path: ["get_overdue_checks"] } })],
    DOCS,
  );
  assert.equal(r.checks.behavior_ok, true);
  assert.equal(r.checks.tool_selection, true);
});

test("도구 선택 정확도는 답변 pass와 합산 안 함 — 도구 틀려도 답변 pass 가능", () => {
  // expected_tool=get_facilities인데 search_documents 호출: tool_selection=false지만
  // behavior=answered·인용 없음(미채점)이면 verdict는 pass여야 한다.
  const r = scoreCase(
    v2row({ expected_tool: "get_facilities", expected_behavior: "answered" }),
    [turn({ done: { status: "answered", tool_path: ["search_documents"] } })],
    DOCS,
  );
  assert.equal(r.checks.tool_selection, false);
  assert.equal(r.verdict, "pass"); // 도구 틀려도 답변은 pass — 별도 지표
});

test("도구 선택 — expected_tool 없으면 미채점(null)", () => {
  const r = scoreCase(v2row({ expected_tool: "", expected_behavior: "fallback" }), [
    turn({ done: { status: "fallback", tool_path: [] } }),
  ], DOCS);
  assert.equal(r.checks.tool_selection, null);
});

test("as_of 불일치 경고 — 라벨 월 ≠ 측정 월", () => {
  const r = scoreCase(v2row({ as_of: "2026-07" }), [turn()], DOCS, { asOf: "2026-09-01" });
  assert.equal(r.checks.as_of_stale, true);
  assert.ok(r.notes.some((n) => n.includes("as_of 불일치")));
});

test("tool 인용 매칭 — tool:get_fees 기대에 tool_path get_fees면 hit", () => {
  const r = scoreCase(
    v2row({ expected_citations: "tool:get_fees", expected_tool: "get_fees" }),
    [turn({ done: { status: "answered", tool_path: ["get_fees"] } })],
    DOCS,
  );
  assert.equal(r.checks.citation_hit, true);
});

test("PII 하드 게이트 — 응답에 전화번호 원문이면 fail", () => {
  const r = scoreCase(
    v2row({ forbidden_content: "개인정보 평문", expected_behavior: "fallback" }),
    [
      turn({
        text: "담당자 연락처는 010-1234-5678 입니다",
        done: { status: "fallback", tool_path: [] },
      }),
    ],
    DOCS,
  );
  assert.equal(r.hard_fail, true);
  assert.equal(r.verdict, "fail");
});

test("v1 회귀 — 서술형 expected_behavior는 v1 경로(v2 오판 금지)", () => {
  // v1 CSV도 expected_behavior 컬럼이 있으나 "근거 기반 답변" 서술형 → v1 채점.
  const v1 = {
    case_id: "QA-0001",
    category: "관리규약·공지·생활 안내",
    execution_set: "Smoke",
    priority: "P2",
    conversation_type: "단일",
    tenant_id: "TENANT-A",
    forbidden_content: "",
    expected_citations: "",
    expected_behavior: "근거 기반 답변",
    citation_gate: "필수",
    fallback_gate: "해당 없음",
    turn_1: "질문",
  };
  const r = scoreCase(v1, [turn()], DOCS);
  // v1 경로는 behavior_ok 키가 없고 tool_selection도 없다(v2 전용).
  assert.equal(r.checks.tool_selection, undefined);
  assert.equal(r.checks.behavior_ok, undefined);
});

test("집계 — 도구 선택은 tool_accuracy로 별도, pass에 안 섞임", () => {
  const results = [
    scoreCase(
      v2row({ case_id: "A", expected_tool: "get_facilities", expected_behavior: "answered" }),
      [turn({ done: { status: "answered", tool_path: ["search_documents"] } })],
      DOCS,
    ),
    scoreCase(
      v2row({ case_id: "B", expected_tool: "get_facilities", expected_behavior: "answered" }),
      [turn({ done: { status: "answered", tool_path: ["get_facilities"] } })],
      DOCS,
    ),
  ];
  const agg = aggregate(results);
  assert.equal(agg.overall.pass, 2); // 둘 다 답변 pass
  assert.equal(agg.overall.tool_scored, 2);
  assert.equal(agg.overall.tool_hit, 1); // 도구는 1건만 정답
  assert.equal(agg.overall.tool_accuracy, 0.5);
});

// ── 복합 질의(required_tools, AND) ───────────────────────────────────────────

test("required_tools — 전부 호출되면 pass(hit===total)", () => {
  const r = scoreCase(
    v2row({
      required_tools: "get_fees,search_documents",
      expected_behavior: "answered",
    }),
    [turn({ done: { status: "answered", tool_path: ["get_fees", "search_documents"] } })],
    DOCS,
  );
  assert.deepEqual(r.checks.tool_selection, { hit: 2, total: 2, pass: true });
  assert.deepEqual(r.expected.required_tools, ["get_fees", "search_documents"]);
});

test("required_tools — 부분 호출은 hit<total·pass=false(답변 pass와 별개)", () => {
  const r = scoreCase(
    v2row({
      required_tools: "get_fees,search_documents",
      expected_behavior: "answered",
    }),
    [turn({ done: { status: "answered", tool_path: ["get_fees"] } })],
    DOCS,
  );
  assert.deepEqual(r.checks.tool_selection, { hit: 1, total: 2, pass: false });
  assert.equal(r.verdict, "pass"); // 도구 부분호출이어도 답변은 pass — 별도 지표
});

test("required_tools 없으면 단일 expected_tool 로직 불변(하위호환)", () => {
  const r = scoreCase(
    v2row({ expected_tool: "get_facilities", expected_behavior: "answered", required_tools: "" }),
    [turn({ done: { status: "answered", tool_path: ["search_documents"] } })],
    DOCS,
  );
  assert.equal(r.checks.tool_selection, false); // boolean 그대로
});

test("집계 — 복합 완전호출률(분수 합산)과 tool_accuracy(완전호출) 병기", () => {
  const results = [
    // 완전호출: hit 2/2, pass
    scoreCase(
      v2row({ case_id: "A", required_tools: "get_fees,search_documents", expected_behavior: "answered" }),
      [turn({ done: { status: "answered", tool_path: ["get_fees", "search_documents"] } })],
      DOCS,
    ),
    // 부분호출: hit 1/2, fail
    scoreCase(
      v2row({ case_id: "B", required_tools: "get_fees,search_documents", expected_behavior: "answered" }),
      [turn({ done: { status: "answered", tool_path: ["get_fees"] } })],
      DOCS,
    ),
    // 단일 expected_tool 정답(boolean 카운트 유지 확인)
    scoreCase(
      v2row({ case_id: "C", expected_tool: "get_fees", expected_behavior: "answered" }),
      [turn({ done: { status: "answered", tool_path: ["get_fees"] } })],
      DOCS,
    ),
  ];
  const agg = aggregate(results);
  assert.equal(agg.overall.pass, 3); // 답변은 셋 다 pass
  assert.equal(agg.overall.required_cases, 2);
  assert.equal(agg.overall.required_hit_sum, 3); // 2 + 1
  assert.equal(agg.overall.required_total_sum, 4); // 2 + 2
  assert.equal(agg.overall.required_call_rate, 0.75); // 3/4
  // tool_accuracy: 복합 완전호출(A) + 단일 정답(C) = 2, 복합 부분(B)는 미완 → 2/3
  assert.equal(agg.overall.tool_scored, 3);
  assert.equal(agg.overall.tool_hit, 2);
});

test("집계 — required_tools 케이스 없으면 required_call_rate null(회귀)", () => {
  const results = [
    scoreCase(v2row({ case_id: "A", expected_tool: "get_fees" }), [turn()], DOCS),
  ];
  const agg = aggregate(results);
  assert.equal(agg.overall.required_cases, 0);
  assert.equal(agg.overall.required_call_rate, null);
});

// ── GraphRAG 비교(§6) ────────────────────────────────────────────────────────

test("deriveBackend — expected_tool → 비교 백엔드 매핑", () => {
  assert.equal(deriveBackend("search_documents"), "pgvector");
  assert.equal(deriveBackend("search_facility_graph"), "neo4j");
  assert.equal(deriveBackend("trace_home_device_issue"), "neo4j");
  assert.equal(deriveBackend("get_fees"), null);
  assert.equal(deriveBackend(""), null);
  assert.equal(deriveBackend(undefined), null);
});

test("by_backend 버킷 — pgvector·neo4j 나란히 집계, category 오염 없음", () => {
  // 도구 hit 여부로 tool_accuracy가 백엔드 버킷에도 계산되는지 확인.
  const doc = (case_id, hit) =>
    scoreCase(
      v2row({ case_id, category: "관리규약 조항", expected_tool: "search_documents" }),
      [turn({ done: { status: "answered", tool_path: hit ? ["search_documents"] : [] } })],
      DOCS,
    );
  const graph = (case_id) =>
    scoreCase(
      v2row({ case_id, category: "시설 그래프", expected_tool: "search_facility_graph" }),
      [turn({ done: { status: "answered", tool_path: ["search_facility_graph"] } })],
      DOCS,
    );
  const results = [doc("A", true), doc("B", false), graph("C"), graph("D")];
  const agg = aggregate(results);

  const pg = agg.by_backend.find((b) => b.key === "backend:pgvector");
  const ng = agg.by_backend.find((b) => b.key === "backend:neo4j");
  assert.equal(agg.by_backend.length, 2);
  assert.equal(pg.n, 2);
  assert.equal(ng.n, 2);
  assert.equal(pg.tool_accuracy, 0.5); // 문서 경로 1/2 도구 적중
  assert.equal(ng.tool_accuracy, 1); // 그래프 경로 2/2 도구 적중
  // by_category에 backend 키가 안 섞이고, 두 카테고리가 그대로 나온다.
  assert.ok(agg.by_category.every((b) => !b.key.startsWith("backend:")));
  assert.ok(agg.by_category.some((b) => b.key === "관리규약 조항"));
  assert.ok(agg.by_category.some((b) => b.key === "시설 그래프"));
});

test("pairs — 같은 pair_id의 pgvector행+neo4j행이 한 항목 양 슬롯으로", () => {
  const doc = scoreCase(
    v2row({ case_id: "D1", pair_id: "p01", expected_tool: "search_documents" }),
    [turn({ done: { status: "answered", tool_path: ["search_documents"] } })],
    DOCS,
  );
  const graph = scoreCase(
    v2row({ case_id: "G1", pair_id: "p01", expected_tool: "search_facility_graph" }),
    [turn({ done: { status: "answered", tool_path: ["search_facility_graph"] } })],
    DOCS,
  );
  const agg = aggregate([graph, doc]); // 입력 순서 무관
  assert.equal(agg.pairs.length, 1);
  assert.equal(agg.pairs[0].pair_id, "p01");
  assert.ok(agg.pairs[0].pgvector !== null);
  assert.ok(agg.pairs[0].neo4j !== null);
  assert.equal(agg.pairs[0].pgvector.pass, true);
  assert.equal(typeof agg.pairs[0].neo4j.total_ms, "number");
});

test("pairs — 한 쪽만 있는 pair_id는 반대 슬롯 null(불완전 쌍)", () => {
  const doc = scoreCase(
    v2row({ case_id: "D1", pair_id: "p02", expected_tool: "search_documents" }),
    [turn()],
    DOCS,
  );
  const agg = aggregate([doc]);
  assert.equal(agg.pairs.length, 1);
  assert.ok(agg.pairs[0].pgvector !== null);
  assert.equal(agg.pairs[0].neo4j, null);
});

test("하위호환 — pair_id/backend 없는 기존 v2는 pairs=[]·by_backend=[]", () => {
  const results = [
    scoreCase(v2row({ case_id: "A", expected_tool: "get_fees" }), [turn()], DOCS),
    scoreCase(v2row({ case_id: "B", expected_tool: "" }), [turn()], DOCS),
  ];
  const agg = aggregate(results);
  assert.deepEqual(agg.pairs, []);
  assert.deepEqual(agg.by_backend, []);
  assert.equal(agg.overall.n, 2);
  assert.equal(agg.by_category.length, 1); // 한 카테고리
});
