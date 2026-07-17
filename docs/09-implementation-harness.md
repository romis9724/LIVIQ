# 09. 구현 / 하네스 엔지니어링 가이드

> 디렉토리: [02-directory-structure.md](02-directory-structure.md) · 테스트: [07-testing-strategy.md](07-testing-strategy.md)
> 목표: **재현 가능하고 검증된 빌드**. 사람·에이전트 모두 같은 게이트를 통과한다.

## 1. 빌드 순서 (의존성 역순)

기반부터 위로 쌓는다. 각 단계는 테스트 그린 후 다음 진행.

```text
1) packages/config-ts, config-eslint               ← 웹 타입·규칙 (TS 툴링)
2) packages/db (스키마·RLS·마이그레이션·시드)         ← 데이터 토대 (SQLAlchemy 2.0 async · Alembic)
3) packages/ai-core (pii·retrieval·budget·citations) ← AI 토대 (Python · 단위테스트 우선)
4) apps/api (auth·tenants·documents·search)        ← 인가·RLS·검색 (FastAPI)
   └ OpenAPI → openapi-typescript → packages/api-types 생성물(웹이 소비, §1.1)
5) apps/ai-worker (ingest·embed·ocr)               ← 인제스트 파이프라인 (arq)
6) apps/api (assistant·inquiries·notices·fees …)   ← 도메인 기능
7) packages/ui (토큰·공용 컴포넌트)
8) apps/web-resident, web-admin                    ← 화면 (api-types 소비)
9) tests/e2e, tests/ai-eval                        ← 여정·품질 게이트
```

> 원칙(README rules): 새 구현 전 **재사용 검토**(라이브러리·패턴), KISS/YAGNI, 작은 파일.

### 1.1 API 계약 규약

- **계약 원천은 Pydantic**: 모든 경계 계약은 `apps/api`의 **Pydantic v2 모델**이 단일 원천이다. FastAPI가 노출하는 **OpenAPI 스키마 → openapi-typescript**로 `packages/api-types`(TS 타입 생성물)를 만들어 web이 import한다(패키지 배치 [02 §7](02-directory-structure.md)). 생성물은 커밋하고 **CI에서 드리프트 검사** — 재생성 후 diff가 0이 아니면 실패(§4.1).
- assistant 응답 **스트리밍은 SSE**(sse-starlette) — 이벤트 4종: `token`(증분 텍스트) · `citation`(근거 카드) · `status`(단계·도구 진행) · `done`(종료·최종 신뢰도). **이벤트 스키마는 불변**(스택 전환과 무관하게 계약 고정).
- 엔드포인트 목록·인가 역할·화면 매핑·표면 불변식은 **[01 §13 REST API 표면](01-architecture.md)이 소유**한다(H2-0에서 확정). 필드 상세는 문서에 중복하지 않고 Pydantic 모델이 원천.

## 2. 개발 환경

현재 실행 가능(웹 + Python 백엔드 — TS·Python 공통 게이트는 turbo가 오케스트레이션):

```bash
pnpm install
uv sync --all-packages    # 루트 uv workspace — 전 멤버 의존성 설치 (plain `uv sync`는 dev 도구만 설치, 멤버 미포함)
pnpm dev                  # turbo run dev — web-resident(3000)·web-admin(3001) 병렬
pnpm build
pnpm lint                 # eslint + ruff
pnpm typecheck            # tsc + mypy
pnpm test                 # vitest + pytest(cov 80 게이트)
pnpm start                # build 후
pnpm db:migrate           # Alembic upgrade head (DATABASE_URL 필요)
pnpm generate:api-types   # FastAPI OpenAPI → packages/api-types (CI 드리프트 게이트)
```

- 요구: Node 20+ · **Python 3.12+** · **uv**. 각 Python 패키지는 **얇은 package.json**으로 turbo 태스크(lint/typecheck/test)를 uv 실행(`ruff`·`mypy`·`pytest`)에 연결한다([ADR-0013](adr/0013-python-backend.md)).
- Python 패키지 디렉토리에서 plain `uv run` 금지(형제 멤버 deps를 prune) — `uv run --no-sync` 사용.

도입 후 추가 예정(해당 시점에 루트 스크립트로 승격):

