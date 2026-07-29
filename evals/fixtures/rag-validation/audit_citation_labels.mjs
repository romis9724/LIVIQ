/**
 * 인용 실패 케이스의 라벨 결함 감사 (H15-2 #4).
 *
 * "기대 출처를 인용하지 않았다"는 판정에는 두 원인이 섞여 있다:
 *   (a) 모델이 못 찾았다        → 진짜 품질 실패
 *   (b) 기대 출처에 답이 없다   → 케이스셋 라벨 결함(인용 불가능한 것을 요구)
 *
 * (b)를 내용으로 가려낸다 — 질문의 핵심 토큰이 기대 문서 본문에 실제로 있는지,
 * 그리고 모델이 인용한 문서에는 있는지 비교한다. 본문은 DB에 색인된 청크를 쓴다
 * (검색기가 보는 것과 동일해야 판정이 유효하다).
 *
 * 라벨을 고쳐 통과율을 올리는 도구가 아니다. 근거는 문서 본문이고, 결과는
 * "사람이 확인할 후보 목록"이다.
 *
 * 준비: docs.csv = COPY (SELECT d.id, d.title, string_agg(c.content, ' ' ORDER BY c.chunk_index)
 *                        FROM documents d LEFT JOIN content_chunks c ON c.document_id = d.id
 *                        GROUP BY d.id, d.title) TO STDOUT WITH (FORMAT csv)
 * 실행: node evals/fixtures/rag-validation/audit_citation_labels.mjs <result.json> <docs.csv>
 */

import { readFileSync } from "node:fs";

import { loadCases, loadManifest, turnsOf } from "../../rag500-cases.mjs";

// 질문에서 빼는 지시어·기능어 — 문서 본문에 있을 리 없고 있어도 근거가 아니다.
const STOPWORDS = new Set([
  "알려줘", "정리해줘", "구분해줘", "설명해줘", "답해줘", "무엇", "어떻게", "어떤", "언제",
  "누가", "얼마", "인가요", "인가", "나요", "제가", "저는", "우리", "그리고", "또는", "관련",
  "대해", "따르면", "함께", "실제로", "따라야", "최신", "문서", "내용", "기준", "경우", "가능",
  "해줘", "주세요", "있나요", "되나요", "하나요", "라면", "라고", "이나", "에서", "으로",
]);

const MIN_TOKEN_LEN = 2;
// 기대 문서 커버리지가 이 값 미만이면 "본문에 답이 없다" 후보.
const COVERAGE_SUSPECT = 0.2;

/** 한글·영숫자 2자 이상 토큰. 형태소 분석 없이도 고유명사·항목명은 잡힌다. */
function tokenize(text) {
  const raw = text.match(/[가-힣a-zA-Z0-9]{2,}/g) ?? [];
  return raw.map((t) => t.toLowerCase()).filter((t) => t.length >= MIN_TOKEN_LEN);
}

/** 질문 토큰 중 문서 본문에 등장하는 비율. 부분일치 허용(한국어 조사 결합 때문). */
function coverage(questionTokens, docText) {
  if (questionTokens.length === 0) return null;
  const body = docText.toLowerCase();
  const hit = questionTokens.filter((t) => body.includes(t)).length;
  return hit / questionTokens.length;
}

function questionTokens(row) {
  const seen = new Set();
  for (const t of tokenize(turnsOf(row).join(" "))) {
    if (!STOPWORDS.has(t)) seen.add(t);
  }
  return [...seen];
}

/** docs.csv → uuid별 {title, body}. csv는 따옴표·개행 포함이라 직접 파싱한다. */
function loadDocBodies(path) {
  const text = readFileSync(path, "utf8");
  const rows = [];
  let field = "";
  let record = [];
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i += 1;
        } else quoted = false;
      } else field += ch;
      continue;
    }
    if (ch === '"') quoted = true;
    else if (ch === ",") {
      record.push(field);
      field = "";
    } else if (ch === "\n") {
      record.push(field);
      rows.push(record);
      record = [];
      field = "";
    } else if (ch !== "\r") field += ch;
  }
  if (field || record.length) {
    record.push(field);
    rows.push(record);
  }
  const byUuid = new Map();
  for (const [id, title, body] of rows) {
    if (id) byUuid.set(id, { title: title ?? "", body: body ?? "" });
  }
  return byUuid;
}

