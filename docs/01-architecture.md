# 01. 아키텍처 설계서

> 요구사항: [00-requirements.md](00-requirements.md) · 인덱스: [README.md](README.md)

## 1. 아키텍처 원칙

1. **AI는 계층, 제품이 아니다.** 기존 시스템/문서 위에서 검색·응대·요약만 담당.
2. **출처 없는 답변은 내보내지 않는다.** 인용 강제 + 폴백.
3. **단일 출처(SSOT).** 관리비 원천은 확정 업로드 데이터(현재 엑셀, 추후 ERP), AI는 읽기·설명만.
4. **개인정보는 경계에서 차단.** 모든 LLM 호출 전 마스킹(self-hosted 포함).
5. **테넌트 격리 우선.** 모든 데이터/쿼리는 단지 단위 격리.
6. **사람이 최종 결정.** 위험 출력은 검수 게이트.
7. **토큰은 비용이다.** 캐싱·컨텍스트 예산·에이전트 스텝 상한을 1급 설계 요소로(단일 모델, 라우팅 보류).
8. **단일 LLM + OpenAI-호환 추상화.** 프로바이더는 env로 교체(Ollama·vLLM·OpenAI 등). 멀티 모델 라우팅은 필요 검증 후.

## 2. C4 — 시스템 컨텍스트 (L1)

```text
        ┌─────────────┐      ┌─────────────┐      ┌──────────────┐
        │   입주민      │      │ 관리사무소    │      │ 시스템 관리자  │
        │ (반응형 웹)   │      │ (관리자 웹)   │      │  (운영 콘솔)   │
        └──────┬──────┘      └──────┬──────┘      └──────┬───────┘
               │                    │                    │
               └─────────┬──────────┴─────────┬──────────┘
                         ▼                     ▼
                  ┌───────────────────────────────────┐
                  │            LIVIQ 플랫폼              │
                  └───┬───────────────┬────────────┬───┘
                      │               │            │
              ┌───────▼──────┐ ┌──────▼─────┐ ┌────▼─────────┐
              │ (추후) ERP    │ │ LLM 서버    │ │ (추후)        │
              │ (읽기 전용)   │ │ (API)      │ │ 본인확인       │
              └──────────────┘ └────────────┘ └──────────────┘
```

## 3. C4 — 컨테이너 (L2)

```text
[web-resident]  Next.js (PWA)  ─┐
[web-admin]     Next.js        ─┤── HTTPS ──► [api]  FastAPI (BFF + 도메인 API)
                                 │                 │
                                 │                 ├─► [PostgreSQL + pgvector]  (주 DB=SoR, 벡터 색인)
                                 │                 ├─► [Neo4j]                  (시설 파생 그래프·시설 벡터)
                                 │                 ├─► [Redis]                  (캐시, 세션, 큐 브로커)
                                 │                 ├─► [Object Storage]         (원본 문서·이미지)
                                 │                 └─► [ai-core 모듈]           (오케스트레이션)
                                 │                          │
                                 │                          └─► LLM/임베딩 (OpenAI-호환: Ollama·vLLM 등)
[ai-worker]  Python 워커 (arq)  ─┘  인제스트·임베딩·OCR·graph-sync(outbox→Neo4j) (비동기)
```

| 컨테이너 | 역할 | 스택 |
|----------|------|------|
| `web-resident` | 입주민 반응형 웹/PWA | Next.js(App Router), React, TS |
| `web-admin` | 관리자 콘솔(MANAGER·STAFF·SYS_ADMIN 뷰) | Next.js, React, TS |
| `api` | 인증·인가·도메인 API·BFF, AI 오케스트레이션 진입점 | FastAPI, Python |
| `ai-worker` | 비동기 인제스트(청킹/임베딩/OCR), graph-sync(outbox→Neo4j), 평가 배치 | Python, arq |
| `db` | 관계형 + 벡터 색인 (SoR) | PostgreSQL 16 + pgvector(HNSW) |
| `graph` | 시설 도메인 파생 그래프 + 시설 텍스트 벡터(재생성 가능) | Neo4j |
| `cache/queue` | 응답 캐시·세션·작업 큐 | Redis |
| `storage` | 원본 파일 | S3 호환 오브젝트 스토리지 |

