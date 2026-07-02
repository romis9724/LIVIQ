# evals — AI 하드 규칙 회귀 측정

LIVIQ의 **절대 규칙**([CLAUDE.md](../CLAUDE.md))을 AI 계층이 지키는지 자동 측정한다.
"개선했다"를 감이 아니라 **pass-rate 수치**로 말하기 위한 하네스.

## 무엇을 재나

각 케이스는 입력·기대 동작·판정 기준을 담는다. 우선 대상(가장 위험 낮고 효과 큰 순):

1. **출처 인용** — 근거 없으면 담당자 연결 폴백, 지어내지 않음 (규칙 1)
2. **개인정보 마스킹** — 외부 LLM 호출 전 마스킹, 실패 시 차단 (규칙 2, fail-closed)
3. **관리비 계산 거부** — AI는 설명만, 계산·부과 안 함 (규칙 5)
4. **자동발송 거부** — 공지는 초안까지만 (규칙 6)

## 구조

```text
cases/          케이스 정의 (JSON). id · rule · input · expect
run.mjs         러너 — 케이스 로드 → 어댑터 실행 → pass-rate 리포트
adapter.mjs     AI 계층 연결 지점 (미구현 — api 도입 시 wiring)
results/        실행 결과 스냅샷 (pass-rate 추이)
```

## 실행

```bash
node evals/run.mjs                 # 전체 실행, pass-rate 출력
node evals/run.mjs --rule=2        # 특정 규칙만
```

> 현재 상태: AI 계층(`apps/api`·`ai-core`) 미구현 → 어댑터가 `not-wired`를 반환하고
> 케이스는 **pending**으로 집계된다. api 도입 시 [adapter.mjs](adapter.mjs)만 연결하면
> 기존 케이스가 즉시 측정 대상이 된다. 케이스는 지금 미리 정의해 규칙을 고정한다.
