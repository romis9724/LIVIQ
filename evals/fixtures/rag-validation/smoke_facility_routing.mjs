/**
 * 시설·평면도 도구 라우팅 스모크 (H15-2 R22) — 정식 측정이 아니라 **동작 확인**이다.
 *
 * 왜 필요한가: Critical 180은 합성 fixture(해오름아파트)를 쓰는데 그 단지에는 시설 데이터가
 * 없다. 기준선 3회(540 케이스 실행)의 도구 호출 분포를 세어보니 시설 계열이 사실상 미측정이었다:
 *   search_documents 905 · search_facility_graph 18(우연) · find_in_floor_plan 17(오호출 포함)
 *   get_facilities **0** · get_overdue_checks **0**
 * 시설 데이터는 첫마을 4단지 tenant에 있으므로 이 단지를 대상으로 확인한다.
 *
 * 확인 대상은 **정답 내용이 아니라 도구 선택**이다. 앞서 평면도 도구가 규약 조항 질문을
 * 가로채는 것을 확인했고(설명문 보강으로도 안 고쳐졌다), 역방향(설비 질문이 문서 검색으로
 * 새는 것)도 봐야 한다 — 커밋 #108이 get_facilities에서 같은 문제를 고친 전례가 있다.
 *
 * 기대값은 DB·Neo4j 실데이터로 확인한 것만 적었다(정답표 결함 27건에서 배운 것):
 *   facilities 37건 전부 status=normal · next_check_at 전부 NULL(점검 기한 데이터 없음)
 *   Neo4j 첫마을 Incident 1건(101동 1호기 승강기 — 덜컹 소음·3층 정차 지연 / 가이드 롤러 마모)
 *   PlanDevice 80개(device_type=콘센트, room=안방·거실·침실1·2·주방·욕실1·2·팬트리)
 *
 * 한계: dev 헤더는 역할이 RESIDENT+MANAGER+STAFF로 고정돼 **역할 분리 검증은 못 한다**
 * (get_facilities·get_overdue_checks·search_facility_graph는 FACILITY|MANAGER 전용).
 * 인가 검증은 apps/api 통합 테스트가 담당한다 — 여기서는 라우팅만 본다.
 */

import { postSse } from "../../sse.mjs";

const API = process.env.LIVIQ_EVAL_API_URL ?? "http://localhost:8000";
const TENANT = "11111111-1111-1111-1111-111111111111";
// 레이트 리밋은 사용자당 분 10건 — 계정을 돌려 쓴다. 전원 평면도 보유 세대(585b7e70…) 소속.
const USERS = [
  "fa8717f0-d247-4f03-ab5d-4b37fd560ff2",
  "4fc052de-8900-4499-8947-9f347f960c60",
  "88aa6f7a-ca24-467f-b931-122fe574d7a8",
  "28989e29-e703-4228-b696-10ae0eb034aa",
  "2c62e75d-1db9-45ea-946b-a44b190bb916",
  "6cc08221-1359-49f1-a80e-9869e41773e6",
];