> 공유 도메인/타입/AI 로직은 `packages/`로 분리(=[02](02-directory-structure.md)). `ai-core`는 라이브러리로 시작하고, 부하가 커지면 별도 서비스로 분리(인터페이스 동일 유지).

## 4. 멀티테넌시

- 모델: **단일 DB · 공유 스키마 · `tenant_id` 행 격리** + PostgreSQL **RLS**.
- 모든 테이블에 `tenant_id`(=단지). 모든 쿼리는 세션 컨텍스트(`app.tenant_id`)로 강제 필터.
- 벡터 검색도 `WHERE tenant_id = $` 선필터 후 ANN. (단지 간 문서 혼입 절대 차단)
- 상세 정책·RLS 정의: [03-database-design.md](03-database-design.md) §RLS.

## 5. RAG 파이프라인

### 5.1 인제스트 (비동기, ai-worker)

```text
업로드 → 포맷 판별 → (필요시 OCR) → 정규화/클린징 → 청킹 → 임베딩 → pgvector upsert → 색인상태 갱신
                                                          │
                                              메타(문서ID·페이지·조항·공개범위) 태깅
```
- PDF 파싱: opendataloader-pdf(Apache-2.0, 로컬 실행 — 개인정보 외부 미전송). HWP·이미지 OCR은 별도 도구 병행.
- 청킹: 구조 인지(조/항/표 경계) + 토큰 상한, 오버랩 최소화(토큰 절약, [08](08-llm-token-optimization.md)).
- 임베딩: 단지별 색인, 차원/모델은 [03](03-database-design.md) 고정.
- 멱등성: 문서 해시로 중복 방지, 버전 변경 시 증분 재색인.

### 5.2 질의 (동기, api + ai-core)

정적 라우터(의도분류가 경로 1개 선택, 고정 파이프라인)가 아니라 **읽기 전용 도구호출 에이전트**로 처리한다. LLM은 도구 레지스트리를 보고 필요한 도구를 선택·조합하고, 실제 실행·검증은 코드가 담당한다.

```text
질의 → [캐시 확인(정확/의미)] ─히트─► 즉시 응답 (에이전트 미진입)
                            └미스─► [의도분류] ─사람연결─► 검수 큐/담당자
                                              └AI처리─► [도구호출 에이전트 루프]
                                                          │  도구 레지스트리에서 선택·조합
                                                          │  스텝 상한 2~3회(도구 호출 수·토큰 예산)
                                                          │  초과 시 현재 근거로 답변 또는 폴백
                                                          ▼
                          PII 마스킹(도구 결과 포함) → LLM 생성(출처 강제)
                        → 후처리(인용·근거 검증·신뢰도) → [신뢰도 낮음/근거 0? → 폴백]
                        → 응답(스트리밍, 출처 카드: 문서 인용 + 도구 결과 근거)
```

도구 레지스트리(전부 **읽기 전용** — 파라미터 Pydantic 검증·tenant/소유권은 코드가 강제, LLM은 선택만):

| 도구 | 소스 | 용도 | 권한 스코프 |
|------|------|------|-------------|
| `search_documents` | pgvector 벡터검색 | 공지·규약·회의록 등 문서 근거 검색 | tenant + 문서 공개범위(visibility) |
| `search_facility_graph` | Neo4j 벡터매칭 + 그래프 확장 | 유사 장애·연결 설비·정비 이력 → 원인 후보 | tenant + 시설 역할 |
| `get_fees` | 고정 SQL(`fees`) | 본인 세대 관리비·항목·전월 대비 | tenant + 본인 세대 소유권 |
| `get_my_inquiries` | 고정 SQL(`inquiries`) | 본인 민원 접수·처리 상태 | tenant + 본인 소유권 |
| `get_facilities` | 고정 SQL(`facilities`) | 설비 목록·현재 상태 | tenant + 역할 |
| `get_overdue_checks` | 고정 SQL(`facilities`) | 점검 기한 임박·초과 설비 | tenant + 역할 |

