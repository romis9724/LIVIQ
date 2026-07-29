# OpenAI 축 측정 계획 — 층화 표본 · 비용 추정 · 실행 절차 (H15-2)

> 로컬 축(llama3.1-8B) 결과는 [MEASUREMENT-LOG.md](MEASUREMENT-LOG.md) R1~R14, 보고서 초안은
> [REPORT-DRAFT.md](REPORT-DRAFT.md). 이 문서는 **외부 API(OpenAI) 축**의 표본 설계·예상 토큰량·
> 실행 절차를 담는다. **API 키·시크릿을 이 문서에 적지 않는다**(placeholder만).

측정 목적 3가지:

1. **품질 상한** — 같은 파이프라인·같은 케이스에서 상위 모델이 어디까지 올라가는가(로컬 8B의
   보수적 폴백·인용 누락이 모델 한계인지 파이프라인 한계인지 판별).
2. **안전** — 적대적 지시 복창(Hard Gate)이 외부 모델에서도 나오는가(로컬 실측 2~4건).
3. **질의당 원가** — top_k 8 vs 16의 **비용 차이**. 로컬에선 지연만 늘지만 외부 API에선 돈이다.

---

## 1. 표본 — Critical 180에서 층화 추출

선정 스크립트: [../../fixtures/rag-validation/pick_sample.py](../../fixtures/rag-validation/pick_sample.py)
산출물: `../../fixtures/rag-validation/sample-openai.csv`(원본과 같은 열 구조) +
`sample-openai.ids.txt`(러너 `--case=` 투입용 쉼표 목록).

```bash
uv run --no-sync python evals/fixtures/rag-validation/pick_sample.py --size 72   # 기본
uv run --no-sync python evals/fixtures/rag-validation/pick_sample.py --selfcheck # 배분·결정성 검증
```

### 1.1 선정 규칙

| 규칙 | 내용 | 근거 |
|---|---|---|
| 모집단 | `--set critical`(Critical 180) | 로컬 확정 기준선(R9·R12)이 같은 모집단 → **재측정 없이 짝지은 비교**(§1.4) |
| 층화 | 카테고리 × priority, 카테고리당 최소 8건 + 잔여 비례 배분 | 반복 변동폭 ±8%p(R9) — 층이 얇으면 노이즈가 결론을 삼킨다 |
| 판별 카테고리만 | 6종(계정·안전·민원·시설·규약·폴백) | 자동 채점이 유효한 카테고리(R6 원인 규명) |
| 제외 3종 | 관리비·다중문서KG·문서버전 | 측정 불가(§1.3). `--include-excluded`로만 포함 |
| 인젝션 6건 | Hard Gate 관측 **정액 쿼터**(품질 지표에 미사용) | §1.3 |
| 추출 방식 | 정렬(case_id) 후 **균등 간격** — 랜덤 아님 | 재현성. `--seed`는 간격 내 위상만 이동 |

### 1.2 분포 (size 72, seed 0)

| 카테고리 | 선정 | 모집단(Critical) | 비율 | 구분 |
|---|---:|---:|---:|---|
| 계정·온보딩·개인정보 | 16 | 35 | 46% | 판별 |
| 안전·법률 등 고위험 질문 | 13 | 25 | 52% | 판별 |
| 관리규약·공지·생활 안내 | 10 | 15 | 67% | 판별 |
| 시설·점검·유지보수 | 9 | 14 | 64% | 판별 |
| 민원·업무 절차 | 9 | 11 | 82% | 판별 |
| 답변 불가·모호한 질문·폴백 | 9 | 11 | 82% | 판별 |
| 프롬프트 인젝션·적대적 질문 | 6 | 30 | 20% | 게이트 관측 |
| **합계** | **72** | 180 | 40% | — |

priority: P0 35 · P1 9 · P2 28 (현 케이스셋은 priority가 카테고리로 결정된다 — 계정=P0, 규약=P2 등.
층화 코드는 유지하지만 실질 층은 카테고리 1개다).
**질의 수 108**(다중 턴 포함 — 케이스 72건의 turn 합계, 원가는 질의 단위로 발생).

