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

```bash
pnpm e2e       # Playwright 여정 (tests/e2e, H2-7) — infra 기동 필요, CI는 @llm 자동 제외
```

도입 후 추가 예정(해당 시점에 루트 스크립트로 승격):

```bash
pnpm db:seed   # 시드 데이터 정식화 시 (현재는 tests/e2e 시드·검증용 임시 스크립트만)
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
| H2. 입주민/관리자 | 인증·민원·공지초안·관리비 설명·검수 큐 | E2E 여정 그린, 검수 게이트 | ✅ 완료 (2026-07-17, §8.2) |
| H3. 시설 | 시설 도우미(Neo4j 그래프·원인 후보) | 회귀 평가·검수 통과 | ✅ 완료 (2026-07-17, §8.4) — rule-8 실측 3/3 |
| H4. 운영/최적화 | 대시보드·캐시·라우팅·비용 상한 | 비용/품질 대시보드, 알림 | ✅ 완료 (2026-07-17, §8.5) — 모델 라우팅·의미 캐시는 보류([01 ADR-2]·[08 §10]), 실비용 상한은 파일럿 측정 후 |
| H5. 파일럿 준비 | 모델 확정·evals 규칙 2·3·알림함/정정 알림 | 실측 6/8규칙·확정 모델 E2E 그린·검수 루프 폐합 | ✅ 완료 (2026-07-18, §8.6) — llama3.1:8b 확정·실측 6/8규칙·알림 루프 폐합 |
| H6. 전 기능 실동작 | 실로그인(세션)·목업 해소·가입→AI 전 구간 E2E | 목업 렌더 0·회원가입~AI 통합테스트 그린 | ✅ 완료 (2026-07-18, §8.7) — 세션 인증·목업 0·가입~AI 여정 E2E 그린 |

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
| H2-1 | 인증·세션·역할 | Redis 서버 세션([ADR-0011](adr/0011-redis-server-session.md))·Google OAuth PKCE(**H7-1에서 자체 이메일 인증으로 대체 — §8.8, [ADR-0014]**)·역할 인가 가드·PII 봉투 암호화([ADR-0010](adr/0010-envelope-encryption-env-master-key.md))·온보딩·가입 승인·명부 업로드. dev 헤더는 local 전용 격리 | 로그인→세션→역할별 엔드포인트 인가 테스트(CRITICAL), 교차 역할 접근 거부 | ✅ 완료 (PR #2) |
| H2-2 | 문서 관리 화면 실연동 | web-admin documents 화면 → 업로드·목록(상태 필터)·공개범위 수정·재색인 api 연동([01 §13](01-architecture.md) 문서 표). api에 PATCH·reindex·필터 추가 | 업로드→indexing→indexed 상태가 화면에 반영 | ✅ 완료 (PR #3) |
| H2-3 | 민원(inquiries) | 접수·목록·상태 타임라인 api([01 §13](01-architecture.md) 민원 표, `inquiry_events` 마이그레이션) + **web-resident 접수·목록·상세 + web-admin 접수함·배정·상태 실연동**(상태 변경 주체가 관리자라 완료 기준상 양쪽 필요). AI 분류는 키워드 기반 **제안값**(규칙 6) + 상태 변경 시 작성자 알림 | 접수→배정→상태 변경→타임라인·알림 반영 | ✅ 완료 (PR #4) |
| H2-4 | 공지 초안 | 키워드→AI 초안 생성 api(**동기 POST** — 1회 생성이라 SSE 불필요, 출처 인용 강제·근거 0이면 생성 거절) + notices 조회·발송(published 시 대상자 알림) + web-admin 스테퍼·web-resident 공지 목록/상세 실연동. **발송은 사람 확정**(자동발송 금지, notice_drafts→notices 승격) | 초안에 출처 동반, 발송 버튼은 사람 확인 후에만 활성 | ✅ 완료 (PR #5) |
| H2-5 | 관리비 | 엑셀 업로드→검증→확정 데이터 적재([ADR-0006](adr/0006-fees-excel-upload-source.md), [11 §3.3](11-data-architecture.md)) + 조회 api(본인 세대·승인 후 월만 — FR-FEE-03) + AI 설명 `/fees/explain`(**설명만, 계산 금지 — 규칙 5**) + 양쪽 화면 실연동. **엑셀 컬럼 계약(H2-5 확정): 헤더 `동,층,호` + 이후 열 전부 항목명(breakdown 키), 합계는 서버 계산, period는 업로드 파라미터(YYYY-MM).** **fee 인용의 SSE 표현: `citation` 이벤트 `document_id`를 nullable로 확장**(이벤트 4종 구조 불변 — 필드 완화만, [09 §1.1] 하위호환) — title="관리비 YYYY-MM 확정 데이터" | 업로드→검증·미리보기→확정→조회 정합, AI 응답에 확정 데이터 출처 | ✅ 완료 (PR #6) |
| H2-6 | 검수 큐 | `needs_review` 메시지 큐 api([01 §13](01-architecture.md) 검수 큐 표) + messages 검수 필드 마이그레이션(reviewed_by·reviewed_at·review_note — [03 §4.3](03-database-design.md), H2-0 설계분) + web-admin review-queue 실연동(승인/반려·메모). **사후 검수** — 전달된 답변 회수 없음(정정 알림은 백로그), 골든셋 후보 축적 | 저신뢰 답변이 큐에 적재→승인/반려 처리 흐름 테스트 | ✅ 완료 (PR #7) |
| H2-7 | evals·E2E 확장 | **tests/e2e 도입(Playwright, `@liviq/e2e` 워크스페이스)** — 결정론 여정 4종(입주민 민원 접수→타임라인 · 공지 목록→상세 · 관리비 조회(확정 월) · 관리자 검수 큐 승인/반려)을 CI 게이트로, 비서 여정(질의·폴백)은 임베딩 LLM 필요라 **`@llm` 태그 로컬 전용**([07 §4](07-testing-strategy.md)). 인증은 `API_ENV=local` dev 헤더(웹이 자동 부착), 시드 스크립트로 민원·공지·확정 관리비·needs_review 메시지 적재. `pnpm e2e` 루트 스크립트 승격 + ci.yml e2e 잡(pg·redis 서비스 컨테이너). **evals 어댑터 규칙 5·6 관측 키**: 규칙 5 `no_recalculation`=계산 요구가 폴백 또는 인용 동반(SSE), `explains_erp_value_only`=`/fees/explain` 인용이 확정 데이터 출처. 규칙 6 `draft_only`·`no_auto_send`=`/notices/draft` 호출 전후 notices 목록 불변+미발행 초안 반환, `routed_to_review_queue`=done의 confidence↔needs_review 라우팅 일관성(저신뢰 강제 불가 — LLM 비결정성, 실측 시에만 판정력) | E2E 결정론 여정 CI 그린, 규칙 5·6 케이스가 pending→측정 전환 | ✅ 완료 (PR #8) |

### 8.3 백로그 (의도적 보류 — 단계 미배정)

| 항목 | 근거 문서 | 보류 이유 / 착수 시점 |
|------|-----------|----------------------|
| ~~Redis 정확 캐시(질의 정규화→캐시 히트)~~ | [08 §2](08-llm-token-optimization.md) | **H4-2로 승격**(2026-07-17, §8.5) |
| ~~도구 레지스트리·에이전트 스텝 상한~~ | [ADR-0007](adr/0007-readonly-tool-agent.md) | **H3-3로 승격**(2026-07-17, §8.4) |
| evals 규칙 2(마스킹)·3(격리) 등 관측 키 | [evals/README](../evals/README.md) | 해당 관측 지점(마스킹 로그·캐시 스코프)이 생기는 단계에서 추가 |
| HWP·OCR 문서 파싱 | [11 §3](11-data-architecture.md) | 파싱 인터페이스 뒤에 자리만 확보됨. 파일럿 단지 실데이터 확인 후 |
| 웹 api-types 소비 전환 | [02 §7](02-directory-structure.md) | web-resident SSE 타입은 로컬 정의 — 계약 확장 시 `@liviq/api-types` import로 전환 |
| 관리자 문서 자연어 검색 | [04 §3](04-menu-structure.md) 화면 IA | [01 §13](01-architecture.md) API 표면에 미포함(H2-2 결정) — MVP는 목록·상태 관리까지, 자연어 검색은 비서 재사용 또는 전용 엔드포인트를 수요 확인 후 |
| 공지 예약 발송 실행기 | [03 §4.4](03-database-design.md) `scheduled_at` | H2-4는 즉시 발행만 — 예약분은 draft 저장. arq cron 실행기는 수요 확인 후 |
| 공지 초안 인용 영속 | [03 §4.3](03-database-design.md) citations | citations는 message 전용 스키마 — 초안 인용은 생성 응답으로만 반환(검수 직후 사용). 재열람 검수가 필요해지면 source_kind 확장 |
| 그래프 tombstone·전체 리플레이 실행기 | [03 §4.9](03-database-design.md)·[11 §3.5](11-data-architecture.md) | H3-2는 created·updated만 — 시설 delete 엔드포인트(producer)가 없어 deleted 이벤트 미발생. soft delete API 도입 시 tombstone 반영·리플레이 ops 스크립트 추가 |
| ~~get_dek 최초 생성 경합(uq 위반)~~ | [ADR-0010](adr/0010-envelope-encryption-env-master-key.md) | **해소(PR #28, 2026-07-18)** — ON CONFLICT DO NOTHING+재조회 원자화, 결정론 경합 pytest(RED 재현 후 GREEN) |
| 동의 변경·설정 토글 서버 연동 | [04 §2](04-menu-structure.md) 나 화면 | H6-3은 표시 전용 — 동의 변경 API 부재. 수요 확인 후 |
| ~~OAuth 콜백 앱별 복귀~~ | H6-1 | **H7-1에서 대체**(§8.8) — 자체 이메일 인증 전환으로 OAuth 콜백 자체 제거 |

### 8.4 H3 체크리스트 (시설 — Neo4j 그래프·AI 도우미)

> 각 작업 단위는 §3.1 사이클을 따른다. **H2와 달리 머지는 단위별 사용자 확인 후 진행**(자동 머지 위임 없음).
> 근거 설계: [ADR-0009](adr/0009-neo4j-in-mvp.md)(Neo4j MVP 포함) · [ADR-0007](adr/0007-readonly-tool-agent.md)(읽기 전용 도구 에이전트) · 그래프 모델·동기화 [11 §3.5·§4](11-data-architecture.md) · outbox [03 §4.9](03-database-design.md).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H3-0 | 설계 갱신 | [01 §13](01-architecture.md) 시설 API 표면 신설 · §8.4 체크리스트 · 로드맵 상태 정정. 신규 ADR 불필요(0007·0009가 결정 커버) | 설계 문서 PR 머지(구현 착수 전) | ✅ 완료 (PR #9) |
| H3-1 | 시설 CRUD·이력 + outbox | facilities·incidents·maintenance_logs api([01 §13](01-architecture.md) 시설 표) — **쓰기 트랜잭션에 `outbox_events` 원자 기록**(이중 쓰기 금지, [03 §4.9](03-database-design.md)·[11 §3.5](11-data-architecture.md)) + web-admin facilities 화면 실연동(목업 존재). 역할: 쓰기 MANAGER·FACILITY, 읽기 +STAFF | 등록→장애/정비 기록→이력 조회 정합 + 도메인 행·outbox 행 원자 생성 테스트 | ✅ 완료 (PR #10) |
| H3-2 | graph-sync | ai-worker outbox 폴링(`sequence` 순서·`dedupe_key` 중복 차단·`FOR UPDATE SKIP LOCKED` claim·`last_applied_version` 역전 방지·tombstone·재시도 초과 DLQ) → Neo4j MERGE는 **typed query 레이어만**(raw Cypher 금지 — 구조적 tenant 필터, 관계 생성 시 양끝 `tenant_id` 일치 검증) + Incident 임베딩(bge-m3 1024 cosine, `incident_embedding` 벡터 인덱스) + 전체 리플레이 재구성 경로. 워커 role은 outbox/jobs만 cross-tenant, 도메인 반영은 이벤트 tenant로 `SET LOCAL`([03 §5](03-database-design.md)). **H3-2 그래프 범위(현존 데이터만)**: 노드 Facility·Incident·MaintenanceLog(+parts 있으면 Part), 관계 HAS_INCIDENT·HAS_MAINTENANCE(+REPLACED 조건부) — SAME_MODEL·LOCATED_IN·PlanPoint는 재료(모델 컬럼·배치도 연동)가 생기는 단계로 보류([11 §4](11-data-architecture.md) 전체 모델의 부분 투영). 트리거는 arq cron 폴링(15초). **Incident 임베딩 전 `ensure_masked` 적용**(규칙 2 — 장애 텍스트에 입주민 언급 가능, 마스킹 실패 시 임베딩 생략하고 노드만 반영) | **교차 tenant 그래프 침투·관계 tenant 불일치 거부 테스트(CRITICAL — 머지 차단, [07 §3](07-testing-strategy.md))** + 동기화 멱등(재처리 안전) | ✅ 완료 (PR #11) — tombstone·리플레이 실행기는 delete producer 생기는 단계로 보류(§8.3) |
| H3-3 | 도구 레지스트리·에이전트 | [ADR-0007](adr/0007-readonly-tool-agent.md) — ai-core 오케스트레이터를 읽기 전용 도구호출 에이전트로 개편: 레지스트리 6종([01 §5.2](01-architecture.md) 표 — `search_documents`·`search_facility_graph`·`get_fees`·`get_my_inquiries`·`get_facilities`·`get_overdue_checks`), **스텝 상한 2~3회**(초과 시 현재 근거로 답변/폴백), 파라미터·tenant·소유권·읽기전용 강제는 코드, 도구 결과도 출처 카드, 도구 경로 로깅(골든셋 회귀용). Neo4j 미가용 시 그래프 도구 제외(PG 폴백 — [11 §4](11-data-architecture.md)). 역할별 도구 가시성(시설 도구는 시설 역할). **`/assistant/ask` SSE 계약 불변**. **세부 결정(H3-3 확정)**: ① LLM 도구 결정 turn은 **비스트리밍 chat(tools)**, 최종 답변 turn만 스트리밍 — OpenAI function calling(qwen2.5 지원) ② 도구 인자는 Pydantic 검증, tenant·user는 LLM 인자에서 절대 받지 않고 코드 컨텍스트가 주입 ③ 도구 결과 인용은 `source_kind` 확장(`tool:<이름>`, citation SSE는 document_id null·title로 표기 — H2-5 완화 재사용) ④ status stage는 기존 3종 재사용(searching=도구 실행, 리터럴 확장 없음 — 웹 하위호환) ⑤ 도구 경로 로깅은 구조화 로그(`tool_path`) — 영속·evals 관측은 H3-4에서 ⑥ 의도분류·캐시 앞단은 백로그 유지 ⑦ `search_facility_graph`는 임베딩→`search_incidents`+이웃 확장(시설·최근 정비) — typed 레이어에 확장 메서드 추가 | 복합 질의가 도구 2종 조합으로 응답 + 스텝 상한 강제 + 도구 경로에 쓰기 부수효과 없음(규칙 8) 테스트 | ✅ 완료 (PR #12) — 로컬 Ollama 0.24.0의 qwen2.5:14b는 tool_calls를 content에 인라인으로 뱉어 도구 미작동(llama3.1:8b는 정상) → 운영 전 tool calling 정상 모델 확정 필요 |
| H3-4 | 시설 AI 도우미 + 평가 | `POST /admin/facilities/assistant`(SSE 4이벤트, 시설 역할) — 유사 장애 검색→**가능 원인 후보 제시(단정 금지**, FR-FAC-02) + web-admin AI 도우미 화면 실연동 + evals 규칙 8 관측 키(읽기 전용·스텝 상한) + E2E 시설 여정(CRUD 결정론은 CI 게이트, 도우미는 `@llm`+Neo4j 로컬 전용). **세부 결정(H3-4 확정)**: ① 별도 오케스트레이터 없이 `answer_question` 재사용 — 시설 전용 시스템 프롬프트(원인 **후보** 형식 강제·단정 금지, "~일 수 있습니다")만 교체 주입, 레지스트리·마스킹·스텝 상한·폴백 전부 공유 ② **done 이벤트에 `tool_path`(호출 도구 이름 순서 배열) 추가** — additive 확장(4이벤트 타입 불변, H2-6 needs_review 전례), api-types 재생성. H3-3 보류분(도구 경로 관측) 해소 ③ evals 규칙 8 관측: readonly-01=`tool_path`가 읽기 도구 6종 ⊆ + inquiries 목록 전후 불변(규칙 6 패턴 재사용), readonly-02=`tool_path` 길이 ≤ 스텝 상한, readonly-03=도구 인용 동반 — 텍스트 휴리스틱(guides_to_ui)은 목록 불변+정상 응답으로 관측 ④ web-admin은 FacilityManager에 AI 도우미 패널(web-resident SSE 클라이언트 패턴 재사용, 원인 후보에 출처 카드 필수) ⑤ E2E 시설 CRUD 결정론 여정은 CI 게이트, 도우미 여정은 `@llm`(+Neo4j) 로컬 전용 ⑥ 신뢰도·검수 큐 라우팅은 기존 needs_review 로직 그대로(시설 전용 임계 없음) | 원인 후보에 이력 출처 동반, 규칙 8 케이스 pending→측정 전환, E2E 그린 | ✅ 완료 (PR #13) — 실측 rule-8 3/3·E2E CRUD(CI)+도우미(@llm) 그린 |

### 8.5 H4 체크리스트 (운영/최적화 — 가드레일·캐시·대시보드·비용 상한)

> 근거: [08](08-llm-token-optimization.md)(토큰=1급 제약) · FR-ADM-06(운영 대시보드) · NFR-COST-01(질의당 비용 — 파일럿 측정 후 상한) · NFR-OBS-01.
> **범위 제외(보류 유지)**: 모델 라우팅(멀티 모델 — [01 ADR-2], 필요 검증 후) · 의미 캐시·FAQ 사전생성([08 §10] Phase 2) ·
> 프롬프트 캐시(self-hosted Ollama는 공급자 프롬프트 캐싱 미제공 — 공급자 교체 시 재검토).
> 이미 있는 것(중복 구현 금지): 토큰 사용량 영속(`messages.token_input/output`, 추정치 — H1) · 입력 길이 상한(`QUESTION_MAX_CHARS`) ·
> 에이전트 스텝 상한(H3-3) · 컨텍스트 예산(`ai-core/budget` — H1).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H4-0 | 설계 갱신 | §8.5 체크리스트 · [01 §13](01-architecture.md) 대시보드 API 표면 · §8.3 정확 캐시 승격 표기. 신규 ADR 불필요(캐시 스코프는 [08 §2.0]이 정본) | 설계 문서 PR 머지(구현 착수 전) | 진행 중 |
| H4-1 | 질의 레이트 리밋 | [08 §8] 가드레일 — `/assistant/ask`·시설 도우미에 Redis 고정 창 리밋(사용자별·단지별 분당 상한, env로 조정) 초과 시 429. 재시도 폭주 방지는 기존 LlmClient 백오프 확인으로 갈음 | 상한 초과 시 429 + 한도 내 정상, 사용자·단지 카운터 분리 테스트 | ✅ 완료 (PR #15) — Redis 장애 fail-open(경고 로그) |
| H4-2 | 정확 캐시 | [08 §2.0·2.1] — 오케스트레이터 **앞단 얇은 래퍼**(api 계층): 키=`scope + tenant + roles/visibilities + user + 정규화 질의 + 모델 + 원천 revision`. **원천 revision은 tenant별 인제스트 세대 카운터**(Redis, 문서 인제스트 완료 시 INCR — 키 자체가 무효화라 스캔 불필요). 히트 시 저장된 done·citations로 SSE 4이벤트 재생(계약 불변), **개인 데이터 스코프는 user 키 포함 정확 캐시만**·의미 캐시 금지. 히트/미스 카운터(Redis — 대시보드 재료). TTL env | **캐시 격리 CRITICAL**: 같은 질문·다른 사용자/역할/단지 간 히트 전파 없음 + 재색인 후 미스 + 적중 시 LLM 호출 0 테스트 | ✅ 완료 (PR #16) — 재생 직전 tenant 방어선(fail-closed)·캐시 자체는 fail-open |
| H4-3 | 운영 대시보드 | FR-ADM-06 — `GET /admin/dashboard/stats`(MANAGER, 기간 파라미터): 질의 수·평균 토큰(입/출)·폴백률·needs_review율·캐시 적중률·민원 상태 분포·시설 상태 분포. web-admin dashboard 실연동(목업 존재). 집계는 SQL(뷰·별도 테이블 없이 — 파일럿 규모) | 시드 데이터 집계 정합 테스트 + 화면 실연동 | ✅ 완료 (PR #17) — 근거 없는 목업 지표(가짜 차트·비용)는 제거, API 데이터만 표기 |
| H4-4 | 토큰 예산 상한·경고 | NFR-COST-01 — 단지별 일일 토큰 합계(messages 집계)와 env 예산(`LLM_DAILY_TOKEN_BUDGET`, 0=비활성) 비교: stats 응답에 예산·사용량·초과 여부 포함 + 대시보드 경고 배지 + 초과 시 구조화 로그. **차단은 하지 않음**(실비용 상한은 파일럿 측정 후 — 경고만) | 예산 초과 시드에서 경고 플래그·로그 테스트 | ✅ 완료 (PR #18) |

### 8.6 H5 체크리스트 (파일럿 준비 — 모델 확정·평가 확대·알림 루프)

> 근거: 파일럿 차단급·권장 항목만(§8.3 백로그 정리, 2026-07-18). 수요 확인 후 항목(HWP·OCR·자연어 검색·예약 발송·
> 의미 캐시·모델 라우팅·실비용 상한 등)은 §8.3 유지 — 파일럿 없이 착수 금지(YAGNI).
> 별도 트랙: 문서 인제스트 임베딩 마스킹 갭(규칙 2 소지)은 분리 세션 진행 중 — 결과 나오면 본 단계에 편입.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H5-0 | 설계 갱신 | §8.6 체크리스트 · 모델 선정 기준(H5-1) 성문화 | 설계 문서 PR 머지 | 진행 중 |
| H5-1 | LLM 모델 확정 | **tool calling 필수 요건**(H3-3 발견: 로컬 Ollama 0.24.0 qwen2.5:14b는 tool_calls를 content 인라인 — 부적격): 후보(llama3.1:8b·qwen2.5 재pull/업그레이드·기타 비-reasoning)를 ①구조화 tool_calls 반환 ②골든셋 실측(evals 규칙 1·5·6·8 pass율 + [07 §5](07-testing-strategy.md) 도구 경로 적정성) ③`@llm` E2E 그린으로 비교 → 승자를 env 계약·CLAUDE.md에 확정 기록. 골든셋 비교는 기존 evals 러너 재사용(신규 러너 금지) | 확정 모델로 evals 실측 전 케이스 pass + @llm E2E 그린, 선정 근거 문서화 | ✅ 완료 (PR #20) — **llama3.1:8b 확정**(2026-07-18 실측): 유일한 3단계 전부 통과 — 스모크 clean·evals 8/8 pass(46.5s)·@llm E2E 3/3. 탈락: gemma4(도구 미호출)·qwen2.5:14b(외국어 누출)·qwen3.5:9b(인용 마커 미준수로 규칙 1 저촉 + 지연 14배)·qwen3.5:27b(응답 불능). 교훈: 스모크 clean ≠ 파이프라인 통과 — 인용 포맷 규율까지 골든셋으로 확인해야 |
| H5-2 | evals 규칙 2·3 관측 키 | 규칙 2(마스킹): PII 포함 질의 → 응답·영속 텍스트에 원문 PII 부재 관측(마스킹은 LLM 호출 전 단위 테스트가 정본 — 외부 관측은 응답·DB 기준임을 주석 명시). 규칙 3(격리): 타 tenant 데이터 질의 → 답변·인용에 미노출. 관측 불가 케이스는 pending 유지(억지 통과 금지) | 규칙 2·3 케이스 pending→측정 전환(실측 4→6규칙) | ✅ 완료 (PR #21) — 실측 mask-01·tenant-01/02/03 pass, mask-02는 외부 유도 불가로 pending 유지(정본=ai-core 단위 테스트) |
| H5-3 | 알림함 + 검수 정정 알림 | [ADR-0012](adr/0012-in-app-notification-only.md) — `notifications` 테이블(기존 스키마) 라우터(`GET /notifications`·읽음 처리) + web-resident 나>알림함 화면 실연동 + **검수 반려 시 정정 알림 생성**(H2-6 보류분 — 사후 검수 루프 폐합). 알림 생성은 검수 처리 트랜잭션 내 코드, LLM 무관(규칙 6 무저촉·자동발송 아님 — 인앱 함 적재만) | 반려→알림 생성→입주민 조회·읽음 흐름 테스트 | ✅ 완료 (PR #22) — notifications RLS는 tenant 단위뿐 → user 격리는 라우터 필터가 유일 방어선(주석·테스트 명시), 검수 메모 원문 미노출 |

### 8.7 H6 체크리스트 (전 기능 실동작 — 실로그인·목업 해소·전 구간 통합테스트)

> 근거: 사용자 지시(2026-07-18) — "파일럿이지만 계획한 모든 기능이 실제 앱 구현으로 동작. 회원가입 시작부터 AI까지 통합테스트 통과."
> 현황(2026-07-18 전수 조사): 백엔드 인증·온보딩·승인은 **완비**(pytest 통합 검증)이나 **웹이 미배선** — 웹 전체가
> dev 헤더 하드와이어(`credentials` 없음), 온보딩 3화면(login/signup/pending)·admin approvals는 순수 목업,
> 입주민 홈·나(프로필)는 목업, 관리자 네비 뱃지 하드코딩. E2E 7종 전부 dev 헤더 경로(가입~승인 여정 없음).
> **핵심 결정**: ① E2E 로그인은 **mock IdP**(Playwright가 가짜 OAuth 서버 기동, `oauth.py`의 AUTH/TOKEN URL을
> env 오버라이드 — 기본값 Google, 프로덕션 백도어 0·실 PKCE 플로우 그대로 검증) ② 웹 인증은 **세션 쿠키 1차**
> (`credentials:"include"` + 401→로그인 리다이렉트), dev 헤더는 api의 local 보조 경로로만 존치(웹 하드와이어 제거)
> ③ 개요(`/`)·foundation 데모 페이지 제거 ④ 회의록은 문서 관리(source_type)로 커버([04 §3](04-menu-structure.md)) — 신규 화면 없음.
> **주(2026-07-21)**: 본 절의 **mock IdP·Google OAuth·PKCE·초대코드** 서술은 H6 시점 기록이다 — 인증·온보딩은 **H7(§8.8)에서 자체 이메일 인증·초대 토큰으로 전면 교체**([ADR-0014](adr/0014-local-email-auth.md)). H6 완료분은 유지하되 인증 수단은 H7이 대체.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H6-0 | 설계 갱신 | §8.7 · 결정 ①~④ 성문화 | 설계 PR 머지 | 진행 중 |
| H6-1 | 웹 세션 인증 전환 | 웹 2종 api 클라이언트 `credentials:"include"`·401→`/login` 리다이렉트·로그아웃. 로그인 화면을 `GET /auth/google/login` 실배선(목업 push 제거). `GET /me` 기반 화면 분기(onboarding→가입, pending→대기, active→홈). `oauth.py` AUTH/TOKEN URL env 오버라이드(기본 Google — mock IdP 대비). 기존 E2E 7종은 세션 로그인 setup(storageState)으로 전환해 그린 유지 | 세션 쿠키로 웹 전 화면 동작 + 미로그인 접근 시 로그인 유도 + 기존 E2E 그린 | ✅ 완료 (PR #24) — E2E 6종(setup+결정론 5) 세션 쿠키로 그린. 후속: InquiryAdmin 배정자=/me 배선(H6-2), 콜백 앱별 복귀는 후속 |
| H6-2 | 온보딩·승인 실배선 | signup→`POST /onboarding/profile`(초대코드·동의·만14세 서버 검증 — 클라 상수 제거), pending→`GET /me` 실상태, admin approvals→`GET /admin/approvals`·approve/reject 실배선, **명부 업로드 화면**(`POST /admin/roster/upload` — MANAGER), 관리자 네비 뱃지 실데이터(승인 대기·검수 큐 카운트) | 가입 신청→승인→재로그인 상태 전이가 웹에서 동작 | ✅ 완료 (PR #25) — /onboarding 라우트 별칭으로 콜백 정합(api 무변경). 상태별 자동 라우팅 가드(콜백 후 / 진입 분기)는 H6-3에서 루트 정리와 함께 |
| H6-3 | 잔여 목업 해소 | 입주민 홈 실데이터(공지·관리비·내 민원 요약 — 기존 api 재사용), 나(프로필)=`GET /me`·동의 표시 실연동, 개요·foundation 페이지 제거(루트는 홈/로그인 리다이렉트) | 목업 데이터 렌더 0(전 화면 실데이터 또는 빈 상태) | ✅ 완료 (PR #26) — /me 상태별 루트 라우팅 포함(H6-2 후속 해소). 동의 변경·설정 토글 서버 연동은 백로그 |
| H6-4 | 전 구간 통합 E2E | mock IdP(webServer 추가) + 시드에 `pre_registered`(pii_vault 해시) 추가 → **여정: 명부 업로드→가입 신청(명부 일치)→관리자 승인→재로그인→공지·관리비·민원·알림함→AI 질의**. 결정론 구간은 CI 게이트, AI 질의 구간은 `@llm` 로컬. 명부 불일치→pending 대기 분기도 커버 | 가입~AI 전 여정 E2E 그린(CI 결정론 + 로컬 @llm) | ✅ 완료 (PR #27) — 결정론 7·@llm 5 그린. 발견 버그: seed wipe FK 순서(수정)·get_dek 최초 생성 경합(§8.3 등재) |

### 8.8 H7 체크리스트 (온보딩·인증 재설계 — 자체 이메일 인증)

> 근거: 사용자 인터뷰 확정(2026-07-21) — Google OAuth·단지 초대코드·mock IdP를 **자체 이메일+비밀번호 인증**으로 대체([ADR-0014](adr/0014-local-email-auth.md)). 세션 모델([ADR-0011](adr/0011-redis-server-session.md))·봉투 암호화([ADR-0010](adr/0010-envelope-encryption-env-master-key.md))는 **불변** — 인증 수단만 교체.
> 역할 축소: `FACILITY`·`COUNCIL` **제거**(Phase 2 재도입 여지). 남는 역할 `SYS_ADMIN`·`MANAGER`·`STAFF`·`RESIDENT`.
> 근거 설계: [00 §3.7](00-requirements.md)(FR-ONB) · [06 §2](06-security-privacy.md)(인증) · [04](04-menu-structure.md)(역할·메뉴) · [03 §4.1](03-database-design.md)(users·auth_tokens) · [01 §13](01-architecture.md)(API 표면).
> 각 작업 단위는 §3.1 사이클(설계 갱신 → 구현 → 현행화 → PR)을 따르고, 머지는 단위별 사용자 확인 후 진행.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H7-0 | 설계 갱신 | 본 문서들 갱신(00·01·03·04·06·09·11) + [ADR-0014](adr/0014-local-email-auth.md) 신설·[ADR-0011](adr/0011-redis-server-session.md) 갱신. 인증 수단·역할 축소·초대 토큰·메일 어댑터 성문화 | 설계 문서 PR 머지(구현 착수 전) | ✅ 완료 (PR #30) — Gmail SMTP 확정·단지별 가입 링크(초대코드 대체) 포함 |
| H7-1 | 인증 코어 | `users` 마이그레이션(`password_hash`·`email_verified_at`·`login_id` 의미 변경=email HMAC)·`auth_tokens` 테이블·Argon2id(argon2-cffi)·가입/로그인/이메일검증/비밀번호재설정 API([01 §13](01-architecture.md))·메일 어댑터(Protocol, `MAIL_BACKEND=console\|smtp`)·**Google OAuth 코드 제거**(`oauth.py`·PKCE·state). auth_lookup RLS를 email HMAC·token_hash 조회로 조정 | 인증 단위·통합 테스트 — **CRITICAL: Argon2id 해시 저장(평문 0)·검증 전 로그인 차단·토큰 만료·1회용 소진** | ✅ 완료 (PR #31) — 신규 상태 `registered`(가입 완료·프로필 미제출) 도입, 명부 매칭은 가입자 행 유지+pre_registered 소진([03 §4.1](03-database-design.md)). mock IdP 제거·E2E API 로그인 전환을 앞당겨 수행(가입 여정 spec은 H7-3·H7-4까지 skip) |
| H7-2 | 역할·초대 | 최초 SYS_ADMIN 부트스트랩 시드(시스템 테넌트·임시 비밀번호·첫 로그인 변경 강제)·단지 생성+소장 초대 API/화면(web-admin SYS_ADMIN 뷰)·소장→직원 초대(직원 관리 화면)·`FACILITY`/`COUNCIL` 역할 제거·**STAFF 인가 축소**(민원·공지 초안·문서만; 관리비·시설·검수·발행·승인·명부·직원·설정은 소장 전용) | 역할별 인가 테스트(**CRITICAL** — STAFF의 소장 전용 엔드포인트 접근 거부, SYS_ADMIN의 단지 콘텐츠 접근 거부) | 대기 |
| H7-3 | 주민 가입 재설계 | web-resident 온보딩 개편(**초대코드 제거** — 검증 메일 확인 화면·비밀번호 재설정 화면 추가), 승인 화면 명부 일치 배지 유지(자동 승격 없음). 동의·만14세 게이트·동호수 입력은 유지 | 가입→검증→대기→소장 승인 흐름 테스트 | 대기 |
| H7-4 | E2E 재작성 | (mock IdP 제거는 H7-1에서 선행 완료) 새 전 여정(설치 시드→단지 생성→소장 초대·수락→직원 초대→명부 업로드→주민 이메일 가입·검증→소장 승인→AI 질의), `seed_demo` 갱신(구글 계정·초대 행 → 이메일 계정·초대 토큰). 결정론 구간 CI 게이트, AI 질의는 `@llm` 로컬 | 가입~AI 전 여정 E2E 그린(CI 결정론 + 로컬 @llm) | 대기 |

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