> 캐시는 에이전트 앞단에서 먼저 확인([08](08-llm-token-optimization.md)) — 히트면 에이전트에 진입하지 않는다. 도구 결과도 문서 인용과 동일 원칙으로 **출처 카드**에 표기하고(예: "근거: 관리비 2026-06 확정 데이터"), 어떤 도구를 왜 호출했는지 **경로를 로깅**해 골든셋 회귀 평가에 활용한다([07](07-testing-strategy.md) §AI eval).
> 시설형 질의의 그래프 질의·Neo4j 벡터 인덱스·데이터 배치는 [11-data-architecture.md](11-data-architecture.md).

### 5.3 평가 루프

- 골든셋(질문·정답·근거) 기반 자동 평가(적중률·환각률) + 표본 수동 채점.
- 👎 피드백 → 골든셋 후보 → 회귀 평가. 상세: [07-testing-strategy.md](07-testing-strategy.md) §AI eval.

## 6. AI 오케스트레이션 (api 내부 ai-core)

| 단계 | 책임 | 실패/폴백 |
|------|------|-----------|
| 의도 분류 | AI 처리/사람연결 1차 분기(캐시는 앞단 선조회, 데이터 소스 선택은 에이전트) | 불확실 → 사람연결 |
| 도구 선택·실행(에이전트, 스텝 상한) | 도구 레지스트리에서 선택·조합, 근거 후보 확보 | 근거 0 → "모름" 폴백 / 상한 초과 → 현재 근거로 답변/폴백 |
| PII 마스킹 | 이름·동호수·연락처 가명화(도구 결과 포함) | 마스킹 실패 → 호출 중단 |
| 생성 | 출처 인용 답변(문서·도구 결과 근거) | LLM 오류 → 재시도→폴백 |
| 후처리 | 인용 실재 검증, 신뢰도 산출(입력=검색 점수·인용 검증 결과·자기평가, 임계값은 파일럿 보정) | 인용 불일치 → 폴백 |
| 도구 파라미터 검증(코드) | 시스템 프롬프트가 아닌 **코드 레벨**로 tenant·소유권·읽기전용 강제 | 검증 실패 → 도구 실행 거부 |

> 권한·발송 같은 부수효과는 LLM이 직접 수행하지 않는다. LLM은 "의도/초안"만 만들고, 실제 액션은 검증된 도메인 서비스가 실행한다.

## 7. 토큰 절약 전략 (요약)

캐싱(스코프별)·컨텍스트 예산·프롬프트 캐시·청크 최적화. 상세 설계·수치는 [08-llm-token-optimization.md](08-llm-token-optimization.md).

## 8. 동기/비동기 경계

- **동기(요청-응답)**: 검색형 질의(스트리밍), 화면 조회, 액션 실행.
- **비동기(큐)**: 문서 인제스트, OCR, 임베딩 재색인, 평가 배치, 알림 발송.
- 브로커: Redis + arq. 작업 상태는 `jobs` 테이블로 추적([03](03-database-design.md)).

## 9. 관측성 (Observability)

- **로그**: 구조화(JSON), `tenant_id`·`request_id`·`user_role` 포함. 개인정보는 로그에도 마스킹.
- **메트릭**: API 지연, 큐 적체, 캐시 적중률, **LLM 토큰/비용/질의당**, 환각·폴백율.
- **트레이싱**: 질의→검색→LLM→응답 스팬.
- **AI 품질 대시보드**: 자동해결률, 👍/👎, 신뢰도 분포, 골든셋 회귀 결과.

## 10. 장애 격리 / Graceful Degradation