### 1.3 판단 사항 — 인젝션은 포함, 나머지 3종은 제외

**인젝션 6건 포함**(정액 쿼터). 사실 채점은 불가하지만(기대사실이 행동 규정 → `needs_judge`),
Hard Gate 관측은 유효하고 보고서 안전성 장의 핵심 소재다. 카테고리 단위 집계라 품질 평균을
오염시키지 않는다(전체 평균은 애초에 쓰지 않는다 — R6 결론).

단, **균등 간격만으로 뽑으면 신호를 놓친다.** 첫 시행(균등 간격 6건)으로 기존 로컬 결과 6회분을
필터하니 Hard Gate가 **0건**이었다 — 실제 위반 케이스가 표본에 없었다. 그래서 로컬 10회 실행에서
반복 위반한 케이스를 **못 박았다**(`GATE_ONLY_PINNED`): QA-0460(7회) · QA-0474(5회) ·
QA-0464 · QA-0470 · QA-0473(각 3회). 못 박은 뒤 같은 필터에서 Hard Gate가 k=8 2~4건 · k=16 2건으로
전수(180건) 관측치와 일치한다 → **같은 프롬프트로 외부 모델을 직접 비교**할 수 있다.

**제외 3종**(기본):

| 카테고리 | 사유 |
|---|---|
| 다중 문서·Knowledge Graph | 합성 단지에 시설·그래프 데이터 없음 — 인용이 구조적으로 불가(R6) |
| 문서 버전·충돌·기준 시점 | citations에 revision 필드 없음 — 파이프라인 한계(보고서 §5.1) |
| 관리비 조회·설명 | 케이스셋 `fee_data` 과요구 결함 잔재 — 인용 적중 21%가 상한(R8) |

세 카테고리는 **모델을 바꿔도 수치가 오르지 않는다**(측정 대상이 모델이 아님). 외부 API 예산을
여기 쓰면 돈으로 아무 정보도 사지 않는 셈이다.

### 1.4 짝지은 로컬 기준선 — 추가 측정 0

표본 72건은 전부 기존 Critical 180 실행에 포함돼 있다. **케이스ID로 기존 결과 JSON을 필터하면
로컬 기준선이 그대로 나온다**(GPU 재측정 불필요):

```bash
uv run --no-sync python - <<'PY'
import csv, glob, json, collections, statistics as st
ids = {r["case_id"] for r in csv.DictReader(
    open("evals/fixtures/rag-validation/sample-openai.csv", encoding="utf-8-sig"))}
for suffix in ("topk16.json", "topk16-rep2.json", "topk16-rep3.json"):
    path = [p for p in glob.glob("evals/results/rag500/*.json") if p.endswith("awq-" + suffix)][0]
    cases = [c for c in json.load(open(path))["cases"] if c["case_id"] in ids]
    agg = collections.defaultdict(lambda: [0, 0])
    for c in cases:
        if c["checks"]["citation_hit"] is not None:
            a = agg[c["category"]]; a[0] += 1; a[1] += c["checks"]["citation_hit"]
    print(suffix, "pass", sum(c["verdict"] == "pass" for c in cases),
          "hardfail", sum(c["hard_fail"] for c in cases),
          {k: f"{h}/{n}" for k, (n, h) in sorted(agg.items())})
PY
```

표본 72건 기준 로컬(vLLM llama3.1-8B-AWQ, 캐시 오프) 3회 인용 적중 **중위값**:

| 카테고리 | k=8 | k=16 |
|---|---:|---:|
| 계정·온보딩·개인정보 | 88% | 88% |
| 안전·법률 등 고위험 | 85% | 85% |
| 시설·점검·유지보수 | 89% | 89% |
| 민원·업무 절차 | 67% | 67% |
| 관리규약·공지·생활 안내 | 60% | **90%** |
| 폴백 정확도(폴백 카테고리) | 100% | 89% |
| pass(72건 중, 3회 범위) | 42 (41~44) | 45 (44~47) |
| Hard Gate | 2~4 | 2 |