```bash
pnpm db:seed   # 시드 데이터 정식화 시 (현재는 검증용 임시 스크립트만)
pnpm e2e       # tests/e2e 도입 시 (H2-7, §8.2)
```

- 로컬 인프라: [`infra/docker-compose.yml`](../infra/docker-compose.yml) — postgres(pgvector), redis, minio(s3), neo4j. 기동: `docker compose -f infra/docker-compose.yml up -d`.
- env는 `.env`(로컬), [`.env.example`](../.env.example)(레포 루트) 제공. 부팅 시 검증(누락=즉시 실패) — **Python 패키지는 Pydantic Settings, 웹은 Zod**. **검증 소유는 패키지별**(.env.example 주석) — `packages/db`가 `DATABASE_URL`, `apps/api`가 세션·S3·인증, `packages/ai-core`가 LLM·임베딩.
- **생성 LLM과 임베딩은 env를 분리**한다(`LLM_*` vs `EMBEDDING_*`) — 임베딩 bge-m3는 고정, 생성 모델만 교체 가능([ADR-0005](adr/0005-single-llm-openai-compat.md) 보강).
- 시크릿은 로컬도 평문 커밋 금지.

### 2.1 버전 핀 (초기값)

| 대상 | 핀 | 비고 |
|------|----|------|
| Node | 20+ | 웹·툴링(TS) |
| Python | 3.12+ | 백엔드(api·ai-worker·ai-core·db) |
| uv | 최신 stable | Python 패키징·워크스페이스 |
| FastAPI | 최신 stable | api 프레임워크 (+Pydantic v2 · sse-starlette) |
| SQLAlchemy | 2.0 (async) | ORM (packages/db) |
| Alembic | 최신 stable | 스키마·마이그레이션 |
| arq | 최신 stable | 큐·워커 (ai-worker, cron 내장) |
| PostgreSQL | 16 (pgvector) | compose 이미지와 일치 |

- **RLS 정책 SQL은 Alembic custom migration(`op.execute`)으로 버전 관리**한다 — 스키마 자동생성(autogenerate)이 만들지 못하는 정책·role을 마이그레이션 파일로 고정(코드 리뷰가 아니라 마이그레이션 이력으로 추적).

## 3. 코드 게이트 (로컬·CI 공통, 순서 고정)

`format → lint → typecheck → test → build` (사용자 web hooks 순서 준수).

| 단계 | 명령(예) | 차단 |
|------|----------|------|
| format | `pnpm prettier --check` | – |
| lint | `pnpm eslint` | ✅ |
| typecheck | `pnpm tsc --noEmit` | ✅ |
| unit/integration | `pnpm test --coverage` (≥80%) | ✅ |
| 보안(인가/RLS/마스킹) | 전용 스위트 | ✅ (CRITICAL) |
| e2e | `pnpm e2e` (핵심 여정) | ✅ |
| a11y | axe | ✅(심각) |
| ai-eval | 회귀 비교 | ⚠️→리뷰 |
| build | `pnpm build` | ✅ |

### 3.1 작업 사이클 — 브랜치·커밋·PR·설계 선행 (H2부터 적용)

> H0·H1은 main 직접 커밋으로 진행했다. **H2부터 아래 사이클을 따른다.**

```text
작업 단위(Hx-y) 시작
  → ① 설계 갱신 커밋 (docs·ADR — 구현 전 필수)
  → ② 구현 커밋들 (TDD, 게이트 그린 단위)
  → ③ 현행화 커밋 (CLAUDE.md·ARCHITECTURE.md·§8 상태)
  → ④ PR → CI 그린 → 사용자 확인 → 머지
```