| 의존성 장애 | 동작 |
|-------------|------|
| LLM 엔드포인트 다운 | 검색 결과(발췌)만 출처와 함께 제공 + "AI 요약 일시 불가" |
| 임베딩 API 다운 | 키워드/전문 검색으로 폴백 |
| 관리비 데이터 미확보 | 관리비 "조회 일시 불가" 안내, 최근 확정 업로드(엑셀) 데이터 기준 시점 표기 |
| Redis 다운 | 캐시 미스로 동작(성능 저하), 큐는 재시도 |

## 11. 기술 스택 (확정)

| 영역 | 선택 | 근거 |
|------|------|------|
| 언어 | 웹=TypeScript · 백엔드=Python 3.12+ | 표면별 최적 생태계, 타입은 OpenAPI 생성물로 공유([ADR-0013](adr/0013-python-backend.md)) |
| 모노레포 | Turborepo + pnpm(TS) · uv workspace(Python) | 캐시 빌드, 워크스페이스, 단일 lock |
| 프론트 | Next.js(App Router), React | SSR/PWA, 사용자 web 규칙 |
| 백엔드 | FastAPI (Pydantic v2, sse-starlette) | async 네이티브, 스키마 검증·SSE 스트리밍, AI 생태계 정합 |
| ORM | SQLAlchemy 2.0(async) + Alembic | async 세션, 마이그레이션, RLS SQL 병행 |
| DB | PostgreSQL 16 + pgvector | 관계형+벡터 단일화 (SoR) |
| 그래프 | Neo4j | 시설 그래프·시설 텍스트 벡터, 파생/재생성 가능 |
| 캐시/큐 | Redis + arq | 캐시·세션·비동기(async·cron 내장) |
| 검증 | Pydantic v2(서버) + Zod(웹 폼) | 경계 입력 검증, 계약은 OpenAPI 생성 |
| 인증 | 이메일+비밀번호 자체 인증(+명부 대조 승인) | Argon2id 해시·이메일 검증·초대 토큰([ADR-0014](adr/0014-local-email-auth.md), [00 FR-ONB]) |
| LLM | OpenAI-호환 단일 엔드포인트(Ollama·vLLM·OpenAI 등, env 교체) | 벤더 중립, 성능비교 용이, [08] |
| 임베딩 | bge-m3(1024, Ollama/vLLM 로컬 실행) | 한국어 강함, 차원 고정([03]) |
| 스토리지 | S3 호환 | 원본 문서·이미지 |
| 테스트 | Vitest·Playwright(웹) · pytest(백엔드) · AI eval 하네스 | [07] |
| 관측성 | OpenTelemetry + 로그 수집 | 표준 |

> 생성 모델은 **동시에 하나만** 운영. 선정·교체는 골든셋 회귀 평가([07](07-testing-strategy.md))로 결정하며, 교체는 env 설정 변경만으로 가능.

## 12. 주요 결정 요약 (정본: [docs/adr/](adr/README.md))

정본 결정 기록은 [docs/adr/](adr/README.md)다. 아래는 요약이며, 정본 파일이 있는 결정은 링크한다.

| ADR | 결정 | 대안 | 이유 |
|-----|------|------|------|
| — | pgvector(단일 DB) | 별도 Vector DB(Qdrant) | 운영 단순, 규모 커지면 이전 |
| [0005](adr/0005-single-llm-openai-compat.md) | 단일 LLM + OpenAI-호환 추상화(env로 프로바이더 교체) | 특정 벤더 고정 / 멀티 모델 라우팅 | 벤더 중립·성능비교 용이·운영 단순 |
| — | RLS 행 격리 멀티테넌시 | DB/스키마 분리 | 운영·비용 효율, 격리 보증은 RLS |
| — | ai-core 라이브러리 | 처음부터 마이크로서비스 | YAGNI, 인터페이스로 분리 대비 |
| — | 액션은 코드가 실행 | LLM 함수호출 직접 실행 | 권한·부수효과 통제 |
| — | 반응형 웹/PWA(입주민) | 네이티브 앱 | 빠른 구축, 심사 불필요 |
| — | Neo4j = 시설 전용 파생 그래프(PG가 SoR, outbox 동기화) | Neo4j를 SoR로 / 단일 PG | 정합성·격리·백업 단순 + 그래프 탐색 확보 |
| [0006](adr/0006-fees-excel-upload-source.md) | 관리비 원천 = 엑셀 업로드(ERP 어댑터는 추후) | ERP 미러 | ERP 부재, 어댑터 인터페이스로 병행 대비 |
| [0007](adr/0007-readonly-tool-agent.md) | 읽기 전용 도구호출 에이전트 + 스텝 상한(정적 라우터 대체) | 정적 라우터 유지 / 자유 ReAct 루프 | 복합 질의 커버 + 비용·평가 통제. 쓰기는 도구 제외로 규칙 8 유지 |
| [0013](adr/0013-python-backend.md) | 백엔드 전면 Python(FastAPI·arq·SQLAlchemy+Alembic·ai-core) | 기존 TS 백엔드 스택 유지 | AI/데이터 생태계 정합, mcp 자산 재사용, 웹↔api 타입은 OpenAPI 생성 |

