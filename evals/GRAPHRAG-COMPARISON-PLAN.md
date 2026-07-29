# GraphRAG 비교 분석 설계 — pgvector vs Neo4j (H15-2 확장)

> 상태: **설계안(검토 대기)** · 작성 2026-07-30 · 인터뷰 확정
> 근거: [CASESET-V2-PLAN.md](CASESET-V2-PLAN.md) · 실측(로컬 첫마을 4단지)

## 0. 목적 (사용자 확정)

Neo4j의 RAG 처리가 어떻게 최적으로 동작하는지 확인하고, **pgvector와 Neo4j를 비교
분석**한다. 두 백엔드는 원래 다른 일을 하므로(pgvector=문서 의미검색, Neo4j=관계 그래프
탐색), 비교는 **두 축을 함께** 쓴다:

1. **병렬 표현 축** — 같은 지식(설비 장애·정비 이력)을 문서 청크(pgvector)와 그래프
   노드(Neo4j) 양쪽에 이중 적재하고, 겹치는 질의를 양쪽으로 답해 **검색 품질·지연을
   head-to-head** 비교.
2. **클래스 분담 축** — 문서=사실 조회, 그래프=다단계 원인 추적으로 나눠 **무엇에 어느
   백엔드가 맞는가**를 측정.

부수 목표: 입주민이 자기 집 시설 민원을 냈을 때 Neo4j로 원인·이력을 추적하는 경험을
신규 도구로 제공(RESIDENT 전용·본인 세대 스코프).

## 1. 인터뷰 확정 사항

| 결정 | 값 |
|---|---|
| 비교 축 | 병렬 표현 + 클래스 분담 **둘 다** |
| 신규 도구 역할 | **RESIDENT 전용·본인 세대 스코프** — 세대 기기→설비→그래프, 서버에서 스코프 강제 |
| 시드 비율 | **겹침 구간만큼** — incident 12~15·maintenance 20~25·연결 2~3단, 겹침 장애 8~10건은 문서로도 이중 적재 |
| 시드 위치 | **첫마을 직접**(제안·판단) — 과거 이력 추가는 데모 오염 아님, `facilities.status`는 불변 유지 |

## 2. 실측 — 현재 배선 (로컬 첫마을 2026-07-30)

| 항목 | 상태 | 조치 |
|---|---|---|
| `inquiries.facility_id` | 존재 | 민원→설비 연결 있음 — 재사용 |
| `plan_devices.facility_id` | **0/108 NULL** | 세대 기기→설비 배선 결손 — §4 계통 매핑으로 해결 |
| `incidents` | `symptom·resolution·root_cause·occurred_at·facility_id` | 그래프 답변에 해결책 근거 가능 |
| `maintenance_logs` | `work·parts·performer·performed_at·facility_id` | 정비 이력 근거 |
| 첫마을 그래프 | incident 1·maintenance 1 | 시드 보강(§3) |
| Neo4j 노드 | Facility 45·PlanDevice 80·Incident 1(첫마을)·MaintenanceLog 1 | PlanDevice→Facility 엣지 없음 |
| 재색인 경로 | PG(정본) → arq worker → Neo4j | 시드는 PG에, 재색인으로 그래프 반영 |

**정합 확인**: Neo4j Incident 9건 중 8건은 E2E 테넌트(`ee2e…`) — 첫마을은 PG·Neo4j 모두
1건으로 일치(불일치 아님).

## 3. 시드 보강 (첫마을·eval 목적)

`facilities.status`는 건드리지 않는다(현재 전부 normal 유지 — 계획 §7-2 오염 방지).
**과거 이력만** 추가:

- **incidents 12~15건** — 설비 계통별 분포(승강기 3·급수 3·소방 2·전기 2·난방 2·환기 1).
  각 `symptom`(증상)·`root_cause`(원인)·`resolution`(조치)·`occurred_at`(과거 시각) 채움.
  회의록에 실재하는 장애(승강기 주로프 마모·부스터펌프 진동·화재수신기 오작동 등)와
  정합시켜 문서-그래프 교차 검증 가능하게.
- **maintenance_logs 20~25건** — incident 대응 정비 + 정기 정비. `work·parts·performer`.
- **연결 깊이 2~3단** — Facility→HAS_INCIDENT→Incident, Facility→HAS_MAINTENANCE→
  MaintenanceLog, 동일 계통 설비 간 연쇄(예: 부스터펌프 1호기 장애 → 2호기 부하 → 정비).
- **겹침 장애 8~10건**은 문서로도 이중 적재: `graphrag-overlap` 문서 1건에 "설비별 과거
  장애·조치 이력"을 서술형으로 넣어 pgvector 청크로도 검색되게 → 병렬 표현 축의 근거.

시드 스크립트: `evals/fixtures/chetmaeul-v2/seed_graph.py`(PG insert → 재색인 enqueue).
`as_of` 고정과 동일 원칙 — `occurred_at`은 절대 시각(2024~2026 분산).

## 4. 신규 도구 — `trace_home_device_issue` (RESIDENT 전용)

입주민 질의 "우리 집 XX가 고장났어요/이상해요" → 세대 평면도 기기를 공용 설비 계통에
매핑하고, 그 계통의 과거 장애·조치 이력을 그래프에서 찾아 반환.

### 경로

