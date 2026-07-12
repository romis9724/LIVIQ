# LIVIQ 문서·설계 심층 리뷰

> 리뷰 일자: 2026-07-13  
> 리뷰 범위: 루트 문서, `docs/`, ADR, 평가 문서 및 현재 저장소 구조  
> 판정: **조건부 승인 — P0 보안·격리 항목 해결 후 실제 tenant 데이터 파일럿 가능**

> **처리 현황 (2026-07-13)**: 아래 취소선(~~) 항목은 설계 문서에 반영 완료 — 다음 리뷰 시 참고 불필요.
> 보류 항목은 ⏸ 표기. 구현·실측 검증 항목(체크박스)은 구현 단계 게이트로 유지.

## 1. 총평

LIVIQ의 핵심 방향은 타당하다. PostgreSQL을 SoR(Source of Record)로 두고 Neo4j를 재생성 가능한 파생 projection으로 분리한 점, LLM 쓰기 도구를 금지하고 코드가 부수효과를 실행하도록 한 점, 관리비 계산 금지·공지 자동발송 금지·근거 없는 답변 폴백을 불변 규칙으로 둔 점은 적절하다.

다만 현재 문서만으로 구현하면 캐시를 통한 세대 정보 노출, 불완전한 RLS 정책, Neo4j 교차 tenant 조회, 구조화 근거의 추적 불가, outbox 이벤트 역전 같은 문제가 발생할 수 있다. 또한 Accepted ADR과 README·사업계획·디자인 핸드오프가 서로 다른 운영 모델과 MVP 범위를 설명하고 있어 구현자와 디자이너가 잘못된 기준을 선택할 위험이 있다.

권장 수정 순서는 다음과 같다.

1. 캐시의 권한·소유권 격리
2. PostgreSQL RLS 및 composite FK 강화
3. Neo4j tenant 격리 검증
4. 범용 evidence/provenance 모델 설계
5. outbox 순서·멱등성 보장
6. 기준 문서 동기화
7. 실행 가능한 명령과 목표 명령 분리

---

## 2. 발견사항 요약

| ID | 심각도 | 영역 | 발견사항 | 권장 조치 |
|---|---|---|---|---|
| ~~REV-001~~ | ~~P0~~ | ~~캐시/인가~~ | ~~캐시 키에 사용자 권한·소유권이 없음~~ | ~~scope별 캐시 분리 및 principal/revision 포함~~ |
| ~~REV-002~~ | ~~P0~~ | ~~PostgreSQL/RLS~~ | ~~RLS 예제가 강한 tenant 격리를 보장하지 못함~~ | ~~FORCE RLS, WITH CHECK, 역할·pool 계약 추가~~ |
| ~~REV-003~~ | ~~P0~~ | ~~Neo4j/멀티테넌시~~ | ~~tenant 격리가 query-layer 필터 하나에 의존~~ | ~~저장소 격리 spike 및 typed query 강제~~ |
| ~~REV-004~~ | ~~P1~~ | ~~AI 근거~~ | ~~SQL·그래프 도구 결과를 citation 스키마로 표현 불가~~ | ~~범용 evidence/provenance 모델 도입~~ |
| ~~REV-005~~ | ~~P1~~ | ~~데이터 정합성~~ | ~~outbox의 순서·멱등성·삭제 경합 설계 누락~~ | ~~sequence, lease, dedupe, tombstone 추가~~ |
| ~~REV-006~~ | ~~P1~~ | ~~문서 정합성~~ | ~~README·사업계획·핸드오프가 Accepted ADR과 충돌~~ | ~~문서 우선순위 선언 및 전면 동기화~~ |
| ~~REV-007~~ | ~~P1~~ | ~~구현 하네스~~ | ~~존재하지 않는 명령을 현재 실행 명령처럼 안내~~ | ~~현재/목표 명령 분리~~ |
| ~~REV-008~~ | ~~P1~~ | ~~클라이언트 보안~~ | ~~관리비 PWA 오프라인 캐시 정책 없음~~ | ~~민감 데이터 캐시 금지 또는 보호정책 명시~~ |
| ~~REV-009~~ | ~~P2~~ | ~~개인정보~~ | ~~암호화·검색 hash가 구현 수준으로 미정~~ | ~~KMS/envelope encryption/HMAC 구체화~~ |
| ~~REV-010~~ | ~~P2~~ | ~~운영~~ | ~~NFR 수치가 운영 가능한 SLO로 연결되지 않음~~ | ~~측정·오류예산·배포 게이트 정의~~ |