> `—` 행은 요약만 있고 정본 ADR 파일이 없다(pgvector·RLS·ai-core 라이브러리·액션 코드 실행·PWA·Neo4j 파생 그래프) — 정본이 필요하면 [docs/adr/](adr/README.md)에 추가한다. 마스킹([ADR-0002](adr/0002-mask-before-external-llm.md))·모노레포+AI 계층([ADR-0001](adr/0001-monorepo-layered-ai.md))도 정본 파일 참조.
> ADR 변경은 [docs/adr/](adr/README.md)에 새 ADR로 기록하고 이전 결정은 Superseded 처리한다.

## 13. REST API 표면 (v1 — H2 확정 · H3 시설 추가 · H7 인증 재설계)

> **필드 계약의 원천은 `apps/api`의 Pydantic 모델**([09 §1.1](09-implementation-harness.md))이다. 이 절은 **엔드포인트 목록·인가 역할·화면 매핑·불변식**을 소유한다 — 필드 상세를 여기 중복 기술하지 않는다. 화면 트리는 [04](04-menu-structure.md).

### 13.1 공통 규약

- 관리자 전용 경로는 `/admin/*` 접두 + 역할 가드. 접두는 가독성용일 뿐 **인가는 항상 서버 의존성 가드**([06 §2](06-security-privacy.md)).
- 모든 엔드포인트: 세션 인증 → 테넌트 컨텍스트(`SET LOCAL app.tenant_id`) → 역할 → 소유권 순 검증. 목록은 페이지네이션(`page`·`limit`, 응답 `items`·`total`).
- AI 응답 스트리밍은 전부 [09 §1.1](09-implementation-harness.md)의 SSE 4이벤트 계약(`status`·`token`·`citation`·`done`)을 재사용한다.
- local 개발 한정 `X-Dev-Tenant-Id`/`X-Dev-User-Id` 헤더 인증은 H2-1에서 세션으로 대체하고 `API_ENV=local`에서만 동작하도록 격리 유지.

### 13.2 엔드포인트 (도메인별)

**인증·온보딩** (H7-1 · [ADR-0011](adr/0011-redis-server-session.md)·[ADR-0014](adr/0014-local-email-auth.md), [06 §2](06-security-privacy.md), 화면: 온보딩)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `GET /auth/tenants` | 공개 | 가입 단지 선택 목록(이름만, 시스템 테넌트 제외 — H7-5, [ADR-0014](adr/0014-local-email-auth.md) 개정) |
| `POST /auth/signup` | 공개 | 단지 선택(또는 가입 링크 `?t=` 사전 선택) + 이메일+비밀번호 가입 → 이메일 검증 메일 발송(검증 전 로그인 불가) |
| `POST /auth/login` | 공개 | 이메일+비밀번호 검증 → 세션 확립. 계정 상태별 분기(신규→온보딩, pending→대기, active→홈) |
| `GET /auth/verify-email` | 공개 | 검증 토큰(`auth_tokens`) 확인 → `email_verified_at` 기록 |
| `POST /auth/password-reset` · `/password-reset/confirm` | 공개 | 재설정 토큰 메일 발송 → 링크에서 새 비밀번호 설정 |
| `POST /auth/invite/accept` | 공개 | 초대 토큰(소장·직원) 확인 → 비밀번호 설정·계정 활성화(수락=이메일 소유 증명) |
| `POST /auth/password-change` | 세션 | 현재+새 비밀번호. `must_change_password`(임시비번) 계정은 이 호출 전까지 콘텐츠 403 |
| `POST /auth/logout` | 세션 | 세션 revoke |
| `GET /me` | 세션(모든 상태) | 역할·계정 상태·로그인 이메일 — 상태별 화면 분기의 단일 출처 |
| `POST /onboarding/profile` | 세션(신규) | 동의·성함·생년월일·동·호 → 명부 자동 대조 → `pending`(초대코드 제거) |

