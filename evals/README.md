# evals — AI 하드 규칙 회귀 측정

LIVIQ의 **절대 규칙**([CLAUDE.md](../CLAUDE.md))을 AI 계층이 지키는지 자동 측정한다.
"개선했다"를 감이 아니라 **pass-rate 수치**로 말하기 위한 하네스.

## 무엇을 재나

각 케이스는 입력·기대 동작·판정 기준을 담는다. 측정 대상 규칙 영역(7):

1. **출처 인용** — 근거 없으면 담당자 연결 폴백, 지어내지 않음 (규칙 1)
2. **개인정보 마스킹** — 외부 LLM 호출 전 마스킹, 실패 시 차단 (규칙 2, fail-closed)
3. **단지(tenant) 격리** — 타 단지·타 세대 데이터 혼입 금지, 캐시 스코프 준수 (규칙 3)
4. **서버 인가 · 온보딩** — 미승인 사용자 질의 거부, 명부 PII 미노출 (규칙 4·2)
5. **관리비 계산 거부** — AI는 설명만, 계산·부과 안 함 (규칙 5)
6. **사람 검수** — 신뢰도 낮은 답변은 검수 큐, 공지는 초안까지만 (규칙 6)
7. **읽기 전용 도구** — 쓰기성 부수효과 차단, 스텝 상한 준수 (규칙 8)

## 구조

```text
cases/          케이스 정의 (JSON). id · rule · input · expect (snake_case)
run.mjs         러너 — 케이스 로드 → 어댑터 실행 → pass-rate 리포트
adapter.mjs     AI 계층 연결 지점 (미구현 — api 도입 시 wiring, 관측값 계약 명세)
results/        실행 결과 스냅샷 (pass-rate 추이)
```

## 실행

```bash
node evals/run.mjs                 # 전체 실행, pass-rate 출력 + 스냅샷 저장
node evals/run.mjs --rule=3        # 특정 규칙만 필터
node evals/run.mjs --trend         # 저장된 스냅샷의 날짜별 추이 표
```

## CI ([evals.yml](../.github/workflows/evals.yml))

`evals/**` push·PR + 매주 월요일(cron)에 러너를 실행한다. LLM 호출이 없어 안전하다.
잡 요약(step summary)에 pass/fail/pending 표를 남기고, `results/` 스냅샷을
아티팩트로 90일 보존해 pass-rate 추이를 축적한다.

## 어댑터 연결 (H1)

[adapter.mjs](adapter.mjs)는 **`LIVIQ_EVAL_API_URL` env 게이트**다:

- **미설정(CI 기본)**: `not-wired` 반환 → 전 케이스 pending. LLM 호출 0으로 CI 안전.
- **설정 시**: 실제 api `/assistant/ask`(SSE)에 질의해 측정. 로컬·스테이징 전용.

```bash
# 사전: infra 기동 + api 서버 실행 + 골든셋 문서 시드(단지 tenant)
LIVIQ_EVAL_API_URL=http://localhost:8000 node evals/run.mjs --rule=1
```

측정 범위(H1): **규칙 1(출처 인용·폴백)**만 SSE 결과에서 관측한다
(`must_cite`·`must_fallback`·`no_hallucination`·`no_answer_from_thin_air`·`tool_result_cited`).
그 외 규칙(마스킹·격리·검수·도구 등, H2+ 기능)은 관측 키를 넣지 않아 **pending**으로 남는다 —
판정 불가를 정직하게 표기하며, 해당 기능 구현 시 어댑터에 관측 키를 추가한다.

dev 컨텍스트는 `LIVIQ_EVAL_TENANT_ID`·`LIVIQ_EVAL_USER_ID`(기본값 = web dev 상수)로 시드와 맞춘다.