---

## 3. 상세 발견사항

### ~~REV-001 — 캐시 키에 사용자 권한·소유권이 없음~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/08 §2.0 캐시 스코프 4종·개인 의미캐시 금지·히트 후 재검증

**심각도: P0**

#### 근거

- `docs/08-llm-token-optimization.md` §2.1은 정확 캐시 키를 `tenant_id + 정규화 질의 + 문서버전 + 모델`로 정의한다.
- 같은 문서 §2.2는 유사 질의의 의미 캐시 답변 재사용을 허용한다.
- `docs/01-architecture.md` §5.2의 도구 레지스트리는 `get_fees`, `get_my_inquiries`처럼 사용자·세대 소유권에 종속된 결과를 반환한다.

#### 영향

같은 단지의 입주민 A와 B가 동일한 관리비·민원 질문을 하면 A의 응답이 B에게 캐시로 재사용될 수 있다. `tenant_id`만으로는 단지 간 격리는 가능하지만 단지 내부 사용자·세대 간 격리를 보장하지 못한다.

#### 권장 수정

- 캐시를 다음 scope로 구분한다.
  - `tenant-public`: 공개 문서·FAQ
  - `tenant-role`: 관리자 전용 등 역할 기반 데이터
  - `household-private`: 관리비·세대 평면도
  - `user-private`: 본인 민원·대화
- 키에 `principal_scope`, `role`, `visibility`, `household_id` 또는 `user_id`, 원천 revision을 포함한다.
- 관리비·민원·개인 대화는 공유 semantic cache를 기본 금지한다.
- cache hit 이후에도 현재 요청자의 권한과 evidence 접근 가능 여부를 재검증한다.
- 보안 테스트에 같은 tenant 내 사용자 A/B 간 cache poisoning·cross-hit 사례를 추가한다.

#### 완료 기준

- [x] 모든 cacheable response에 명시적인 scope가 있다.
- [ ] private response는 다른 principal에서 hit되지 않는다. (구현 시 검증)
- [ ] 권한·문서 공개범위 변경 시 관련 캐시가 무효화된다. (구현 시 검증)

### ~~REV-002 — RLS 예제가 강한 tenant 격리를 보장하지 못함~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/03 §5 FORCE RLS·WITH CHECK·role 분리·composite FK

**심각도: P0**

#### 근거

`docs/03-database-design.md` §5는 다음 수준의 예제만 제시한다.

```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON documents
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

#### 문제

- table owner는 기본적으로 RLS를 우회할 수 있는데 `FORCE ROW LEVEL SECURITY`가 없다.
- INSERT/UPDATE tenant 변조를 막는 `WITH CHECK`가 없다.
- 애플리케이션 역할의 `BYPASSRLS` 금지와 table ownership 분리가 없다.
- connection pool에서 `SET LOCAL`이 반드시 같은 transaction/connection에 유지된다는 계약이 없다.
- worker·migration·운영자 역할의 권한 경계가 없다.
- 자식 행의 `tenant_id`와 참조 대상의 tenant가 일치하도록 하는 composite FK가 없다.

#### 권장 수정

```sql
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON documents
  FOR ALL
  USING (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
  )
  WITH CHECK (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
  );