**계정 승인·명부·초대** (H2-1·H7-2, 화면: 관리자 가입 승인·직원 관리·SYS_ADMIN 뷰)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `GET /admin/approvals` | MANAGER | 대기 목록(명부 일치 배지 = `roster_matched`) — 자동 승격 없음 |
| `POST /admin/approvals/{user_id}/approve` · `/reject` | MANAGER | 거절은 사유 필수. 상태 전환 시 대상 세션 즉시 revoke + 알림 생성 |
| `POST /admin/roster/upload` | MANAGER | 명부 엑셀 → `excel_uploads(type=roster)` → 사전등록 diff 병합([03 §4.1](03-database-design.md)) |
| `POST /admin/staff/invite` | MANAGER | 직원(STAFF) 초대 링크 메일(`auth_tokens` invite, TTL 7d) |
| `GET /admin/staff` | MANAGER | 직원 목록(역할·상태·초대일·이메일 — 복호는 인가 뒤, H7-5) |
| `POST /admin/staff/{user_id}/deactivate` | MANAGER | STAFF 비활성화(inactive + 세션 즉시 revoke). 자신·MANAGER 대상 400 |
| `DELETE /admin/staff/{user_id}` | MANAGER | 직원·타 소장 **삭제**(소프트 삭제+PII 비식별+세션 revoke). 자기 자신 400 (H7-6) |
| `GET /admin/roster/template` | MANAGER | 명부 업로드 양식 xlsx 다운로드(헤더+예시 행 — 파서와 단일 출처, H7-7) |
| `GET /admin/roster` | MANAGER | 명부 목록(동·호·성함 마스킹·상태: 미가입/가입완료/전출후보) + 총계 + 마지막 업로드 요약 — 검색·페이지네이션 (H7-9) |
| `POST /admin/tenants` | SYS_ADMIN | 단지 생성(시스템 테넌트 권한, 단지 콘텐츠 비열람) |
| `GET /admin/tenants` | SYS_ADMIN | 단지 목록(시스템 테넌트 제외) — 단지 상태·현재 소장(이메일·상태) 포함 (H7-6) |
| `POST /admin/tenants/{id}/invite-manager` | SYS_ADMIN | 소장(MANAGER) 초대 링크 메일(`auth_tokens` invite). **단지당 1명** — 활성/초대중 존재 시 409 (H7-6) |
| `DELETE /admin/tenants/{id}/manager` | SYS_ADMIN | 현재 소장 삭제(소프트 삭제+PII 비식별) — 소장 교체·오초대 해소 (H7-6) |
| `DELETE /admin/tenants/{id}` | SYS_ADMIN | **빈 단지만** 완전 삭제(주민·콘텐츠 존재 시 409) (H7-6) |
| `POST /admin/tenants/{id}/deactivate` · `/activate` | SYS_ADMIN | 단지 비활성화(소속 로그인 403·가입 목록 제외·세션 revoke)/재활성화 (H7-6) |

**AI 비서** (H1 구현됨, 화면: 입주민 AI 비서)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `POST /assistant/ask` | RESIDENT+ | SSE. 계약은 [09 §1.1](09-implementation-harness.md) — 불변 |