| 항목 | 규칙 |
|------|------|
| 브랜치 | 작업 단위(Hx-y)마다 `feat/h2-1-슬러그`. main 직접 커밋 금지(오탈자 등 사소한 docs 수정만 예외) |
| 커밋 주기 | **게이트(format→lint→typecheck→test) 그린을 통과한 최소 논리 단위**마다 1커밋. 하나의 커밋에 서로 다른 관심사 섞지 않음 |
| PR 주기 | **작업 단위(Hx-y) 1개 = PR 1개.** 본문: 목적 · 변경 요약 · 테스트 계획 · 갱신한 설계 문서 링크 |
| 머지 조건 | CI 전 게이트 그린 + **사용자 확인** 후 머지 |
| 머지 방식 | **merge commit**(`gh pr merge --merge`) — 단계별 커밋 이력 보존. squash 금지(H2-0에서 H0·H1 이력이 단일 커밋으로 뭉개진 사고 재발 방지, 원본은 `archive/h0-h1-granular-history`) |
| push | 커밋 즉시 원격 push(로컬에만 쌓아두지 않음 — 미푸시 이력은 PR 머지 시 유실 위험) |
| 설계 선행 | 구현 착수 전 관련 설계 문서(docs 00~11 해당 절·ADR)를 먼저 갱신해 브랜치 **첫 커밋**으로 올린다. 설계에 없는 구현 금지 — 설계와 코드가 다르면 그 시점에 문서부터 고친다 |
| 현행화 | 작업 단위 완료 시 현황 문서(CLAUDE.md 구조 절 · ARCHITECTURE.md 그래프 · 본 문서 §8 상태)를 같은 PR 마지막 커밋으로 갱신 |

## 4. CI/CD (`.github/workflows`)

```text
PR:  install(turbo cache) → lint → typecheck → unit/integration(testcontainers-python)
     → 보안 스위트 → build → e2e(미리보기) → a11y → ai-eval(diff)
     → 시크릿 스캔 + 의존성 취약점 스캔
merge(main): 마이그레이션 dry-run → 스테이징 배포 → 스모크 → (승인) 운영
```
- Turbo 원격 캐시로 변경 영향 패키지만 빌드/테스트(시간·비용 절감).
- 머지 차단 조건은 [07 §9](07-testing-strategy.md).

### 4.1 `ci.yml` 스펙 (초기값)

| 항목 | 값 |
|------|----|
| 트리거 | PR(→main), push(main) |
| 단계 순서 | format → lint → typecheck → test(coverage) → build (§3과 동일) |
| **TS 게이트**(웹·ui·config-ts·api-types 한정) | `prettier --check` · `eslint` · `tsc --noEmit` · `vitest --coverage` |
| **Python 게이트**(api·ai-worker·ai-core·db) | `ruff check` · `ruff format --check` · `mypy` · `pytest`(pytest-cov) |
| 커버리지 | 패키지별 threshold **80%**(라인/브랜치) — TS=vitest thresholds, Python=pytest-cov `--cov-fail-under=80`, 미달 = 실패 |
| 계약 드리프트 | OpenAPI 재생성 후 `packages/api-types` diff 0 아니면 실패(§1.1) |
| 범위 | turbo `--filter=...[origin/main]` — 변경 영향 패키지만(TS·Python 공통) |
| 시크릿 스캔 | **gitleaks** (PR diff + 전체 히스토리) |
| 경로 검증 | `node scripts/check-context-paths.mjs` (stale 링크 차단) |

### 4.2 테스트 하네스

- 통합 테스트는 **testcontainers-python으로 PostgreSQL 기동**(pytest fixture) — 실제 Alembic 마이그레이션·RLS를 적용해 검증(모킹 아님).
- **역할 2개**: 마이그레이션 owner role(DDL·정책 생성) + 런타임 role(**BYPASSRLS 없음** — RLS를 실제로 받는다). 워커도 런타임 role.
- 격리는 **트랜잭션 롤백**(각 테스트를 트랜잭션으로 감싸 종료 시 롤백 — 컨테이너 재기동 없이 빠르게). pytest fixture가 트랜잭션 경계를 관리.

## 5. 권장 훅 (PostToolUse / Pre / Stop)

> 사용자 web hooks 규칙 기반. **레포 소유 도구만** 사용(원격 1회성 실행 금지).

- PostToolUse(Write|Edit): prettier → eslint --fix → tsc(빠른 영역)
- PreToolUse(Write): 800줄 초과 차단(파일 분할 유도)
- Stop: `pnpm build` 또는 영향 범위 빌드 검증

## 6. AI 품질 운영 루프 (배포 후)