전수(180건) 수치와 카테고리별로 ±3%p 안에서 일치한다 → **표본이 대표성을 유지**한다.

### 1.5 표본 크기의 한계 (해석 규칙)

- 표본 72건에서 **top_k 8 vs 16의 pass 범위가 겹친다**(41~44 vs 44~47). 전수 180건에서는 겹치지
  않았다(91~96 vs 97~107). → **표본으로는 미세한 설정 차이를 판정할 수 없다.** 표본의 용도는
  "외부 모델이 로컬 기준선을 넘는가"이고, 넘는 폭이 카테고리당 **20%p 이상**일 때만 유의로 본다
  (층 n=9~16 → 1건이 6~11%p).
- 규약·공지처럼 **범위가 비겹침으로 남는 신호**(60% vs 80~100%)는 표본에서도 살아남는다.
- 카테고리 n이 9~16이라 소수점 비교는 무의미하다. 표는 정수 건수(x/n)로 적는다.

---

## 2. 토큰 추정

### 2.1 실측 상수 (추정의 근거)

결과 JSON에는 프로바이더 `usage`가 없다(로컬 vLLM 측정 시점 러너가 토큰을 기록하지 않았고,
서버 `done.usage`는 추정치다 — §2.5). 따라서 **프롬프트 구조 + 실측 상수**로 산식을 세운다.

| 상수 | 값 | 측정 방법 |
|---|---:|---|
| 시스템 프롬프트(도구 결정 turn) | 105 tok | `AGENT_SYSTEM_PROMPT` → `estimate_tokens` |
| 시스템 프롬프트(최종 답변 turn) | 149 tok | `ANSWER_SYSTEM_PROMPT` → 동일 |
| 도구 스펙(JSON) | 414(입주민 4종) ~ 592(관리자+그래프 6종) tok | `default_registry().specs_for()` 직렬화 후 측정 → 산식은 450 사용 |
| 질문 1건 | 평균 30 tok(최대 46) | 표본 CSV의 turn 101~108건 실측 |
| 청크 1개 | **합성 코퍼스 69 tok** / **첫마을 PDF 303 tok**(중위 370, 상한 400) | `chunk_text` + `estimate_tokens`를 fixture 코퍼스·데모 PDF 33건에 직접 실행 |
| 청크 머리글(`[n] (제목 조항 p.N)`) | 12 tok | `build_context_block` 형식 |
| 케이스당 도구 호출 | 1.74건(k=16) · 2.01건(k=8) | 기존 결과 JSON `tool_path` 길이 평균(Critical 180) |
| 케이스당 턴 | 1.32턴 → 턴당 도구 호출 1.32건 | 같은 JSON `latency.turns` |
| 케이스당 출력 | 답변 350 tok(본문 288 + tool_call JSON 약 60) | `answer_chars` 평균(k=16, 한국어는 1자≈1토큰) |
| 최종 turn 컨텍스트 상한 | 2,400 tok | `orchestrator.CONTEXT_BUDGET_TOKENS`(`_fit`이 절단) |

**주의: `retrieval_top_k`는 도구 결정 turn에 그대로 실린다.** `search_documents`는 top_k 청크를
잘라내지 않고 tool 메시지에 넣고, 그 대화가 다음 결정 turn에 다시 전송된다. 최종 답변 turn만
2,400 토큰으로 절단된다 → **top_k를 올린 비용은 주로 결정 루프에서 발생**한다.

### 2.2 질의당 입력 토큰 산식

```
입력(질의 1건)
  = Σ(결정 turn i) [ 105 + 450 + 질문30 + 누적(assistant tool_calls 40 + 도구결과) ]
  + [ 149 + min(2400, 근거블록) + 질문30 ]                 ← 최종 답변 turn
도구결과(search_documents) = top_k × (청크토큰 + 12)
```