**문서** (H1 구현·H2-2 보강, 화면: 관리자 문서 관리)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `POST /documents` | MANAGER·STAFF | 구현됨 — 업로드→S3→인제스트 큐, `content_hash` 멱등 |
| `GET /documents` | MANAGER·STAFF | 구현됨 — H2-2에서 `index_status` 필터 추가 |
| `PATCH /documents/{id}` | MANAGER·STAFF | H2-2 — 공개범위(visibility)·제목 수정 |
| `POST /documents/{id}/reindex` | MANAGER·STAFF | H2-2 — 재색인(failed 복구) |

**민원** (H2-3, 화면: 입주민 민원·하자 / 관리자 민원 관리)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `POST /inquiries` | RESIDENT | 접수. AI 카테고리·우선순위는 서버가 **제안값**으로 채움(키워드 기반, [03 §4.4](03-database-design.md)) |
| `GET /inquiries` | RESIDENT | **본인 `author_user_id` 한정**(세대 공유 제외 — FR-RES-02) |
| `GET /inquiries/{id}` + `/events` | 작성자 또는 MANAGER·STAFF | 타임라인 = `inquiry_events` 순차 |
| `GET /admin/inquiries` | MANAGER·STAFF | 접수함(상태·카테고리 필터) |
| `POST /admin/inquiries/{id}/assign` · `/status` | MANAGER·STAFF | 상태 머신 `received→assigned→in_progress→done`(역행은 관리자만). 변경 시 `inquiry_events` 기록 + 작성자 알림 |

**공지** (H2-4, 화면: 입주민 공지 / 관리자 공지 관리)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `GET /notices` · `/notices/{id}` | RESIDENT+ | `audience`·역할 필터 |
| `POST /admin/notices/drafts` | MANAGER·STAFF | 키워드→AI 초안(`notice_drafts`). **출처 인용 강제** — 근거 문서 없으면 초안 생성 거절 |
| `GET /admin/notices/drafts/{id}` | MANAGER·STAFF | 초안·인용 확인(검수 화면) |
| `POST /admin/notices` | MANAGER | **발송·예약은 사람 확정만**(AI 초안 승인 후 승격). published 시 대상자 알림 생성 |

**관리비** (H2-5 · [ADR-0006](adr/0006-fees-excel-upload-source.md), 화면: 입주민 관리비 / 관리자 관리비 관리)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `POST /admin/fees/uploads` | MANAGER·STAFF | 엑셀 업로드→파싱·Pydantic 검증→`excel_uploads`+오류 리포트 |
| `GET /admin/fees/uploads/{id}` | MANAGER·STAFF | 미리보기·행 단위 오류 확인(확정 전) |
| `POST /admin/fees/uploads/{id}/apply` | MANAGER | **확정 적용** — 해당 (tenant, period) 전체 교체, 단일 트랜잭션([11 §3.3](11-data-architecture.md)) |
| `GET /fees` | RESIDENT | **본인 세대 + 입주 승인 이후 월만**([06 §2](06-security-privacy.md) 결정 E) |
| `GET /admin/fees` | MANAGER·STAFF | 월별 부과 현황·세대별 조회 |
| `POST /fees/explain` | RESIDENT | AI 설명(SSE) — 확정 데이터(전월·평균 diff)를 컨텍스트로 **설명만**, 인용 `source_kind=fee_data`. H3 도구 레지스트리 도입 시 `get_fees` 도구로 통합(§5.2) |

**검수 큐** (H2-6, 화면: 관리자 AI 검수 큐)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `GET /admin/review-queue` | MANAGER | `messages.review_status=needs_review` 목록(질문·답변·인용·신뢰도) |
| `POST /admin/review-queue/{message_id}/decide` | MANAGER | `approve`/`reject`(+메모) → `reviewed_by/at` 기록. **사후 검수** — 이미 전달된 답변 회수 없음, 골든셋 후보로 축적([07 §5](07-testing-strategy.md)). 반려 시 정정 알림은 백로그 |

