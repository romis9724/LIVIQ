/**
 * 채점기 v2 경로 단위 테스트 (node --test). 순수함수라 인프라 불필요.
 * v2 채점의 계약을 고정한다: behavior·도구선택 별도집계·빈결과 카드 answered·as_of 경고.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { aggregate, scoreCase } from "./rag500-score.mjs";

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
