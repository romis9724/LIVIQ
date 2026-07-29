/**
 * 첫마을 관리규약 조항 인용 동작 확인 (H15-2 #3) — 정식 측정이 아니라 **동작 확인**이다.
 *
 * Critical 180은 해오름아파트(fixture, 청크 평균 72토큰)를 쓰므로 청커 수정이 발현되지
 * 않는다. 청커·clause 수정이 실문서에서 실제로 조항 단위 인용을 만들어내는지만 본다.
 *
 * 기대 조항은 규약 본문에서 확인한 것만 적었다(라벨 결함 27건에서 배운 것 — 본문에 없는
 * 출처를 기대하면 측정이 아니라 자기 확인이 된다).
 */

import { postSse } from "../../sse.mjs";

const API = process.env.LIVIQ_EVAL_API_URL ?? "http://localhost:8000";
const TENANT = "11111111-1111-1111-1111-111111111111";
// 레이트 리밋은 사용자당 분 10건(RATE_LIMIT_USER_PER_MIN) — 계정을 돌려 쓴다.
const USERS = [
  "fa8717f0-d247-4f03-ab5d-4b37fd560ff2",
  "4fc052de-8900-4499-8947-9f347f960c60",
  "88aa6f7a-ca24-467f-b931-122fe574d7a8",
  "28989e29-e703-4228-b696-10ae0eb034aa",
  "2c62e75d-1db9-45ea-946b-a44b190bb916",
  "6cc08221-1359-49f1-a80e-9869e41773e6",
];

// [질문, 기대 조항 번호(본문 확인), 근거 요지]
const CASES = [
  ["층간소음으로 야간에 금지되는 행위는 무엇인가요?", 60, "오후 10시~오전 6시 뛰거나 문 크게 닫기·망치질 금지"],
  ["밤에 몇 시부터 몇 시까지 세대 내부 수리를 하면 안 되나요?", 60, "오후 10시부터 다음날 오전 6시"],
  ["동별 대표자는 총 몇 명을 선출하나요?", 17, "총 5명 정원"],
  ["동별 대표자 선거구별 최소·최대 세대수 차이 제한이 있나요?", 17, "2배 이하"],
  ["동별 대표자 자리가 비면 며칠 안에 다시 뽑나요?", 21, "60일 이내"],
  ["보궐선거에서 잔여임기가 얼마 미만이면 선출하지 않을 수 있나요?", 21, "180일 미만"],
  ["동별 대표자 해임은 몇 분의 몇 이상 요구로 진행되나요?", 20, "선거구 10분의 1 이상"],
  ["선거관리위원회 위원은 몇 명으로 구성하나요?", 39, "500세대 이상 5~9명"],
  ["선거관리위원이 궐위되면 며칠 안에 위촉하나요?", 42, "30일"],
  ["선거관리위원장은 어떻게 선출하나요?", 42, "위원 중 호선"],
  ["장기수선충당금 적립 요율은 연도별로 어떻게 되나요?", 71, "2013.05~2021.12 0.60%, 2022.01~2025.05 1.44%"],
  ["관리규약의 목적은 무엇인가요?", 1, "공동주택관리법 제18조제2항에 따라 관리·사용에 필요한 사항 규정"],
  ["이 규약에서 입주자는 어떻게 정의되나요?", 3, "공동주택의 소유자 또는 그 소유자를 대리하는 자"],
  ["관리대상물은 어디에 정해져 있나요?", 4, "별표 1"],
  ["전용부분과 공용부분의 범위는 어디에 있나요?", 5, "별표 2·별표 3"],
  ["주거공용부분에는 어떤 시설이 포함되나요?", 5, "복도·계단·현관·승강기"],
  ["입주자가 집을 임대한 경우 관리비 체납분은 누가 책임지나요?", 13, "해당 입주자가 부담"],
  ["관리주체가 점검을 위해 전유부분에 들어오려 할 때 거부할 수 있나요?", 13, "특별한 사유 없이 거부 불가"],
  ["의결권을 서면이나 전자적 방법으로 행사할 수 있나요?", 12, "서면 또는 전자적 방법 가능"],
  ["가구주가 아닌 사람이 의결권을 대리 행사할 수 있나요?", 12, "위임장 첨부 시 가능"],
  ["경비원에게 폭언하면 어떻게 되나요?", "14조의2", "공동주택 내 괴롭힘 금지"],
  ["입주자대표회의가 주택관리업자 직원 인사에 간섭할 수 있나요?", 14, "부당 간섭 금지"],
  ["기존 주택관리업자의 입찰 참가를 제한하려면 언제까지 해야 하나요?", 52, "계약만료 1개월 전"],
  ["어린이집 위탁 계약의 중요계약내용은 누구 동의가 필요한가요?", 59, "이용 입주자등 과반수 동의"],
  ["입주자등이 열람할 수 있는 자료에는 어떤 것이 있나요?", 56, "운영경비·잡수입 사용내역·민원 처리 내역 등"],
];

async function ask(question, index) {
  return postSse(`${API}/assistant/ask`, { question }, {
    "content-type": "application/json",
    "X-Dev-Tenant-Id": TENANT,
    "X-Dev-User-Id": USERS[index % USERS.length],
  });
}

const results = [];
for (const [index, [question, expected, basis]] of CASES.entries()) {
  try {
    const { done, citations } = await ask(question, index);
    const clauses = citations.map((c) => c.clause ?? null).filter(Boolean);
    const want = String(expected).endsWith("조의2") ? `제${expected}` : `제${expected}조`;
    results.push({
      question,
      expected: want,
      basis,
      status: done?.status ?? null,
      clauses,
      hasAnyClause: clauses.length > 0,
      hit: clauses.some((c) => c.startsWith(want)),
    });
  } catch (error) {
    results.push({ question, expected: String(expected), basis, error: String(error) });
  }
  await new Promise((resolve) => setTimeout(resolve, 1500));  // 레이트 리밋 여유
}

const withClause = results.filter((r) => r.hasAnyClause).length;
const hit = results.filter((r) => r.hit).length;
const answered = results.filter((r) => r.status === "answered").length;
const errors = results.filter((r) => r.error).length;

console.log(`질의 ${results.length}건 | 답변 ${answered} | 폴백 ${results.length - answered - errors} | 오류 ${errors}`);
console.log(`조항 인용이 출력된 질의: ${withClause} | 기대 조항 적중: ${hit}\n`);
for (const r of results) {
  const mark = r.error ? "!" : r.hit ? "O" : r.hasAnyClause ? "~" : "X";
  console.log(`${mark} [기대 ${r.expected}] ${r.question}`);
  console.log(`    상태=${r.status ?? r.error} | 인용 조항=${(r.clauses ?? []).join(", ") || "(없음)"}`);
}
console.log(JSON.stringify({ total: results.length, answered, withClause, hit, errors }));