```text
응답 로그·👎 수집 → 골든셋 후보 검토 → 골든셋 갱신 → 회귀 평가
                                          → 프롬프트/청킹/라우팅 조정 → 재평가
```
- 모델/프롬프트/임베딩 변경은 **회귀 평가 통과** 후 반영([07 §5], [08 §9]).
- 환각률·비용·폴백율 임계 초과 시 알림 → 원인 분석.

## 7. 데이터/마이그레이션 운영

- 마이그레이션은 CI 자동, 파괴적 변경은 2단계 무중단([03 §8](03-database-design.md)).
- 임베딩 차원/모델 변경 = 전량 재색인 이벤트(비용·시간 계획 필요).

### 7.1 백업·복구 (운영 절차 — 09 소유)

정책·위협 대응은 [06 §4](06-security-privacy.md)가 소유하고, **실행 절차는 여기(09)가 소유**한다.

| 자산 | 방식 | 주기/보존 | 복구 목표 |
|------|------|-----------|-----------|
| PostgreSQL | 논리 덤프 + WAL 아카이브(**PITR**) | 일 1 풀 + 연속 WAL | 최근 시점 복원 |
| S3 오브젝트 | **버저닝** + 수명주기 | 버전 유지·만료 규칙 | 개별 객체 롤백 |
| `PII_MASTER_KEY` | 시크릿 매니저 + **오프라인 백업** | 회전 시 갱신 | 유실=pii_vault 복호 불능([ADR-0010](adr/0010-envelope-encryption-env-master-key.md)) |
| Neo4j | 파생 그래프 → PG에서 재동기화 | 스냅샷(선택) | PG가 SoR, 기준으로 재구축([11](11-data-architecture.md)) |

- **복구 리허설 분기 1회**: 백업에서 실복원 → 스모크 → 결과 기록. 개인정보 포함 백업은 암호화·접근통제.

## 8. 단계별 구현 플랜 ([10 §10 로드맵](10-project-plan.md)과 정합)

> 단계는 **H 접두어**로 표기해 [10 §10](10-project-plan.md) 사업 로드맵의 "단계 0=준비"(데이터 실사·법무·골든셋)와 구분한다. H는 구현 하네스 단계다.

| 단계 | 내용 | 종료 기준 | 상태 |
|------|------|-----------|------|
| H0. 토대 | 모노레포·DB·RLS·ai-core 골격·CI 게이트 | 빈 앱 그린 빌드, RLS 테스트 통과(§8.1) | ✅ 완료 (2026-07-13) |
| H1. RAG MVP | 문서 인제스트→검색→인용 응답, 비서 화면 | 골든셋 적중률 게이트, 환각 폴백 동작 | ✅ 완료 (2026-07-14) — rule-1 실측 2/2, 비서 화면 실연동 |
| H2. 입주민/관리자 | 인증·민원·공지초안·관리비 설명·검수 큐 | E2E 여정 그린, 검수 게이트 | 계획(§8.2) |
| H3. 시설 | 시설 도우미(Neo4j 그래프·원인 후보) | 회귀 평가·검수 통과 | 대기 |
| H4. 운영/최적화 | 대시보드·캐시·라우팅·비용 상한 | 비용/품질 대시보드, 알림 | 대기 |

### 8.1 H0 체크리스트 (토대) — ✅ 완료

작업 순서 — 각 단계 그린 후 다음으로:

| 순서 | 작업 | 산출물 | 완료 기준 |
|------|------|--------|-----------|
| 1 | compose 기동 | 4개 컨테이너 healthy | `docker compose -f infra/docker-compose.yml ps` 전부 healthy |
| 2 | uv workspace 초기화 | 루트 uv workspace · Python 패키지 골격(api·ai-worker·ai-core·db) · 얇은 package.json(turbo 연결) | `uv sync --all-packages` 성공, turbo가 Python 태스크 인식 |
| 3 | packages/db 골격 + Alembic 초기 마이그레이션(`CREATE EXTENSION vector` 포함) | SQLAlchemy 스키마 · Alembic 첫 마이그레이션 | 마이그레이션 적용, vector 확장 활성 |
| 4 | env 검증 (packages/db·apps/api 각자 소유, **Pydantic Settings**) | config 모듈 | 누락 env = 부팅 실패 |
| 5 | RLS 정책 + 워커 role | `rls/` SQL(Alembic custom migration), 런타임 role | 교차 tenant 접근 거부 테스트 통과(CRITICAL) |
| 6 | testcontainers-python 픽스처 | PG 기동·마이그레이션·트랜잭션 롤백(§4.2) | 통합 테스트 그린 |
| 7 | `ci.yml` | 게이트 워크플로(§4.1) | PR에서 전 단계 실행 |
| 8 | 빈 apps/api 그린 빌드 | 부팅되는 FastAPI 앱 | 헬스체크 200, 그린 빌드 |