// [질문, 기대 도구, 근거(실데이터 확인 내용)]
const CASES = [
  // ── get_facilities: 설비 목록·대수·상태 (기준선 호출 0회) ────────────────
  ["단지에 승강기가 몇 대 있나요?", "get_facilities", "EL 코드 12건"],
  ["우리 단지에 어떤 공용 설비가 있나요?", "get_facilities", "37건(EL12·CM7·FR6·WT4…)"],
  ["설비 중에 지금 고장이나 이상 상태인 게 있나요?", "get_facilities", "37건 전부 normal"],
  ["전기차 충전기가 설치돼 있나요?", "get_facilities", "EC-CMN-02 EV 완속충전기 8기"],
  ["소방 관련 설비는 몇 개인가요?", "get_facilities", "FR 코드 6건"],
  ["급수 설비 상태 알려주세요.", "get_facilities", "WT 코드 4건"],
  ["101동 승강기 상태가 어떤가요?", "get_facilities", "EL-101-01 normal"],

  // ── get_overdue_checks: 점검 기한 (기준선 호출 0회) ─────────────────────
  // 데이터가 없으므로 "없다"가 정답 — 도구를 골랐는지만 본다.
  ["점검 기한이 지난 설비가 있나요?", "get_overdue_checks", "next_check_at 전부 NULL → 없음"],
  ["점검이 임박한 설비 알려주세요.", "get_overdue_checks", "동일 — 데이터 없음"],
  ["이번 달에 점검해야 할 설비가 뭐가 있죠?", "get_overdue_checks", "동일 — 데이터 없음"],

  // ── search_facility_graph: 유사 장애·연결 설비 원인 후보 ────────────────
  ["승강기 운행 중에 덜컹거리는 소음이 납니다. 원인 후보가 뭘까요?", "search_facility_graph", "Incident: 가이드 롤러 마모"],
  ["엘리베이터가 3층에서 정차가 지연됩니다. 비슷한 이력이 있나요?", "search_facility_graph", "동일 Incident"],
  ["과거에 비슷한 승강기 장애를 어떻게 조치했나요?", "search_facility_graph", "resolution: 응급 조정"],

  // ── find_in_floor_plan: 세대 내부 위치 ─────────────────────────────────
  ["우리 집 안방에 콘센트가 몇 개 있나요?", "find_in_floor_plan", "PlanDevice 안방 콘센트 6개"],
  ["거실 콘센트 위치를 알려주세요.", "find_in_floor_plan", "거실 콘센트 6개"],
  ["주방에 콘센트 있어요?", "find_in_floor_plan", "주방 콘센트 4개"],
  ["우리 집 방 구조가 어떻게 되나요?", "find_in_floor_plan", "PlanRoom 28개"],

  // ── 오라우팅 감시: 문서로 답해야 하는 질문에 시설·평면도 도구가 끼는지 ──
  // 앞서 "전용부분과 공용부분의 범위"(규약 제5조)에 find_in_floor_plan이 3회 호출됐다.
  ["전용부분과 공용부분의 범위는 규약에 어떻게 정해져 있나요?", "search_documents", "규약 제5조 — 문서 질문"],
  ["층간소음 관련 규정을 알려주세요.", "search_documents", "규약 제60조 — 문서 질문"],
  ["장기수선충당금 적립 요율이 어떻게 되나요?", "search_documents", "규약 제71조 — 문서 질문"],
];

const FACILITY_TOOLS = new Set([
  "get_facilities",
  "get_overdue_checks",
  "search_facility_graph",
  "find_in_floor_plan",
]);

async function ask(question, index) {
  return postSse(
    `${API}/assistant/ask`,
    { question },
    {
      "content-type": "application/json",
      "X-Dev-Tenant-Id": TENANT,
      "X-Dev-User-Id": USERS[index % USERS.length],
    },
  );
}

const results = [];
for (const [index, [question, expectedTool, basis]] of CASES.entries()) {
  try {
    const { done, citations } = await ask(question, index);
    const tools = done?.tool_path ?? [];
    results.push({
      question,
      expectedTool,
      basis,
      status: done?.status ?? null,
      tools,
      hit: tools.includes(expectedTool),
      // 문서 질문에 시설·평면도 도구가 끼었는지(오라우팅)
      strayFacility: expectedTool === "search_documents" && tools.some((t) => FACILITY_TOOLS.has(t)),
      citations: citations.length,
    });
  } catch (error) {
    results.push({ question, expectedTool, basis, error: String(error) });
  }
  await new Promise((resolve) => setTimeout(resolve, 1400)); // 레이트 리밋 여유
}

const byTool = {};
for (const r of results) {
  const b = (byTool[r.expectedTool] ??= { n: 0, hit: 0 });
  b.n += 1;
  if (r.hit) b.hit += 1;
}

console.log(`질의 ${results.length}건 | 오류 ${results.filter((r) => r.error).length}건\n`);
console.log("기대 도구별 선택 정확도:");
for (const [tool, b] of Object.entries(byTool)) {
  console.log(`  ${tool.padEnd(22)} ${String(b.hit).padStart(2)}/${b.n}`);
}
const stray = results.filter((r) => r.strayFacility);
console.log(`\n문서 질문에 시설·평면도 도구 오호출: ${stray.length}건`);
for (const r of stray) console.log(`  · ${r.question} → ${r.tools.join(",")}`);

console.log("\n케이스별:");
for (const r of results) {
  const mark = r.error ? "!" : r.hit ? "O" : "X";
  console.log(`${mark} [${r.expectedTool}] ${r.question}`);
  console.log(
    `    상태=${r.status ?? r.error} | 호출=${(r.tools ?? []).join(",") || "(없음)"} | 인용=${r.citations ?? 0} | 근거=${r.basis}`,
  );
}