| 코퍼스 | top_k | 결정 turn 합 | 최종 turn | **질의당 입력** |
|---|---:|---:|---:|---:|
| 측정용 합성 코퍼스(청크 69 tok) | 8 | 1,858 | 827 | **2,685 tok** |
| 측정용 합성 코퍼스 | **16** | 2,506 | 1,475 | **3,981 tok** |
| 운영 코퍼스(첫마을 PDF, 청크 303 tok) | 8 | 3,730 | 2,579 | **6,309 tok** |
| 운영 코퍼스 | **16** | 6,250 | 2,579 | **8,829 tok** |

측정 표본은 합성 3단지 문서로 도니 **운영 원가보다 2배 이상 싸다**. 보고서에 "질의당 원가"를 쓸
때는 **운영 코퍼스 기준(6.3k / 8.8k tok)**을 병기해야 오해가 없다.

### 2.3 조합별 총 토큰량 (표본 × 반복 × 모델 1종)

출력은 반복·top_k와 무관하게 케이스당 350 tok으로 본다.

| 표본 | 질의/회 | 반복 | k=8 입력 | k=16 입력 | 출력 |
|---:|---:|---:|---:|---:|---:|
| 72건 | 108 | 1 | 290k | 430k | 25k |
| 72건 | 108 | 2 | 580k | 860k | 50k |
| 72건 | 108 | **3** | 870k | 1,290k | 76k |
| 96건 | 135 | 2 | 725k | 1,075k | 67k |
| 117건(판별 전수) | 164 | **2** | 881k | 1,306k | 82k |
| 117건 | 164 | 3 | 1,321k | 1,959k | 123k |

`--size 120` 이상은 117건에서 포화한다(판별 6종 Critical 111건 + 인젝션 6건 = 상한).

### 2.4 비용 표 — 단가는 측정 시점에 채운다

**단가를 코드·문서에 박지 않는다**(낡는다). 실행 당일 OpenAI 공식 가격표에서 확인해 아래 빈 칸에
적고, 러너에는 env로 주입한다(`LIVIQ_EVAL_PRICE_IN`·`LIVIQ_EVAL_PRICE_OUT`, 1M 토큰당 USD).

```
비용(USD) = 입력토큰/1_000_000 × 단가_in + 출력토큰/1_000_000 × 단가_out
```

| 모델 | top_k | 반복 | 입력 토큰 | 출력 토큰 | 단가_in($/1M) | 단가_out($/1M) | 비용($) |
|---|---:|---:|---:|---:|---:|---:|---:|
| mini급 | 8 | 3 | 870k | 76k | | | |
| mini급 | 16 | 3 | 1,290k | 76k | | | |
| 상위 1종 | 8 | 3 | 870k | 76k | | | |
| 상위 1종 | 16 | 3 | 1,290k | 76k | | | |
| **소계(권고안, §3)** | | | **3,493k** | **246k** | | | |

참고 — 운영 환산(첫마을 코퍼스, 질의 1건):

| top_k | 입력 tok | 출력 tok | 질의당 비용($) |
|---:|---:|---:|---:|
| 8 | 6,309 | 350 | |
| 16 | 8,829 | 350 | |

### 2.5 러너 원가는 **전 turn 합산 근사값**이다 (정정 반영됨)

이 문서 초안 시점에는 러너 원가가 최종 답변 turn만 담아 **입력의 63~71%가 누락**됐다. 그 결함을
오케스트레이터에서 정정했다(`_sum_usage` — 도구 결정 turn + 최종 답변 turn 합산, 폴백 경로도 이미
쓴 결정 turn 토큰을 싣는다).

정정 전/후 실측(같은 케이스·vLLM llama3.1-8B-AWQ):

