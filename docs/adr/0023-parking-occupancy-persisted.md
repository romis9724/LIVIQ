# ADR-0023 — 주차 점유를 PG에 영속화 (프론트 시뮬레이션 폐기)

- 상태: Accepted (H15-4) → 개정 (H16)
- 관련: [0007](0007-readonly-tool-agent.md)(읽기 전용 도구 에이전트) · [03 §4.11](../03-database-design.md) · [11 §3.4.2](../11-data-architecture.md)
- 대체: [03 §4.11]·[11 §3.4.2]의 "면 점유 상태는 저장하지 않는다(프론트 시뮬레이션)" 서술을 폐기한다.

## Context

주차 "어느 면에 어느 차가 있는지"(점유)는 지금까지 DB에 없고 프론트 `apps/web-admin/src/features/parking/parking-sim.ts`
`simulateParking()`가 시드(20260725) 고정으로 매 렌더 합성했다(재실률 0.75·외부차 8대). 두 문제:

1. **데이터 원칙 위반** — 도메인 사실(점유)이 PostgreSQL/Neo4j 밖(브라우저)에만 존재. 감사도 RLS도 불가.
2. **입주민 최근접 빈자리 기능 불가** — "내 동에서 가장 가까운 빈 주차자리"(H15-4) 도구가 답하려면 점유가
   서버에서 확정·재현·감사 가능해야 한다(규칙1 출처, 규칙3 테넌트 격리). 클라 시뮬은 출처가 될 수 없다.
3. **진실 이원화 위험** — 점유를 서버로 옮기면서 관리자 3D뷰가 계속 시뮬하면 AI 도구 답과 화면이 갈린다.

## Decision

> **개정 노트 (H16)** — 저장 형태는 H16에서 `parking_vehicles.spot_no`·`entry_at` 컬럼으로
> 대체한다(별도 테이블 폐기 — 정리 마이그레이션 `73ca7f73a44d`). 아래 DDL·"전량 교체" 서술은
> 그 범위에서만 낡았다. 점유의 PG SoR 원칙·최근접 빈 자리 도구(`find_nearest_available_parking`)·
> 순수 기하 모듈(`ai_core/parking/geometry.py`)은 그대로 유지된다.

점유를 **PostgreSQL `parking_occupancy` 테이블에 영속화**하고 **단일 사실 원천(SoR)** 으로 삼는다.
프론트 시뮬은 SoR에서 은퇴한다(좌표·카메라 등 뷰 수학은 유지, 점유만 API로 읽음).

```sql
-- 면 점유 (면당 1행 · 전량 교체 · 표준 tenant RLS)
parking_occupancy(id, tenant_id,
                  spot_no text,                 -- parking_layouts.layout.spots[].no
                  is_external bool default false,
                  parking_vehicle_id uuid NULL, -- FK → parking_vehicles(tenant_id,id) composite, ON DELETE CASCADE (입주민 차)
                  external_plate_enc bytea NULL,-- 외부/방문차 번호판 암호문(봉투 암호화, 규칙2) — is_external=true일 때
                  parked_hours double precision,-- 입차 경과(뷰 표시용) — 절대시각 대신 상대값이라 시간 지나도 "3시간 전" 유지
                  created_at, updated_at)
  UNIQUE(tenant_id, spot_no)
  -- 무결성: is_external=false ⇒ parking_vehicle_id NOT NULL · external_plate_enc NULL
  --         is_external=true  ⇒ parking_vehicle_id NULL · external_plate_enc NOT NULL
```

- **RLS**: 표준 tenant 격리(ENABLE+FORCE·`tenant_isolation`). `liviq_app`(api 프로세스) SELECT grant — orchestrator 도구가 api에서 돎.
- **적재**: 시드 스크립트(`seed_parking.py`)가 배치도·차량 적재 뒤 **결정적 배정**을 계산해 전량 교체(멱등).
  배정 규칙(프론트 시뮬과 동종): 입주민 차는 자기 동 코어에서 가까운 빈 면 우선, **장애인 면 미배정·전기차 면은 EV만**,
  외부차 8대는 입구 근처. 정렬 기반 결정적(동·호·created 순, JS PRNG 바이트동일 재현은 불필요 — SoR가 PG로 바뀌므로).

## 최근접 빈자리 알고리즘 (도구 `find_nearest_available_parking`)

순수 기하 함수 `nearest_available_spots(layout, occupied, core, kind_pref)`를 ai-core에 두고
**도구(SQLAlchemy fetch)와 gen_labels(asyncpg fetch)가 공유**(드리프트 차단):

1. 빈 면 = `layout.spots` − `parking_occupancy.spot_no` − 장애인 면.
2. 앵커 = 내 동 코어(`Household.building_id`→`Building.name`="401"→코어명 "401동", `layout.cores[].name` 1:1).
3. 면 중심 ↔ 코어 중심 유클리드 거리 오름차순 top-K. EV 선호 시 전기차 면 우선(비-EV는 전기차 면 제외).
4. 반환: 면 no·kind·거리(m)·출처(=`parking_occupancy`). **LLM은 거리 계산 안 함 — 도구가 확정**(규칙8). 빈 면만 반환 → 타 입주민 PII 없음.

## 대안 (기각)

- **Neo4j 주차 노드로 통일**: 기각. 최근접은 **공간 거리**이지 관계 다단계 탐색(그래프 우위)이 아님. R26 실측상 검색 백엔드 중립.
- **시뮬 유지 + 도구용 Python 시뮬 복제**: 기각. 진실 이원화(도구 vs 화면). 단일 SoR 원칙 위반.
- **입출차 카메라(번호판 인식) API**: 미래 교체점으로 유지 — `parking_occupancy` 적재 경로를 시드에서 카메라 피드로 바꾸면 됨(스키마 불변).

## 결과

- 관리자 3D뷰(`ParkingView.tsx`)는 `simulateParking` 대신 `GET /admin/parking/occupancy`를 읽는다(단일진실).
- 입주민 최근접 빈자리 = RESIDENT 읽기 전용 도구. 데모 데이터임을 답변에 명시.
- 외부/방문차는 `is_external` 행으로 보존(방치 차량 시나리오 유지). 향후 방문차 관리 기능의 기반.
