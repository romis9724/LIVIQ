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

> 현재 상태: AI 계층(`apps/api`·`ai-core`) 미구현 → 어댑터가 `not-wired`를 반환하고
> 케이스는 **pending**으로 집계된다. api 도입 시 [adapter.mjs](adapter.mjs)만 연결하면
> 기존 케이스가 즉시 측정 대상이 된다. 케이스는 지금 미리 정의해 규칙을 고정한다.
