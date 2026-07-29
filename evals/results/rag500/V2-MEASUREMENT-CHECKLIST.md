# v2 330 개발서버 기준선 측정 체크리스트 (④)

> 옵션 1 확정: v2 먼저 측정, GraphRAG(G1~) 나중. 이 문서는 9시 이후 사용자 자리에서
> 개발서버 측정을 바로 시작하기 위한 절차. **측정은 개발서버에서만**(노트북 금지 — 계획 §2-2).

## 0. 현재까지 (main 반영 완료)

- ⓪ 도구 I/O(#112) · v2 케이스셋 330(#113) · 채점기 v2 확장(#114) 전부 머지.
- v2 케이스·라벨은 **로컬 DB**로 생성됨 — 개발서버는 시드 UUID·문서가 다를 수 있어 재생성 필요.

## 1. 선행 — 개발서버에서 라벨 재생성 (b)

로컬에서 만든 `quality-cases-v2.csv`의 라벨(문서 UUID·세대 바인딩·as_of)이 개발서버 DB와
정합하는지 확인하고, 어긋나면 개발서버에서 `gen_labels.py` 재실행.

```bash
# 개발서버 접속(메모리: 배포 호스트 SSH 16200)
# ssh -p 16200 <배포호스트>

# 개발서버 DB로 라벨 재생성 (DATABASE_URL은 개발서버 pg)
DATABASE_URL=postgresql://liviq_app:...@localhost:5432/liviq EVAL_AS_OF=2026-07-30 \
  uv run --no-sync python evals/fixtures/chetmaeul-v2/gen_labels.py selfcheck   # 먼저 11/11 확인
DATABASE_URL=... EVAL_AS_OF=2026-07-30 \
  uv run --no-sync python evals/fixtures/chetmaeul-v2/gen_labels.py gen evals/fixtures/chetmaeul-v2/cases-draft.csv
```

**확인 포인트**: selfcheck 통과(문서 제목·조항·세대·incident 다 존재) → 개발서버 코퍼스가
로컬과 동일 시드인지. 문서 34·설비 37·세대 322·incident 1이 개발서버에도 있어야.
스냅샷(`snapshot.json`) 카운트·해시가 로컬과 같으면 라벨 재생성 불필요(그대로 사용).

## 2. 측정 — Critical 132 × 3회 (단일 턴 3회·다중 턴 1회)

```bash
# 캐시 오프(H15-3 노브 answer_cache_ttl_s=0) — 측정 표준. api·러너 개발서버.
# vLLM 사내망 직결(192.168.10.171:8077) — 터널 아님(지연 오염 방지).
LIVIQ_EVAL_API_URL=http://localhost:8000 \
  node evals/rag500.mjs --caseset=v2 --set=critical --as-of=2026-07-30 \
  --auth=session --label=v2-vllm-llama31-r1
# r2·r3 반복 (라벨만 -r2/-r3). 3회 = 변동폭 판정(비겹침만 유의미).
# 다중 턴은 --set=full에서 1회(다중 턴 28건은 회귀 감지용).
```

- **`--auth=session` 필수**: v2는 역할×도구 정합·계정 격리 케이스가 있어 dev 헤더(역할 고정)로는
  역할 차단 검증 불가. 세션 로그인으로 실제 역할 태움. 시드 계정 UUID가 케이스 user_ref와
  일치해야(로컬=개발서버 시드 동일 가정, §1에서 확인).
- **안전 게이트 30**은 매 회 포함(Smoke에 들어감) — 전수 통과 조건.

## 3. 판정 지표 (채점기 v2 신설)

| 지표 | 의미 | 주의 |
|---|---|---|
| pass | 완주+behavior+citation | 도구 선택과 **합산 안 됨** |
| tool_accuracy | primary ∈ tool_path | 별도 — hit≠답변 성공 |
| citation_hit_rate | 실 UUID·tool·notice 인용 | v2 포맷 |
| fallback/behavior_ok | answered|fallback 일치 | 빈 결과 카드=answered |
| hard_fail | PII·인젝션·쓰기 | 안전 게이트 전수 |
| as_of_stale | 라벨 월≠측정 월 | 경고(2에서 as-of 맞추면 0) |

## 4. 측정 후

- 3회 결과 `evals/results/rag500/`에 JSON. MEASUREMENT-LOG.md에 R23으로 기록
  (pass·tool_accuracy·citation 범위, 카테고리별, v1 대비).
- **시설 그래프 케이스**(search_facility_graph 3+부정 7)는 현재 incident 1건 기준 — G1 시드 후
  재측정 대상으로 표시(옵션 1의 의도된 2단계).
- v1 500과 직접 비교 금지(다른 코퍼스·라벨 규약) — v2가 정본, v1은 회귀용.

## 5. 알려진 한계(측정 전 인지)

- FACILITY 역할 사용자 시드 없음 → 시설 케이스 MANAGER 바인딩(계획 §4 기록).
- PII 게이트는 정규식(전화·RRN·이메일)까지 — 타인 실명 노출은 시드 원문 대조 필요(A1 PR 미완,
  측정 시 시드 PII 로드해 응답 대조로 보강).
- 개발서버 실사용 백엔드가 env 폴백으로 qwen3:8b일 수 있음(R14 배포 확인 주의) — AI 설정 DB
  행으로 llama3.1 확정 상태인지 `/system/ai` 확인 후 측정.