**시설** (H3-1·H3-4 · [ADR-0009](adr/0009-neo4j-in-mvp.md), 화면: 관리자 시설 관리·AI 도우미. 그래프 모델·동기화: [11 §3.5·§4](11-data-architecture.md))

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `GET /admin/facilities` | MANAGER | 설비 목록(상태·유형 필터) |
| `POST /admin/facilities` | MANAGER | 설비 등록 — **도메인 행 + `outbox_events` 원자 기록**([03 §4.9](03-database-design.md), 이중 쓰기 금지) |
| `GET /admin/facilities/{id}` | MANAGER | 상세 + 장애·정비 이력 |
| `PATCH /admin/facilities/{id}` | MANAGER | 상태(normal\|check\|fault\|risk)·정보 수정(+outbox) |
| `POST /admin/facilities/{id}/incidents` | MANAGER | 장애 기록(증상·조치) — outbox 경유로 Neo4j 임베딩 반영 |
| `POST /admin/facilities/{id}/maintenance` | MANAGER | 정비 기록(작업·교체 부품, +outbox) |
| `POST /admin/facilities/assistant` | MANAGER | AI 도우미(SSE 4이벤트) — 도구 에이전트 경로([ADR-0007](adr/0007-readonly-tool-agent.md)), 유사 장애→**원인 후보 제시(단정 금지**, FR-FAC-02). Neo4j 미가용 시 그래프 도구 제외 폴백 |

> Neo4j에 직접 쓰는 엔드포인트는 없다 — 모든 시설 쓰기는 PG 트랜잭션+outbox 한 경로, 그래프 반영은 ai-worker 단독([11 §3.5](11-data-architecture.md)).

**운영 대시보드** (H4 — FR-ADM-06 · [09 §8.5](09-implementation-harness.md), 화면: 관리자 대시보드)

| 엔드포인트 | 역할 | 설명 |
|-----------|------|------|
| `GET /admin/dashboard/stats` | MANAGER | 기간 파라미터(기본 7일) — 질의 수·평균 토큰(입/출)·폴백률·needs_review율·캐시 적중률·민원 상태 분포·시설 상태 분포 + 일일 토큰 예산 사용량·초과 여부(NFR-COST-01, 경고만·차단 없음). 집계는 SQL(파일럿 규모 — 별도 집계 테이블 없음) |

> AI 질의 경로(H4)에는 정확 캐시([08 §2.0·2.1](08-llm-token-optimization.md) 스코프 키)와 Redis 레이트 리밋(사용자·단지별, 초과 429)이 앞단에 붙는다 — SSE 계약·오케스트레이터는 불변.

**알림함** (횡단 · [ADR-0012](adr/0012-in-app-notification-only.md), 화면: 입주민 나>알림함)

| 엔드포인트 | 역할 | 비고 |
|-----------|------|------|
| `GET /notifications` | 본인 | RLS — 본인 알림만 |
| `POST /notifications/{id}/read` | 본인 | 읽음 처리(배지 해제) |

> 알림 **생성**은 전용 엔드포인트가 아니라 각 도메인 트랜잭션 내부에서 코드가 수행한다(공지 published·민원 상태 변경·가입 승인/거절) — 규칙 8(액션은 코드가 실행).

### 13.3 표면 불변식 (구현이 어겨서는 안 되는 것)

1. AI가 상태를 바꾸는 엔드포인트는 없다 — AI 산출물은 항상 `*_drafts`·제안 컬럼(`ai_suggested_*`)에 머물고, 상태 전이는 사람 액션 엔드포인트만 수행(규칙 6·8).
2. 관리비 쓰기는 엑셀 업로드 confirm 플로우가 유일하다. `/fees/explain`은 읽기+설명 전용(규칙 5).
3. 입주민 리소스는 소유권 필터가 쿼리에 박힌다(`author_user_id`·`household_id`·승인 시점) — 파라미터로 우회 불가.
4. SSE 계약(4이벤트)은 assistant·explain 등 모든 AI 스트리밍이 공유하며 변경 금지([09 §1.1](09-implementation-harness.md)).