| 케이스 | 정정 전 | 정정 후 | 누락분 |
|---|---|---|---|
| QA-0002 (answered) | 1,228 in / 30 out | **4,618 in / 114 out** | 입력 73% · 원가 3.8배 |
| QA-0001 (fallback, 3턴) | 4,366 in / 112 out | **17,693 in / 1,165 out** | 입력 75% |

남은 오차는 **최종 답변 turn 하나**뿐이다 — 스트리밍이라 프로바이더 usage가 오지 않아
`estimate_tokens` 추정치를 쓴다. 결정 turn은 비스트리밍이라 실측값이다. 그래서:

- 결과 JSON·콘솔의 `token_estimated`/`⚠` 경고는 "최종 turn 추정 혼입" 표시다(전량 추정이 아니다).
- 러너 원가는 **근사값이며 카테고리 간 상대 비교에 충분**하다. 절대 청구액은 OpenAI 사용량
  대시보드와 한 번 대조해 오차율을 기록하면 보고서 신뢰도가 올라간다(필수는 아님).
- 완전 실측을 원하면 `chat_stream`에 `stream_options: {include_usage: true}` + usage 반환 채널이
  필요하다 — 시그니처 변경이라 별도 작업 단위.
- **부수 영향**: DB `messages.token_input/output`도 전 turn 합계로 기록된다(대시보드 `_budget_stats`가
  참조). 값이 3~4배로 커지므로 `LLM_DAILY_TOKEN_BUDGET`을 쓰는 환경은 재산정이 필요하다
  (개발서버는 미설정=무제한이라 영향 없음). 과거 기록과 섞이면 평균에 단절이 보이는 것은 정상이다.

---

## 3. 반복 횟수 권고

로컬 동일 설정 3회에서 카테고리별 ±8%p가 흔들린다(R9). 표본은 층이 얇아 변동이 더 크다
(층 n=9~16 → 1건이 6~11%p). 반복 없이 1회만 재면 **노이즈를 성능 차이로 오독**한다.

토큰 총량이 같은 두 안을 비교하면:

| 안 | 구성 | 입력 | 출력 | 얻는 것 | 잃는 것 |
|---|---|---:|---:|---|---|
| **A** | 표본 72건 × 3회 (mini k8·k16, 상위 k16) | 3.45M | 227k | 반복 3회 = 로컬과 같은 프로토콜, 변동폭 직접 관측 | 카테고리 n=9~16 유지(해상도 낮음) |
| **B(권고)** | 표본 117건 × 2회 (mini k8·k16, 상위 k16) | 3.49M | 246k | 판별 카테고리 **전수** — 카테고리 해상도 최대, 전수 결과와 직접 비교 | 반복 2회(변동폭을 로컬 ±8%p 사전값으로 대체) |
| C(최소) | 표본 72건 × 2회 (mini·상위 k16만) | 1.72M | 101k | 절반 비용 | top_k 비용 비교 불가, 반복 2회 |

**권고: B.** 변동폭은 로컬 3회(R9·R12)에서 이미 정량화돼 있어 사전값으로 쓸 수 있고, 외부 모델
측정의 병목은 노이즈보다 **층 두께**다(카테고리 n이 9면 1건이 11%p). 다만 B에서도 **최소 2회**는
반드시 돌린다 — 1회 결과로 카테고리 순위를 매기지 않는다.

단가 확인 후 상위 모델 비용이 예산을 넘으면 **상위 모델만 A(72건 × 2~3회)로 축소**한다. mini급은
싸므로 117건 × 2회를 유지한다(top_k 비용 비교는 mini급에서 얻는다).

---

## 4. 실행 절차 (측정 당일)

전제: 로컬 스택(api·pg·redis·minio) 기동, 합성 3단지 시드·색인 완료, `LIVIQ_EVAL_API_URL` 설정.
**임베딩은 bge-m3 로컬 고정**(변인 통제 — §4.2).

### 4.0 표본 확정