function main() {
  const [resultPath, docsPath] = process.argv.slice(2);
  if (!resultPath || !docsPath) {
    console.error("사용법: node audit_citation_labels.mjs <result.json> <docs.csv>");
    process.exit(2);
  }

  const result = JSON.parse(readFileSync(resultPath, "utf8"));
  const bodies = loadDocBodies(docsPath);
  const manifest = loadManifest();
  const uuidOf = new Map(Object.entries(manifest).map(([id, d]) => [id, d.uuid]));
  const rowById = new Map(loadCases({ set: "critical" }).map((r) => [r.case_id, r]));

  // 판정은 **모델 출력과 무관**해야 한다 — 모델이 인용한 문서를 조건에 넣으면 순환 논리가 된다.
  // 기준: 기대 출처 문서 본문이 질문의 주제 토큰을 담고 있는가. 전 케이스에 대해 계산한다
  // (실패 케이스만 보면 표본이 편향된다).
  const scored = [];
  for (const c of result.cases) {
    const row = rowById.get(c.case_id);
    if (!row) continue;
    const expectedIds = (c.expected.document_ids ?? []).filter((id) => uuidOf.has(id));
    if (expectedIds.length === 0) continue;
    const qTokens = questionTokens(row);
    const covs = expectedIds.map((id) => {
      const doc = bodies.get(uuidOf.get(id));
      return { id, title: doc?.title ?? "(본문 없음)", cov: doc ? coverage(qTokens, doc.body) : null };
    });
    scored.push({
      case_id: c.case_id,
      category: c.category,
      citation_hit: c.checks.citation_hit,
      covs,
      best: Math.max(...covs.map((m) => m.cov ?? 0)),
    });
  }

  const defects = scored.filter((e) => e.best < COVERAGE_SUSPECT);
  const sound = scored.filter((e) => e.best >= COVERAGE_SUSPECT);
  const pct = (v) => (v === null ? "  -  " : `${(v * 100).toFixed(0)}%`.padStart(5));

  console.log(`감사 대상: ${resultPath}`);
  console.log(`기대 출처가 있는 케이스: ${scored.length}건`);
  console.log(
    `\n## 라벨 결함 후보 — 기대 출처 어느 문서에도 질문 주제가 없음 (커버리지 <${COVERAGE_SUSPECT * 100}%): ${defects.length}건\n`,
  );
  for (const e of defects) {
    const hit = e.citation_hit === true ? "통과" : e.citation_hit === false ? "실패" : "미채점";
    console.log(`${e.case_id} [${e.category}] 판정=${hit}`);
    console.log(`  기대출처: ${e.covs.map((m) => `${m.id} "${m.title}"(${pct(m.cov)})`).join(" ")}`);
  }

  console.log("\n## 커버리지 분포 (기준선 선택 근거)\n");
  for (const [lo, hi] of [[0, 0.05], [0.05, 0.1], [0.1, 0.2], [0.2, 0.3], [0.3, 1.01]]) {
    const n = scored.filter((e) => e.best >= lo && e.best < hi).length;
    console.log(`  ${(lo * 100).toFixed(0).padStart(3)}~${(hi * 100).toFixed(0).padStart(3)}%  ${String(n).padStart(3)}건`);
  }

  const tally = (list) => {
    const t = {};
    for (const e of list) t[e.category] = (t[e.category] ?? 0) + 1;
    return t;
  };
  console.log("\n## 카테고리별 결함 후보 / 라벨 정상\n");
  const defectByCat = tally(defects);
  const soundByCat = tally(sound);
  for (const cat of new Set([...Object.keys(defectByCat), ...Object.keys(soundByCat)])) {
    console.log(
      `  ${cat.padEnd(28)} 결함 ${String(defectByCat[cat] ?? 0).padStart(3)}건 / 정상 ${String(soundByCat[cat] ?? 0).padStart(3)}건`,
    );
  }

  // 결함 후보 중 판정이 '실패'인 것 = 이 결함이 실제로 점수를 깎은 건수.
  const costing = defects.filter((e) => e.citation_hit === false);
  console.log(`\n## 결함이 실제로 인용 판정을 떨어뜨린 건수: ${costing.length}건`);
  console.log(costing.map((e) => e.case_id).join(" "));
}

main();