```

- migration owner와 runtime role을 분리하고 runtime role에 `BYPASSRLS`를 부여하지 않는다.
- 모든 요청은 transaction wrapper 안에서 tenant/user/role을 설정하고, wrapper 밖 query를 구조적으로 금지한다.
- 부모 테이블에 `UNIQUE (tenant_id, id)`, 자식 테이블에 `FOREIGN KEY (tenant_id, parent_id)`를 사용한다.
- RLS 테스트에 owner role, pool 재사용, context 누락, INSERT/UPDATE tenant 변조를 포함한다.

#### 완료 기준

- [ ] 모든 업무 테이블에 `ENABLE`과 `FORCE RLS`가 적용된다. (구현 시 검증)
- [ ] runtime role이 table owner나 `BYPASSRLS`가 아니다. (구현 시 검증)
- [ ] tenant context가 없으면 읽기·쓰기가 모두 실패한다. (구현 시 검증)
- [ ] cross-tenant FK가 DB constraint로 거부된다. (구현 시 검증)

### ~~REV-003 — Neo4j 격리가 query-layer 필터 하나에 의존~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/11 §4 typed query·관계 tenant 검증·recall 각주·PG 폴백 + docs/07 CRITICAL

**심각도: P0**

#### 근거

- `docs/11-data-architecture.md` §4는 모든 노드에 `tenant_id`를 두고 query layer에서 필터를 주입한다.
- 같은 문서의 벡터 검색 예제는 전역 vector index를 조회한 뒤 `WHERE node.tenant_id = $tenant`로 거른다.

#### 영향

- tenant 필터가 누락된 Cypher 한 건으로 교차 tenant 데이터가 노출될 수 있다.
- 전역 top-K를 먼저 선택하면 다른 tenant의 노드가 후보를 점유하여 현재 tenant의 검색 recall이 낮아질 수 있다.
- 관계 양쪽의 tenant 일치가 저장소 제약으로 보장되지 않는다.

#### 권장 수정

- P0 spike로 Neo4j 배포 버전에서 tenant별 database, label/index 분리, vector pre-filter 지원 가능성을 실측한다.
- raw Cypher 실행을 금지하고 tenant predicate를 구조적으로 포함하는 typed repository/query builder만 허용한다.
- 노드뿐 아니라 관계 생성 시 양 끝 노드의 tenant 일치를 검증한다.
- tenant별 검색 recall과 교차 tenant 침투 테스트를 구축한다.
- Neo4j가 stale/failed 상태이면 facility graph 결과를 제외하고 PG 기반 기본 검색으로 폴백한다.

#### 완료 기준

- [ ] vector 검색이 tenant별 후보군에서 top-K를 계산한다. (구현 시 검증)
- [ ] 필터 누락 query가 코드 리뷰가 아닌 구조적 장치로 차단된다. (구현 시 검증)
- [ ] 모든 관계의 양 끝 tenant가 일치한다. (구현 시 검증)
- [ ] cross-tenant graph 테스트가 배포 차단 게이트다. (구현 시 검증)

### ~~REV-004 — 구조화 도구 결과를 citation 모델로 표현할 수 없음~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/03 §4.3 citations source_kind/source_ref/source_revision/observed_at

**심각도: P1**

#### 근거

`docs/03-database-design.md` §4.3의 `citations`는 `document_id`, `chunk_id`, `quote`, `page`, `clause` 중심이다. 반면 아키텍처는 관리비·민원·시설·그래프 도구 결과도 출처 카드로 표시하도록 요구한다.

#### 영향

“2026-06 확정 관리비 데이터”와 같은 근거의 upload revision, 행 식별자, 조회 시점, graph projection version을 저장하거나 사후 검증할 수 없다. UI의 출처 카드와 감사 로그도 문서 근거만 안정적으로 표현할 수 있다.

#### 권장 수정

범용 evidence 모델을 도입한다.

```text
evidence(
  id, tenant_id, message_id,
  evidence_type,       -- document_chunk|fee_snapshot|inquiry|facility|graph_projection
  source_ref,
  source_revision,
  observed_at,
  display_label,
  excerpt,
  provenance_json
)
```

- 문서 인용은 evidence의 한 subtype으로 취급한다.
- 구조화 데이터는 immutable snapshot 또는 재현 가능한 revision을 참조한다.
- 사용자에게 노출할 label과 내부 provenance를 분리한다.
- evidence가 현재 사용자에게 공개 가능한지 응답 직전 재검증한다.

### ~~REV-005 — outbox 순서·멱등성·삭제 경합 설계 누락~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/03 §4.9 sequence·dedupe_key·SKIP LOCKED·last_applied_version·tombstone·DLQ

**심각도: P1**

#### 근거

`docs/03-database-design.md` §4.9와 `docs/11-data-architecture.md` §3.5는 `status`, `attempts`, `created_at` 및 “순차 폴링”만 정의한다.

#### 영향

여러 worker와 retry가 동시에 존재하면 오래된 update 이벤트가 최신 상태를 덮어쓸 수 있다. delete 이후 지연된 update가 실행되면 삭제된 그래프 노드가 재생성될 수도 있다.

#### 권장 수정

- aggregate별 monotonic `sequence` 또는 `source_version` 추가
- `event_id`/deduplication key unique constraint 추가
- claim 상태, lease 만료, `FOR UPDATE SKIP LOCKED` 처리 계약 명시
- Neo4j 노드에 `last_applied_version`을 저장하고 더 오래된 이벤트 거부
- delete tombstone과 보존기간 정의
- 최대 retry 이후 DLQ 및 운영자 재처리 절차 정의
- projection lag, last success, failed aggregate를 모니터링

### ~~REV-006 — 기준 문서와 과거 문서가 서로 다른 제품을 설명~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/README 문서 우선순위 + docs/10 역사적 배너 + 핸드오프 카피 교체

**심각도: P1**

#### 충돌 사례

| 문서 | 현재 표현 | Accepted 기준 |
|---|---|---|
| `README.md` | 관리비는 ERP 단일 출처 | ADR-0006: 현재 엑셀 확정 업로드 |
| `README.md` | 외부 LLM API, Claude 우선 | ADR-0005: 단일 OpenAI-compatible endpoint |
| `design-handoff-prompt.md` | ERP 데이터·ERP 시점 | 현재는 엑셀 upload/revision 기준 |
| `10-project-plan.md` | Claude/GPT + 필요 시 sLLM | 단일 모델을 env로 교체 |
| `10-project-plan.md` | 관리비·시설은 Phase 2 | SRS에서는 MVP 포함 |
| `10-project-plan.md` | STT 회의록 요약 Phase 2 | SRS에서는 MVP 제외·추후 |

#### 권장 수정

문서 우선순위를 명시한다.

1. Accepted ADR
2. SRS (`00-requirements.md`)
3. Architecture/data/security 문서
4. Implementation plan
5. README·사업계획·디자인 핸드오프

하위 문서는 상위 결정의 요약만 담고 독자적인 기술 결정을 반복하지 않도록 한다. superseded 내용은 삭제하거나 명시적인 “역사적 배경” 블록으로 격리한다.

### ~~REV-007 — 구현 가이드가 현재 실행 불가능한 명령을 안내~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/09 §2 현재/도입 후 명령 분리

**심각도: P1**

#### 근거

`docs/09-implementation-harness.md`는 현재 존재하지 않는 다음 항목을 실행 명령처럼 제시한다.

- `infra/docker-compose.yml`
- `pnpm db:migrate`
- `pnpm db:seed`
- `pnpm prettier --check`
- `pnpm e2e`

현재 루트 `package.json`에는 `dev`, `build`, `lint`, `typecheck`, `test`, `start`, `check:paths`만 존재한다.

#### 권장 수정

- `현재 실행 가능한 명령`과 `목표 패키지 도입 후 추가할 명령`을 분리한다.
- 목표 명령에는 도입 조건과 담당 package를 표시한다.
- CI 문서는 실제 workflow가 추가된 뒤 경로와 job 이름을 기록한다.
- README와 AGENTS의 명령 목록을 root `package.json`과 자동 비교하는 문서 검증 스크립트를 고려한다.

### ~~REV-008 — 관리비 PWA 오프라인 캐시의 개인정보 정책 없음~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/05 §7·docs/06 §6 no-store·tenant-public만·purge

**심각도: P1**

#### 근거

`docs/05-ui-ux-design.md` §7은 “공지/관리비 마지막 조회 캐시”를 요구한다. `docs/06-security-privacy.md`에는 service worker, 브라우저 저장소, 로그아웃 시 삭제, TTL, 공유 단말 정책이 없다.

#### 권장 수정

우선안은 관리비·민원·개인 대화를 service worker cache에서 제외하는 것이다. 오프라인 제공이 필수라면 다음을 문서화해야 한다.

- 사용자/세대별 저장 영역 분리
- 짧은 TTL과 화면 재인증
- logout, inactive 전환, 계정 변경 시 즉시 purge
- `Cache-Control: no-store` 적용 대상
- 브라우저 뒤로가기 및 shared-device threat model
- 오프라인 화면에 데이터 기준 시점과 stale 표시

### ~~REV-009 — PII 암호화·검색 설계가 구현 수준으로 충분하지 않음~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/03 §6·docs/06 §4.1 KMS envelope·keyed HMAC 방향

**심각도: P2**

#### 근거

`docs/03-database-design.md` §6과 `docs/06-security-privacy.md` §4.1은 PII를 암호화하고 salted hash로 검색한다고만 정의한다.

#### 문제

일반적인 per-record salted hash는 이름·전화번호의 정확 대조 검색에 직접 사용할 수 없다. 반대로 단순 deterministic hash는 전화번호·생년월일처럼 값 공간이 작은 데이터에 대해 사전 대입 공격에 취약하다.

#### 권장 수정

- KMS 기반 envelope encryption 구조와 key version 정의
- tenant 또는 환경별 DEK 정책과 rotation 절차 정의
- 검색용 값은 정규화 후 keyed HMAC로 생성
- 전화번호·이름·생년월일의 정규화 규칙 정의
- old/new key 동시 조회와 migration 기간 정의
- 복호화는 제한된 application service에서만 수행하고 일반 DB view가 자동 복호화하지 않도록 검토

### ~~REV-010 — NFR 수치가 운영 가능한 SLO로 연결되지 않음~~ ✅ 반영(2026-07-13)

> 반영 위치 — docs/00 §4 측정 계약 각주

**심각도: P2**

#### 근거

`docs/00-requirements.md` §4에는 p95 응답 지연, 99.5% 가용성, 환각률, Top-5 적중률 등이 있지만 측정 계약과 오류 예산이 없다.

#### 권장 수정

- 측정 구간, 최소 표본 수, 제외 조건 정의
- first-token latency와 complete-response latency 분리
- provider/model/tenant/query-type별 metric dimension 정의
- fallback을 성공·부분 성공·실패 중 무엇으로 집계할지 결정
- 99.5%에 대응하는 월 오류 예산과 소진 시 배포 정책 정의
- AI eval 경고를 배포 차단으로 승격하는 조건 정의
- 파일럿 보정의 승인자와 ADR/SRS 갱신 절차 정의

---

## 4. 문서별 리뷰 결과

| 문서 | 평가 | 주요 조치 |
|---|---|---|
| ~~`README.md`~~ | ~~수정 필요~~ | ~~ERP·Claude 우선 표현을 Accepted ADR과 동기화~~ |
| ~~`AGENTS.md` / `CLAUDE.md`~~ | ~~대체로 양호~~ | ~~두 파일 중복 관리 정책과 자동 동기화 여부 결정~~ |
| ~~`ARCHITECTURE.md`~~ | ~~대체로 양호~~ | ~~목표 컴포넌트 승격 조건과 graph failure fallback 보강~~ |
| ~~`00-requirements.md`~~ | ~~양호~~ | ~~운영 SLO 측정 계약과 프로젝트 계획의 MVP 충돌 해소~~ |
| ~~`01-architecture.md`~~ | ~~보강 필요~~ | ~~캐시 scope, evidence, graph staleness 정책 추가~~ |
| ~~`02-directory-structure.md`~~ | ~~보강 필요~~ | ~~ERP 중심 잔여 설명과 현재/목표 구조 구분 재검토~~ |
| ~~`03-database-design.md`~~ | ~~중요 수정~~ | ~~RLS, composite FK, evidence, outbox, PII crypto 구체화~~ |
| ~~`04-menu-structure.md`~~ | ~~대체로 양호~~ | ~~기능 scope가 SRS와 계속 일치하는지 추적~~ |
| ~~`05-ui-ux-design.md`~~ | ~~보강 필요~~ | ~~private offline cache 정책 및 stale 표시 추가~~ |
| ~~`06-security-privacy.md`~~ | ~~중요 수정~~ | ~~client cache, Neo4j 격리, key management 보강~~ |
| ~~`07-testing-strategy.md`~~ | ~~보강 필요~~ | ~~같은 tenant 내 소유권·cache·graph 침투 테스트 추가~~ |
| ~~`08-llm-token-optimization.md`~~ | ~~중요 수정~~ | ~~캐시 키와 private semantic cache 금지 정책 수정~~ |
| ~~`09-implementation-harness.md`~~ | ~~수정 필요~~ | ~~현재 존재하는 명령과 목표 명령 분리~~ |
| ~~`10-project-plan.md`~~ | ~~전면 동기화 필요~~ | ~~MVP, LLM, ERP, STT, 기술 구성 갱신~~ |
| ~~`11-data-architecture.md`~~ | ~~중요 수정~~ | ~~Neo4j tenant spike와 outbox versioning 추가~~ |
| ~~`design-handoff-prompt.md`~~ | ~~수정 필요~~ | ~~ERP 카피를 엑셀 확정 upload 기준으로 변경~~ |
| ~~ADR~~ | ~~대체로 양호~~ | ~~ADR-0002의 과거 external-only 문구를 0005와 명시적으로 연결~~ |

---

## 5. 권장 검증 게이트

> 설계 반영 완료. 체크박스는 **구현 단계 검증 게이트**로 유지.

### P0 — 실제 tenant 데이터 도입 전

- [ ] cache scope 모델 및 같은 tenant 내 A/B 사용자 격리 테스트
- [ ] `FORCE RLS`, `WITH CHECK`, runtime role 분리
- [ ] 모든 tenant FK의 composite constraint 전략 확정
- [ ] Neo4j tenant vector 검색 spike와 교차 tenant 침투 테스트
- [ ] private client cache 정책 확정

### P1 — RAG/도구호출 구현 전

- [ ] 범용 evidence/provenance 스키마 확정
- [ ] outbox sequence·dedupe·lease·DLQ 설계 확정
- [ ] graph projection revision/staleness 및 fallback 정의
- [ ] README·사업계획·디자인 핸드오프 동기화
- [ ] 구현 하네스 명령을 실제 `package.json`과 일치시킴

### P2 — 파일럿 운영 전

- [ ] PII key management와 searchable HMAC 설계 확정
- [ ] SLO 측정 규칙·오류 예산·알림 정의
- [ ] AI eval 차단 기준과 수동 검수 표본 정책 확정
- [ ] 백업·복구·파기·graph 재구성 리허설

---

## 6. 긍정적 평가

- PostgreSQL SoR + Neo4j 파생 projection의 책임 분리가 명확하다.
- PG와 Neo4j의 직접 이중 쓰기를 금지하고 outbox를 선택한 방향이 적절하다.
- 관리비 계산·부과에 LLM을 개입시키지 않는 원칙이 명확하다.
- 공지 자동발송 금지와 사람 검수 흐름이 요구사항·UI·테스트에 반영되어 있다.
- 근거 없는 답변을 사람 연결로 폴백하는 정책이 일관적이다.
- self-hosted를 포함한 전 프로바이더에 fail-closed 마스킹을 적용한 결정이 안전하다.
- 생성 모델을 단일 OpenAI-compatible endpoint로 추상화하고 임베딩 차원을 고정한 결정은 초기 운영 복잡도를 줄인다.
- 보안 격리와 AI 품질을 별도 테스트 게이트로 다루려는 방향이 좋다.

## 7. 최종 판정

현재 설계는 **구현 가능한 기반을 갖췄지만 보안·정합성 P0가 남아 있는 조건부 승인 상태**다. UI 골격이나 합성 데이터 기반 prototype은 진행할 수 있다. 다만 REV-001~003이 해결되기 전에는 실제 입주민·관리비·민원 데이터를 사용하는 파일럿을 시작하지 않는 것이 안전하다.

P0 해결 후 evidence/outbox와 문서 기준선을 확정하면 본격 구현 단계로 전환할 수 있다.