```bash
uv run --no-sync python evals/fixtures/rag-validation/pick_sample.py --selfcheck
uv run --no-sync python evals/fixtures/rag-validation/pick_sample.py --size 120   # 권고안 B = 117건
```

확인: 콘솔 분포표의 카테고리 7종 · 선정 합계 · `sample-openai.ids.txt` 생성.
저장돼 있는 CSV는 **기본 72건**(§1.2 분포·§1.4 기준선이 이 표본 기준). 권고안 B로 117건을
다시 뽑으면 §1.4 명령을 그 CSV로 한 번 더 돌려 **짝지은 기준선을 새로 계산**한다.

### 4.1 AI 설정에 OpenAI 백엔드 등록

관리자 웹 **시스템 → AI 설정**(`/system/ai`, SYS_ADMIN 전용) 또는 API `PUT /system/ai-config`.

| 필드 | 값 |
|---|---|
| base URL | `https://api.openai.com/v1` |
| 모델 | 측정 대상 모델 ID(mini급 / 상위 1종) |
| API 키 | **여기 적지 않음** — 당일 전달받아 UI에 입력(응답은 끝 4자만 마스킹 표시) |
| reasoning effort | 비움 또는 `none` — **추론 모델은 content가 비어 잘린다**(#106, ADR 없음: 실측 교훈) |
| 임베딩 섹션 | **건드리지 않는다**(로컬 bge-m3 유지 — 바꾸면 차원 검증 422 또는 전량 재색인) |

API로 할 경우(키는 셸 히스토리에 남지 않게 env로):

```bash
curl -sS -X PUT "$API/system/ai-config" -H 'Content-Type: application/json' \
  -b "liviq_session=$SESSION" \
  -d "{\"base_url\":\"https://api.openai.com/v1\",\"model\":\"$MODEL\",\"api_key\":\"$OPENAI_API_KEY\",
       \"retrieval_top_k\":16,\"answer_cache_ttl_s\":0}"
```

확인:
1. UI **연결 테스트**(`POST /system/ai-config/test`) → ok=true·지연 표시. 실패하면 여기서 멈춘다.
2. `GET /system/ai-config` 응답의 `source`가 `db`, `model`이 대상 모델, `api_key_masked`가 `****`+4자.
3. 임베딩 `embedding_source`가 여전히 `env`(로컬 bge-m3) — **여기가 db로 바뀌면 잘못 만졌다.**

### 4.2 측정 프로토콜 노브

| 노브(UI 라벨) | 값 | 이유 |
|---|---|---|
| 답변 캐시 TTL(초) | **0** | 캐시 히트는 품질·지연·토큰을 모두 왜곡(R1 교훈) |
| 검색 top_k | 8 / 16 (조합별로 전환) | 비용·품질 비교 대상. 재색인 불필요 |
| 청크 토큰 상한 | 400(기본) 고정 | 바꾸면 **전량 재색인** — 변인에서 제외 |
| LLM 출력 상한 | 1024(기본) 고정 | 출력 토큰 원가 상한 고정 |
| LLM timeout(초) | 60(기본) | 외부 API 지연 여유 |

확인: `GET /system/ai-config`의 `answer_cache_ttl_s=0`·`retrieval_top_k`가 의도한 값.
1건 스모크 후 결과 JSON의 `latency.ttft_ms`가 수백 ms 이상(수십 ms면 캐시 히트 = 캐시가 안 꺼졌다).

### 4.3 하드 룰 게이트 먼저

```bash
LIVIQ_EVAL_API_URL=http://localhost:8000 node evals/run.mjs
```

확인: **fail 0**. 인용 규율·tool calling·읽기 전용을 못 지키는 모델은 품질 표본을 돌릴 자격이
없다(R10·R13에서 두 모델이 여기서 탈락). fail이 있으면 케이스 발췌를 보고 모델 문제인지
설정 문제인지 가른 뒤 진행 여부를 결정한다.

### 4.4 표본 측정

러너에 **CSV 파일 경로 옵션은 없다**(`loadCases`가 `quality-cases-500.csv`를 고정 경로로 읽고
`--set`/`--case`로만 필터). 표본은 `--case=`로 투입한다:

```bash
IDS=$(cat evals/fixtures/rag-validation/sample-openai.ids.txt)
LIVIQ_EVAL_API_URL=http://localhost:8000 \
LIVIQ_EVAL_PRICE_IN=<단가_in> LIVIQ_EVAL_PRICE_OUT=<단가_out> \
  node evals/rag500.mjs --set=all --case="$IDS" --auth=session --label=openai-<모델>-k16-rep1
```

- `--set=all`을 함께 준다 — `--case`가 필터를 지배하지만 결과 JSON `set` 필드가 정확해진다.
- `--auth=session`: 케이스의 실제 역할·테넌트로 호출(역할 민감 케이스 재현).
- 라벨에 **모델·top_k·회차**를 넣는다(파일명이 곧 실험 조건 — 로컬 실행 관례와 동일).
- 반복은 라벨만 바꿔 다시 실행(`-rep2`, `-rep3`).
- 러너는 429(분당 상한)에 61초 냉각 후 1회 재시도한다. 외부 API의 rate limit에 걸리면
  콘솔에 429가 반복되므로, 그 경우 조합을 나눠 순차 실행한다.

확인:
1. 콘솔 카테고리 표의 `n` 합계 = 표본 건수, `측정 실패 0건`.
2. `토큰in/토큰out` 열과 원가 열이 채워짐(단가 주입 시). **`⚠ 추정 토큰` 경고는 정상** —
   최종 답변 turn만 추정 혼입이라는 뜻이다(§2.5).
3. 결과 파일 `evals/results/rag500/rag500-<timestamp>-<label>.json` 생성.
4. OpenAI 사용량 대시보드에서 해당 시간대 실제 토큰·청구액 확인 → §2.4 표에 기록.

### 4.5 기록

[MEASUREMENT-LOG.md](MEASUREMENT-LOG.md)에 R15 이후로 시간순 추가: 라벨·모델·top_k·반복·캐시
상태·카테고리별 수치·Hard Gate·대시보드 실측 토큰/비용. 표본 기준 로컬 기준선(§1.4)과
**같은 표에 나란히** 적는다(전수 수치와 섞지 않는다 — n이 다르다).

---

## 5. 원복 절차 (측정 종료 후 필수)

1. 관리자 웹 AI 설정에서 **base URL·모델을 로컬 백엔드로 되돌린다**(vLLM 터널 또는 ollama).
2. **API 키를 빈 문자열로 저장**한다 — 빈 값 = 삭제(env 폴백 복귀). 키를 DB에 남기지 않는다.
3. 노브 원복: `answer_cache_ttl_s` 비움(기본 3600 복귀), `retrieval_top_k` 비움(기본 16 복귀).
4. 확인: `GET /system/ai-config` → `base_url`이 로컬, `api_key_masked`가 null 또는 env 키,
   `answer_cache_ttl_s=3600`. 질의 1건이 정상 응답.
5. 확인: `node evals/run.mjs` fail 0(로컬 백엔드로 게이트 회복).
6. 키 문자열은 셸 히스토리·문서·커밋에 남기지 않는다(env·UI 입력만 사용).

---

## 6. 산출물 체크리스트

- [ ] `sample-openai.csv` · `sample-openai.ids.txt`(원본과 동일 열 구조 — `--selfcheck`로 검증)
- [ ] 조합별 결과 JSON(모델 2종 × top_k × 반복) — 라벨에 조건 표기
- [ ] §2.4 비용 표(당일 단가·대시보드 실측 청구액)
- [ ] MEASUREMENT-LOG R15+ 기록(표본 기준 로컬 기준선 병기)
- [ ] REPORT-DRAFT §6 "외부 API 품질 상한·질의당 비용" 갱신 — 카테고리별 정수 건수(x/n)로
- [ ] AI 설정 원복 확인(§5)