```
질의("화장실 온수가 안 나와요")
 → 세대 확인(user→household, find_in_floor_plan과 동일 스코프)
 → device_type/증상 → 설비 계통 매핑(§4.1)
 → Neo4j: 해당 계통 Facility의 HAS_INCIDENT·HAS_MAINTENANCE 탐색
 → 카드: 유사 증상·원인·조치 이력(resolution 포함)
```

### 4.1 계통 매핑 (세대 기기·증상 → 공용 설비 code 접두)

세대 내부 기기는 공용 설비에 물리 직결이 아니므로 **증상 키워드 → 설비 계통** 매핑을 둔다
(코드 상수, 도메인 규칙):

| 세대 증상·기기 | 설비 계통(code 접두) | 근거 문서 |
|---|---|---|
| 온수·난방 안 됨 | WT(급수)·열교환기 | 부스터펌프·열교환기 매뉴얼 |
| 정전·콘센트·분전함 | EP(전기)·수변전 | 수변전 지침 |
| 화재감지기·경보 | FR(소방) | 화재수신기 매뉴얼 |
| 승강기 | EL | 승강기 지침 |
| 환기·주차장 | 환기설비 | 환기 매뉴얼 |

매핑은 `plan_devices.facility_id`를 채우는 대신 **런타임 규칙**으로 둔다(세대 기기와 공용
설비는 M:1도 N:M도 아닌 계통 관계라 FK가 부적절 — 온수 문제는 급수+난방 둘 다일 수 있음).

### 4.2 계약 (절대 규칙 준수)

- **RESIDENT 전용**, 본인 세대 스코프 서버 강제(다른 세대·전체 설비 조회 불가 — 규칙 4).
- 읽기 전용(규칙 8). 그래프 탐색 결과는 카드로, 인용은 `tool:trace_home_device_issue`.
- 빈 결과(이력 없음)도 카드 승격(⓪ 계약) — "해당 계통 과거 장애 없음"이 확정 근거.
- 개인정보 없음(설비·장애 이력은 PII 아님) — 마스킹 대상 아니나 세대 스코프는 엄수.

### 4.3 기존 도구와의 경계

- `search_facility_graph`(FACILITY·MANAGER) — 관리자용, 전체 설비 원인 추적. 유지.
- `trace_home_device_issue`(RESIDENT) — 입주민용, 본인 세대 계통 한정. 신규.
- `find_in_floor_plan`(RESIDENT) — 위치만. 신규 도구가 이 세대 해석 로직 재사용.

## 5. 케이스셋 확장 (v2에 GraphRAG 비교 카테고리 추가)

기존 330 + **GraphRAG 비교 40건**:

| 하위 | 건수 | 축 | label_source |
|---|---:|---|---|
| 병렬-문서 | 10 | 병렬 표현 | 겹침 장애를 `doc`로 질의(pgvector 경로) |
| 병렬-그래프 | 10 | 병렬 표현 | 같은 장애를 `graph:incident`로 질의(Neo4j 경로) |
| 세대 민원 추적 | 12 | 클래스(그래프 강점) | `home-device:<증상>` 신규 리졸버 |
| 다단계 원인 | 8 | 클래스(그래프 강점) | 연쇄 장애 추적(`graph:chain`) |

병렬 10+10은 **동일 장애의 두 표현** — 같은 정답을 문서/그래프로 각각 물어 검색 적중·
지연을 짝지어 비교(측정 시 `pair_id`로 묶음).

## 6. 채점 확장 (rag500-score.mjs)

- **백엔드별 집계**: 병렬 쌍(`pair_id`)의 문서 경로 vs 그래프 경로 — 인용 적중·지연·폴백률
  나란히. 이게 head-to-head 표의 원자료.
- 클래스 분담: 세대 민원·다단계 케이스는 그래프 도구 선택 정확도 + 답변 품질.
- 기존 v2 채점(도구 선택·PII·부정 정답 계약)과 공존.

## 7. 이행 순서

1. **시드 보강** `seed_graph.py` — incident·maintenance PG insert + 겹침 문서 1건, 재색인.
2. **신규 도구** `trace_home_device_issue` — 계통 매핑·세대 스코프·그래프 탐색, TDD.
3. **겹침 문서 이중 적재** 확인(pgvector 청크 검색됨).
4. **케이스 40건** draft + 라벨 생성기 리졸버 2종(`home-device`·`graph:chain`) 추가.
5. **채점 확장** 병렬 쌍 백엔드별 집계.
6. **개발서버 기준선**(④와 합류) — pgvector vs Neo4j 비교표 산출.

## 8. 열린 질문 (검토 요청)

1. 계통 매핑(§4.1)을 코드 상수로 두는 게 맞나, 아니면 `plan_devices.facility_id`를 실제로
   채워 그래프 엣지(PlanDevice→SERVED_BY→Facility)로 만드는 게 GraphRAG 취지에 더 맞나?
   (후자가 "그래프다운" 표현이나 세대 기기-설비가 N:M이라 배선 비용 큼)
2. 병렬 표현의 공정성 — 같은 장애를 문서는 서술형, 그래프는 구조화로 넣으면 표현 차이가
   곧 백엔드 차이와 섞인다. 서술 밀도를 어떻게 통제할지.
3. GraphRAG 비교 40건을 v2 정본에 합칠지, 별도 실험 세트로 둘지(정본 오염 vs 편의).
4. 다단계 원인 추적(§5 `graph:chain`)의 정답을 어떻게 결정론 생성하나 — 연쇄는 그래프
   경로라 라벨 생성기가 Cypher로 경로를 뽑아 고정해야 함.