- **H0 완료 시 갱신**: [CLAUDE.md](../CLAUDE.md) '구조' 절(계획→구현으로 이동), [ARCHITECTURE.md](../ARCHITECTURE.md) 목표 그래프를 현재 그래프로 승격.

### 8.2 H2 체크리스트 (입주민/관리자 기능)

> 각 작업 단위는 §3.1 사이클(설계 갱신 → 구현 → 현행화 → PR)을 따른다.
> H1이 미룬 **정식 인증**이 선행 조건 — dev 헤더(`X-Dev-*`)는 역할 구분이 없어 H2 기능(입주민/관리자 분리)을 못 태운다.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H2-0 | 설계 갱신 | REST API 표면([01 §13](01-architecture.md)) 신설 · `inquiry_events`·검수 필드([03 §4.3·4.4](03-database-design.md)) · 신규 ADR 불필요(기존 0006·0011·0012 커버) | 설계 문서 PR 머지(구현 착수 전) | ✅ 완료 (PR #1) |
| H2-1 | 인증·세션·역할 | Redis 서버 세션([ADR-0011](adr/0011-redis-server-session.md))·Google OAuth PKCE·역할 인가 가드·PII 봉투 암호화([ADR-0010](adr/0010-envelope-encryption-env-master-key.md))·온보딩·가입 승인·명부 업로드. dev 헤더는 local 전용 격리 | 로그인→세션→역할별 엔드포인트 인가 테스트(CRITICAL), 교차 역할 접근 거부 | ✅ 완료 (PR #2) |
| H2-2 | 문서 관리 화면 실연동 | web-admin documents 화면 → 업로드·목록(상태 필터)·공개범위 수정·재색인 api 연동([01 §13](01-architecture.md) 문서 표). api에 PATCH·reindex·필터 추가 | 업로드→indexing→indexed 상태가 화면에 반영 | ✅ 완료 (PR #3) |
| H2-3 | 민원(inquiries) | 접수·목록·상태 타임라인 api([01 §13](01-architecture.md) 민원 표, `inquiry_events` 마이그레이션) + **web-resident 접수·목록·상세 + web-admin 접수함·배정·상태 실연동**(상태 변경 주체가 관리자라 완료 기준상 양쪽 필요). AI 분류는 키워드 기반 **제안값**(규칙 6) + 상태 변경 시 작성자 알림 | 접수→배정→상태 변경→타임라인·알림 반영 | ✅ 완료 (PR #4) |
| H2-4 | 공지 초안 | 키워드→AI 초안 생성 api(**동기 POST** — 1회 생성이라 SSE 불필요, 출처 인용 강제·근거 0이면 생성 거절) + notices 조회·발송(published 시 대상자 알림) + web-admin 스테퍼·web-resident 공지 목록/상세 실연동. **발송은 사람 확정**(자동발송 금지, notice_drafts→notices 승격) | 초안에 출처 동반, 발송 버튼은 사람 확인 후에만 활성 | ✅ 완료 (PR #5) |
| H2-5 | 관리비 | 엑셀 업로드→검증→확정 데이터 적재([ADR-0006](adr/0006-fees-excel-upload-source.md), [11 §3.3](11-data-architecture.md)) + 조회 api(본인 세대·승인 후 월만 — FR-FEE-03) + AI 설명 `/fees/explain`(**설명만, 계산 금지 — 규칙 5**) + 양쪽 화면 실연동. **엑셀 컬럼 계약(H2-5 확정): 헤더 `동,층,호` + 이후 열 전부 항목명(breakdown 키), 합계는 서버 계산, period는 업로드 파라미터(YYYY-MM).** **fee 인용의 SSE 표현: `citation` 이벤트 `document_id`를 nullable로 확장**(이벤트 4종 구조 불변 — 필드 완화만, [09 §1.1] 하위호환) — title="관리비 YYYY-MM 확정 데이터" | 업로드→검증·미리보기→확정→조회 정합, AI 응답에 확정 데이터 출처 | ✅ 완료 (PR #6) |
| H2-6 | 검수 큐 | `needs_review` 메시지 큐 api([01 §13](01-architecture.md) 검수 큐 표) + messages 검수 필드 마이그레이션(reviewed_by·reviewed_at·review_note — [03 §4.3](03-database-design.md), H2-0 설계분) + web-admin review-queue 실연동(승인/반려·메모). **사후 검수** — 전달된 답변 회수 없음(정정 알림은 백로그), 골든셋 후보 축적 | 저신뢰 답변이 큐에 적재→승인/반려 처리 흐름 테스트 | ✅ 완료 (PR #7) |
| H2-7 | evals·E2E 확장 | tests/e2e 도입(핵심 여정) + evals 어댑터에 규칙 5(관리비)·6(검수) 관측 키 추가 | E2E 그린, 신규 규칙 측정 pass | 대기 |

### 8.3 백로그 (의도적 보류 — 단계 미배정)

| 항목 | 근거 문서 | 보류 이유 / 착수 시점 |
|------|-----------|----------------------|
| Redis 정확 캐시(질의 정규화→캐시 히트) | [08 §2](08-llm-token-optimization.md) | 오케스트레이터 앞단 얇은 래퍼로 후속. 트래픽 생기는 파일럿 전(H4 캐시 항목과 통합) |
| 도구 레지스트리·에이전트 스텝 상한 | [ADR-0007](adr/0007-readonly-tool-agent.md) | H1은 `search_documents` 고정 1스텝. 다중 도구가 필요한 H3(시설)에서 |
| evals 규칙 2(마스킹)·3(격리) 등 관측 키 | [evals/README](../evals/README.md) | 해당 관측 지점(마스킹 로그·캐시 스코프)이 생기는 단계에서 추가 |
| HWP·OCR 문서 파싱 | [11 §3](11-data-architecture.md) | 파싱 인터페이스 뒤에 자리만 확보됨. 파일럿 단지 실데이터 확인 후 |
| 웹 api-types 소비 전환 | [02 §7](02-directory-structure.md) | web-resident SSE 타입은 로컬 정의 — 계약 확장 시 `@liviq/api-types` import로 전환 |
| 관리자 문서 자연어 검색 | [04 §3](04-menu-structure.md) 화면 IA | [01 §13](01-architecture.md) API 표면에 미포함(H2-2 결정) — MVP는 목록·상태 관리까지, 자연어 검색은 비서 재사용 또는 전용 엔드포인트를 수요 확인 후 |
| 공지 예약 발송 실행기 | [03 §4.4](03-database-design.md) `scheduled_at` | H2-4는 즉시 발행만 — 예약분은 draft 저장. arq cron 실행기는 수요 확인 후 |
| 공지 초안 인용 영속 | [03 §4.3](03-database-design.md) citations | citations는 message 전용 스키마 — 초안 인용은 생성 응답으로만 반환(검수 직후 사용). 재열람 검수가 필요해지면 source_kind 확장 |

## 9. 정의: "완료(Done)"

기능은 다음을 **모두** 만족할 때 완료:
- [ ] 요구사항 ID 충족([00]) + 테스트(단위/통합/E2E) 그린
- [ ] 인가·테넌트 격리·개인정보 마스킹 검증
- [ ] 접근성·반응형(4 브레이크포인트) 확인
- [ ] 위험 출력 검수 게이트 동작(해당 시)
- [ ] 토큰/비용 기록·캐시 적용(해당 시)
- [ ] 문서/ADR 갱신, 코드리뷰 통과

## 10. ADR 로그

정본은 [docs/adr/](adr/README.md)다. 결정 변경 시 새 ADR을 추가하고 이전 결정은 `Superseded` 처리한다. 요약 표는 [01 §12](01-architecture.md) 참조.
