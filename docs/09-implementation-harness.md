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

프로덕션 이미지 스모크(H10-1 — [`infra/compose.prod.yml`](../infra/compose.prod.yml)):

```bash
# 1. env 준비 — 값 채우기(API_ENV=local 필수. 호스트 포트 충돌 시 POSTGRES_PORT 등 조정)
cp infra/env.prod.example infra/env.prod

# 2. 1호스트에서 3프로필 동시 기동 = 배포 형상 그대로
#    migrate 는 `alembic upgrade head` 뒤에 `python -m liviq_db.runtime_roles`(접속 롤 수렴·검증)까지
#    돌린다 — 실패하면 api·ai-worker가 아예 뜨지 않는다(H10-2, docs/03 §5.1).
docker compose --env-file infra/env.prod -f infra/compose.prod.yml \
  --profile data --profile app --profile web up -d --build

# 3. 접속: http://resident.localhost:8080 · http://admin.localhost:8080 (Caddy 경유)

# 4. 최초 SYS_ADMIN 부트스트랩 (api 이미지에 포함된 유일한 시드 스크립트)
#    ★ `api`가 아니라 `migrate` 서비스로 실행한다 — api 서비스는 DATABASE_URL이 런타임 롤
#      (liviq_app)로 오버라이드돼 있어 시드가 권한 오류로 깨진다. migrate는 owner 접속이다(H10-2).
docker compose --env-file infra/env.prod -f infra/compose.prod.yml \
  run --rm --workdir /app migrate python scripts/bootstrap_sys_admin.py --email <이메일>

# 5. 정리 (볼륨까지 — 개발 인프라 볼륨과 별개다)
docker compose --env-file infra/env.prod -f infra/compose.prod.yml \
  --profile data --profile app --profile web down -v
```

- 평소 개발 루프는 **네이티브 유지**(HMR·reload 속도) — 컨테이너는 배포 전 스모크·운영 배포용([ADR-0020](adr/0020-container-deploy-3tier-vm.md)).

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
| 컨테이너 베이스(Python) | 빌더 `ghcr.io/astral-sh/uv:0.11.14-python3.12-trixie-slim` → 런타임 `python:3.12-slim-trixie` | api·ai-worker 공용. **Python 마이너뿐 아니라 Debian 릴리스도 빌더·런타임 일치** 필요 — 복사한 `.venv`의 컴파일 wheel(glibc) 때문 |
| 컨테이너 베이스(웹) | `node:20.20.1-alpine3.22` (builder·runner 동일) | Next standalone 런타임(web-resident·web-admin) |
| 리버스 프록시 | `caddy:2.11.4-alpine` | TLS 종단 · `/api` 프록시(web tier) |

- **RLS 정책 SQL은 Alembic custom migration(`op.execute`)으로 버전 관리**한다 — 스키마 자동생성(autogenerate)이 만들지 못하는 정책·role을 마이그레이션 파일로 고정(코드 리뷰가 아니라 마이그레이션 이력으로 추적).
- **운영 이미지 태그는 고정 태그 핀**이다(재기동 시 실체가 바뀌는 `latest` 금지). 로컬 [`infra/docker-compose.yml`](../infra/docker-compose.yml)이 `latest`로 쓰던 3개는 H10-1에서 [`infra/compose.prod.yml`](../infra/compose.prod.yml)에 **고정 태그로 해소**했다 — `minio/minio:RELEASE.2025-09-07T16-13-09Z` · `minio/mc:RELEASE.2025-08-13T08-35-41Z` · `neo4j:5.26.28-community`(5.26 LTS). 함께 핀한 나머지: postgres `pgvector/pgvector:0.8.5-pg16` · redis `redis:7.4.10-alpine`. 앱 4종 자체 이미지의 태그 규칙은 §4.3.
- **uv 공식 이미지의 `bookworm` 변형은 0.9.30에서 단절**됐다(현행 태그는 trixie/alpine 계열만) — H10-1에서 설계상 bookworm 계획을 **trixie로 전환**하고 런타임도 `python:3.12-slim-trixie`로 맞췄다.

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
merge(main): 이미지 4종 빌드·GHCR push(sha + latest 태그)
     → (수동) VM 배포: data → migrate → app → web → 스모크 → 필요 시 이전 sha로 롤백
```
> merge(main) 라인은 **H10-3에서 배선**했다(`release.yml` — §4.3). **VM 배포는 수동 절차**다
> ([12 배포 런북](12-deployment-runbook.md)) — CI가 운영 호스트에 SSH로 들어가지 않는다(배포
> 자격증명을 CI에 두지 않는다는 선택. 스테이징 자동 배포는 스테이징 VM이 실존할 때 재검토).

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

### 4.3 릴리스 파이프라인 (`release.yml` 스펙 — H10-3에서 추가)

앱 4종을 컨테이너 이미지로 만들어 3-tier VM(web/app/data)에 배포한다([ADR-0020](adr/0020-container-deploy-3tier-vm.md)). 아래는 `.github/workflows/release.yml`의 계약이며 **워크플로 파일 자체는 H10-3에서 추가**한다.

| 항목 | 값 |
|------|----|
| 트리거 | **push(main)** = 빌드+push · **PR** = 빌드만(push 없음, `paths` 한정 — Dockerfile·compose·`release.yml`·`pnpm-lock`·`uv.lock` 변경 시) · `workflow_dispatch` 수동 재실행. **릴리스 태그 트리거는 보류** — 버전 체계(semver·CHANGELOG)가 없어 sha 핀만으로 충분하다(YAGNI) |
| 대상 이미지 | [`api`](../apps/api/Dockerfile) · [`ai-worker`](../apps/ai-worker/Dockerfile) · [`web-resident`](../apps/web-resident/Dockerfile) · [`web-admin`](../apps/web-admin/Dockerfile) — 4개 모두 H10-1에서 실존 |
| 빌드 컨텍스트 | **레포 루트**(uv workspace 단일 lock · pnpm workspace 때문에 앱 디렉토리 컨텍스트로는 빌드 불가). 제외는 루트 [`.dockerignore`](../.dockerignore) |
| 빌드 방식 | docker buildx(멀티 스테이지) — Python은 `uv sync --frozen --no-dev --no-editable --package <멤버명>` 후 런타임 스테이지에 `.venv`만 복사(non-root uid/gid 10001). **`--no-editable` 필수**: 기본값(editable)이면 `.venv`가 빌더의 소스 경로를 가리켜 `.venv`만 복사한 런타임에서 import가 깨진다 — 멤버가 실제 wheel로 site-packages에 들어가므로 **런타임에 앱 소스를 따로 복사하지 않는다**(중복 shadowing 방지). 레이어 캐시는 2단계(`--no-install-workspace`로 외부 의존만 먼저 → 소스 복사 후 멤버 설치). 웹은 pnpm 빌드 후 Next standalone 산출물만 복사(`node` 사용자) |
| 웹 standalone 경로 | `distDir`이 `.next-build`라 진입점은 `.next-build/standalone/apps/<앱>/server.js`, static은 `standalone/apps/<앱>/.next-build/static`에 배치. 런타임 `HOSTNAME=0.0.0.0` 필수(미설정이면 localhost만 바인드). `public/`은 두 앱 모두 없음 |
| 레지스트리 | **GHCR** — `ghcr.io/${{ github.repository_owner }}/liviq-<앱>`(오너 하드코딩 금지). 패키지 기본 가시성은 **private**이라 배포 호스트는 `read:packages` PAT로 `docker login ghcr.io` 필요([12 §3](12-deployment-runbook.md)) |
| 태그 규칙 | **git sha + `latest`** 동시 push. **배포는 sha 태그 핀 고정**(§4.3 하단) |
| 캐시 | buildx `cache-from`/`cache-to: type=gha`(앱별 스코프) |
| 웹 빌드 인자 | `NEXT_PUBLIC_API_BASE_URL=/api` — `NEXT_PUBLIC_*`은 빌드타임 인라인이라 **런타임 env로 못 바꾼다**. 브라우저→api는 Caddy `/api/*` `strip_prefix` 프록시로 same-origin |
| 시크릿 취급 | **이미지에 미포함**(빌드 인자·레이어에 시크릿 금지) — DB·세션·`PII_MASTER_KEY`·SMTP·LLM 엔드포인트는 전부 **런타임 주입**(`env_file`, 레포 밖 0600). LLM은 컨테이너 밖 외부 엔드포인트를 env로만 가리킨다([ADR-0005](adr/0005-single-llm-openai-compat.md) 유지) |
| 마이그레이션 | api 이미지를 재사용하는 one-shot `migrate` 서비스(`working_dir: /app/packages/db` · `alembic upgrade head`). Alembic 자산은 wheel 밖(`packages/db/alembic`·`packages/db/alembic.ini`)이라 이미지에 **명시 복사** |
| api 이미지 3역할 | ① api 서버(기본 CMD `uvicorn app.main:app --proxy-headers`) ② 마이그레이션 러너 ③ **최초 SYS_ADMIN 부트스트랩**(`/app/scripts/bootstrap_sys_admin.py` — 신규 배포에서 첫 관리자를 만드는 유일한 경로라 이미지에 포함). `scripts/`의 나머지(seed_demo·seed_parking·seed_households·backfill)는 **의도적 제외** — seed_demo가 공개된 고정 비밀번호로 MANAGER를 만들어 운영 이미지에 두면 위험 |

- **기동 순서**: data(postgres·redis·minio·neo4j) → `migrate`(완료 대기) → app(api·ai-worker) → web(Caddy·web-resident·web-admin). compose `profiles`(`data`/`app`/`web`) + `healthcheck`·`depends_on`으로 강제한다.
- **롤백**: 이전 sha 태그로 재기동(코드만 되돌림 — 파괴적 스키마 변경은 [03 §8](03-database-design.md) 2단계 규칙으로 앞뒤 호환 유지).
- **`latest` 배포 금지**: 같은 태그의 실체가 push마다 바뀌어 "직전으로 되돌리기"가 성립하지 않는다. `latest`는 편의 포인터로만 유지하고 배포·롤백은 sha 핀만 쓴다.

### 4.4 사내 GitLab 파이프라인 (`.gitlab-ci.yml` 스펙 — H12)

두 번째 배포 형상용이다([ADR-0021](adr/0021-gitlab-ci-single-host-wsl.md)) — 사내 단일 호스트
(Windows Server + WSL2 Docker)에 GitLab CI가 배포한다. GitHub Actions [`release.yml`](../.github/workflows/release.yml)(§4.3)는
**유지**되고, 두 파이프라인이 각자의 레지스트리에 같은 커밋의 이미지를 게시한다.

> **실측 반영(H12-2)**: 아래 표는 실호스트에서 파이프라인이 그린이 된 뒤의 형상이다. H12-1 초안과
> 다른 곳이 셋 있다 — ①배포는 **레지스트리 pull이 아니라 로컬 빌드 이미지**로 한다(러너가 같은
> 호스트라 push→pull 왕복 ≈1.3GB가 순수 낭비) ②게시는 **스모크 통과 후**로 내려갔다(검증된 것만
> 레지스트리에 남긴다) ③러너 태그는 `wsl`,`docker`다(`wsl-140`은 존재하지 않는 태그였다).
> 절차·함정은 [13](13-gitlab-wsl-deploy.md)이 단일 출처.

| 항목 | 값 |
|------|----|
| stage | `build → deploy → verify(smoke) → publish` + 수동 `rollback`·`prune` |
| 진입점 | [`infra/deploy-wsl.sh`](../infra/deploy-wsl.sh) — CI와 수동 운영의 **공용**. 잡은 `bash infra/deploy-wsl.sh <cmd>` 한 줄 |
| 트리거 | push(main) — 전 stage · MR — `build`만(기동 없음) · 수동(`web`·`api` source) — 전 stage + rollback·prune |
| 러너 | **대상 호스트 WSL 안**의 `shell` executor(태그 `wsl`,`docker`). 아웃바운드 폴링만 — 대상 호스트 인바운드 개방 0 |
| 배포 소스 | `build`가 만든 **로컬 이미지**. 레지스트리 왕복 없음 |
| 이미지 좌표 | `IMAGE_PREFIX`가 **구분자까지 포함**한다(ADR-0021 결정 5). 이 형상에서는 로컬 이름 **`liviq-`** — 레지스트리 좌표는 게시에만 쓰고 `$CI_REGISTRY_IMAGE`로 온다 |
| 태그 | `$CI_COMMIT_SHORT_SHA`(8자 — `deploy-wsl.sh`의 `git rev-parse --short=8`과 같은 폭) + 게시 시 `latest`(편의 포인터, 배포 금지) |
| 게시 | `needs: [smoke]` — 검증 통과 후에만 **Nexus** docker hosted 저장소로 push(`192.168.10.153:8082/liviq/<앱>`). GitLab 컨테이너 레지스트리는 **포트 미노출로 사용 불가**(실측 — [13 §8](13-gitlab-wsl-deploy.md)). `allow_failure` 없음: 게시 실패 = 롤백 백업 없음이므로 빨개져야 한다. 자격증명은 protected CI 변수 `REGISTRY_USER`·`REGISTRY_PASSWORD`(보호 브랜치에서만 주입 — 비보호 브랜치에서 잡 토큰으로 폴백하면 남의 레지스트리에 401) |
| 빌드 | 4종을 **한 잡에서 순차**(4코어 — 병렬은 메모리·CPU를 다퉈 더 느리고 레이어 캐시는 순차에서도 공유). 컨텍스트는 **레포 루트**(§4.3과 동일) |
| 배포 명령 | `-f compose.prod.yml -f compose.wsl.yml --profile data --profile app --profile web up -d` = **1호스트 3프로필**(H10-1 스모크와 같은 형상) |
| WSL 오버레이 | [`infra/compose.wsl.yml`](../infra/compose.wsl.yml) — 차이 **하나**: `host.docker.internal:host-gateway`(WSL Docker CE는 이 이름을 주입하지 않아 LLM 기본 엔드포인트가 DNS 실패). `compose.prod.yml`은 3-tier 형상의 단일 출처라 건드리지 않는다 |
| 스모크 | Caddy 경유 4건 — api `/health` 200 · web 2종 200/307/308 · `X-Frame-Options: DENY`. `Host` 헤더 명시(`*.localhost`는 curl에서 해석 안 될 수 있다). 실패 시 **자동 롤백 없음**(운영 판단) |
| env | `/etc/liviq/env.prod`(레포 밖·**0640 root:gitlab-runner**). 스크립트는 `source`하지 않고 필요한 비민감 키만 뽑는다(시크릿을 CI 로그·자식 프로세스로 흘리지 않기) |
| 동시성 | `resource_group: liviq-prod` + `interruptible: false` — 같은 compose 프로젝트를 두 잡이 동시에 만지지 못하게, 배포를 중간에 끊지 못하게 |
| 불변 계약 | 3-URL 접속 롤(H10-2) · `migrate` 2단계 · Caddy same-origin `/api`·SSE `flush_interval -1` |
| 롤백 | 수동 `rollback` 잡 + 파이프라인 변수 `ROLLBACK_TAG=<sha 8자>`. **그 태그 이미지가 호스트에 남아 있어야** 한다(`tags`로 확인, `prune`이 최근 5개만 보존) |

- **`.gitlab-ci.yml`이 main에 있어야** push가 파이프라인을 만든다. 없으면 GitLab이 Auto DevOps 템플릿을 대신 돌려 `shell` executor에서 실패한다(실측 — 명시적 CI 설정이 우선하므로 머지하면 사라진다).
- **push 시점에 WSL이 떠 있어야** 한다. 러너는 WSL 안 systemd 서비스이고 Windows 재부팅 후 WSL은 자동 시작되지 않는다 → 잡이 `pending`으로 쌓이고 방치되면 stuck으로 실패([13 §3.1](13-gitlab-wsl-deploy.md)).
- **러너 URL은 GitLab 정본 주소**를 쓰고, `config.toml`에 `clone_url`을 명시한다 — `external_url`에 포트가 빠져 있어 CI가 받는 클론 URL이 80을 가리킨다(레지스트리 realm 문제와 같은 뿌리).

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
| H7. 온보딩·인증 재설계 | 자체 이메일+비밀번호 인증(Argon2id·검증 메일·`auth_tokens`)·역할 축소(FACILITY·COUNCIL 제거)·단지/소장/직원 초대·단지·계정 수명주기·명부 운영 도구·주민 관리 목록 | 역할·수명주기 인가 테스트(CRITICAL) + 설치~가입~AI 전 여정 E2E 그린 | ✅ 완료 (2026-07-22, §8.8) — Google OAuth 전면 제거([ADR-0014](adr/0014-local-email-auth.md)), E2E 15/15 |
| H8. 게시판 전환·운영 개편 | 공지·문서 AI 초안 폐기 후 게시판화(첨부·버전·예약 발행·공지 벡터화)·공통 코드 레지스트리·동/호수 관리·관리비 고지서(총액 트리 분배)·AI 검수 큐 제거·민원 수동 워크플로·관리자 콘솔(메뉴 그룹·액션 큐) | 첨부·코드·민원 인가/격리 테스트(CRITICAL) + 게이트 그린 + 시각 실측 | ✅ 완료 (2026-07-24, §8.10) — [ADR-0015](adr/0015-notice-board-replaces-ai-draft.md)·[0016](adr/0016-document-board-versioned-attachment.md)·[0017](adr/0017-tenant-code-registry.md)·[0018](adr/0018-inquiry-manual-handling.md) |
| H9. 단지 트윈·주차장 | `household_geometries` + deck.gl 3D·오버레이 4종(입주·민원·관리비·설비)·세대 상세·VWorld 실사 3D 토글·트윈 대시보드·주차장 배치도(442면·차량 348대 `plate_enc`) | tenant 격리·MANAGER 인가(CRITICAL)·plate 암호화 왕복 + 게이트 그린 + 라이브 시각 실측 | ✅ 완료 (2026-07-25, §8.11) — [ADR-0019](adr/0019-complex-twin-3d.md), 프로토타입 수치 완전 일치 |
| H10. 컨테이너 배포 | 앱 4종 이미지(GHCR)·3-tier VM `compose.prod.yml` profiles(data/app/web)·리버스 프록시 same-origin(`/api`)·CI 릴리스 | 로컬 전체 스택 스모크 그린 + 이미지 GHCR 게시 + 배포·롤백 절차 문서화 | ✅ 완료 (2026-07-26, §8.13) |
| H11. 운영 정합 | 감사 로그 실배선(보안 핵심 행위)·문서·스키마 드리프트 정정 | 감사 행위별 기록 테스트(CRITICAL — 개인정보 비저장 포함) + 문서와 실제 스키마 일치 | ✅ 완료 (2026-07-26, §8.14) |
| H12. 사내 GitLab 배포 | GitLab CI 파이프라인(빌드·배포·스모크·게시)·단일 호스트(WSL Docker) 형상·이미지 좌표 규약 변경 | main push로 대상 호스트 배포 그린(Caddy 경유 스모크) + 롤백 실연. 레지스트리 게시는 서버 `external_url` 미해결로 `allow_failure` | 🚧 진행 (§8.15) |
| H13. 시설 그래프·평면도 | 시설관리 메인을 3D 시설 그래프로(계통/위치 렌즈·검색 fly-to·상세 패널)·민원-시설 연결 3단·세대 평면도(데이터·입주민 뷰·편집·어시스턴트 도구) | tenant 격리·MANAGER 인가·**LLM 추천 승인 게이트**(CRITICAL) + Neo4j 미가용 폴백 + 게이트 그린 + 시각 실측 | ✅ 완료 (2026-07-27, §8.16 — PR #94~#98 스택, 머지 대기) — [ADR-0022](adr/0022-facility-graph-dashboard.md) |
| H14. 시설관리 UX 개편·코드 체계 | 시설관리 탭 폐지→전체화면 그래프+플로팅 패널(도면→방·종류→마커 계층)·시설 코드 체계(계통-위치-연번)·평면도 공통코드·트윈 평면도 동일화·주차장 3D(주행 차량)·관리자 전 메뉴 UI 일관화(§5A 가이드) | 코드 자동부여 유일성·tenant 격리(CRITICAL) + FloorPlan 잔존 노드 재발 방지 + 게이트 그린 + 시각 실측 | ✅ 완료 (2026-07-28, §8.17 — 단일 브랜치 PR, 머지 대기) |
| H15. LLM 백엔드 런타임 전환 | SYS_ADMIN AI 설정 UI(base URL·모델·API 키·연결 테스트)·`ai_backend_config` 전역 테이블·요청 단위 즉시 반영(env 폴백)·백엔드 비교 측정(ollama vs vLLM vs OpenAI) | SYS_ADMIN 인가(CRITICAL)·API 키 마스킹 응답 + 캐시 키 백엔드 분리 + 게이트 그린 + 시각 실측 | 🚧 진행 (§8.18 — H15-1 ✅·H15-3 ✅, H15-2 로컬 축 완료·GraphRAG 비교(G1~G4) 개발서버 실측 완료·OpenAI 축 대기 · H15-4 멀티-검색 라우팅+주차+3자 측정 ✅ 완료(8B 유지 — 점유 저장 형태는 H16이 대체)) |
| H16. 주차 점유 실데이터화 | 프론트 점유 시뮬 폐기 → DB 단일 출처: `parking_vehicles.spot_no`·`entry_at`·`household_id NULL`(외부 차량) + 시드 결정적 배정 + API 확장 + 웹 실데이터 렌더. H15-4의 `parking_occupancy` 별도 테이블은 이 설계로 대체(ADR-0023 개정) — 최근접 빈자리 도구는 spot_no 기반으로 재배선 | 부분 유니크(tenant, spot_no)·RLS 유지(CRITICAL) + 시드 멱등 + 게이트 그린 + 시각 실측 | ✅ 완료 (§8.19) |

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
| ~~공지 예약 발송 실행기~~ | [03 §4.4](03-database-design.md) `scheduled_at` | **H8-1로 승격**(2026-07-22, §8.10) — `ai-worker` arq cron(1분 폴링) 실행기 |
| ~~공지 초안 인용 영속~~ | [03 §4.3](03-database-design.md) citations | **무효(H8-1, [ADR-0015](adr/0015-notice-board-replaces-ai-draft.md))** — 공지 AI 초안 제거로 초안 인용 개념 소멸 |
| 그래프 tombstone·전체 리플레이 실행기 | [03 §4.9](03-database-design.md)·[11 §3.5](11-data-architecture.md) | H3-2는 created·updated만 — 시설 delete 엔드포인트(producer)가 없어 deleted 이벤트 미발생. soft delete API 도입 시 tombstone 반영·리플레이 ops 스크립트 추가 |
| ~~get_dek 최초 생성 경합(uq 위반)~~ | [ADR-0010](adr/0010-envelope-encryption-env-master-key.md) | **해소(PR #28, 2026-07-18)** — ON CONFLICT DO NOTHING+재조회 원자화, 결정론 경합 pytest(RED 재현 후 GREEN) |
| 동의 변경·설정 토글 서버 연동 | [04 §2](04-menu-structure.md) 나 화면 | H6-3은 표시 전용 — 동의 변경 API 부재. 수요 확인 후 |
| ~~OAuth 콜백 앱별 복귀~~ | H6-1 | **H7-1에서 대체**(§8.8) — 자체 이메일 인증 전환으로 OAuth 콜백 자체 제거 |
| 한글 NFD/NFC 정규화 불일치 — 제목 검색 무력화 | [03 §4.2](03-database-design.md) documents·[04 §3](04-menu-structure.md) | **재현되는 사용자 영향 버그**(H8-10 후속 검증 중 발견, 2026-07-25). macOS 파일명은 NFD(분해형) → `DocumentForm.tsx:57`이 제목을 파일명에서 자동 채움 → title이 NFD로 저장(실측 `title = normalize(title, nfc)` → false) → 사용자는 키보드로 NFC 입력 → 부분일치 실패로 **0건**. 영향 4곳: `documents/data.ts:57`·`inquiry-admin/InquiryAdmin.tsx:133`(클라이언트 부분일치)·`documents.py:135`·`fees.py:227`(서버 `ilike` — Postgres도 NFD/NFC 구분, 동 이름은 숫자라 영향 낮음). 수정 방향은 **경계에서 NFC 정규화**(서버 저장 시 — 그러면 검색 4곳은 미변경으로 일치) + 기존 데이터 `normalize(title, nfc)` 마이그레이션 + 파일명 자동 채움 지점 `.normalize("NFC")` 보강. 별도 작업 단위로 착수 |
| 기존 벡터 일괄 재색인 — 마스킹 기준 소급 적용 | [ADR-0015 개정 노트](adr/0015-notice-board-replaces-ai-draft.md)·[06 §4.2](06-security-privacy.md) | **임베딩 마스킹 수정(PR #73, 2026-07-25)은 소급되지 않는다** — 그 전에 색인된 `content_chunks.embedding`은 원문 임베딩이고, 프로바이더에 원문이 전송된 사실도 취소 불가. 파일럿까지 로컬 Ollama만 썼다면 실질 외부 노출은 없으나, 외부 엔드포인트를 붙인 이력이 있으면 별도 판단 필요. 착수 조건: 재색인 ops 스크립트(문서·공지 전량 재인제스트 큐잉 — 문서는 `index_status` 리셋, 공지는 published 전량) + 벡터 교체 전후 검색 회귀 확인. 재업로드 시엔 개별 자동 해소되므로 **운영 데이터가 쌓이기 전에 실행**하는 편이 싸다 |
| **감사 로그 잔여 행위 + 이상 징후 알림** | [06 §8](06-security-privacy.md) | 낮음 — H11-1이 보안 핵심 11종을 배선했고, 나머지 3종은 문서 공개범위 변경·공지 발행·ERP 동기화(ERP 자체가 미구현)다. 이상 징후 알림(대량 조회·비정상 시간대·마스킹 우회)은 **감사 행이 실제로 쌓인 뒤** 룰을 정한다 — 지금 정하면 임계값이 추측이 된다 |
| **존재하지 않는 이메일의 로그인 실패 미기록** | [06 §8](06-security-privacy.md) | 낮음 — tenant를 특정할 수 없어 RLS가 INSERT를 거부한다(fail-closed). 이 표면은 레이트 리밋이 방어하고, 기록하려면 시스템 테넌트에 쓰는 별도 경로가 필요하다(크리덴셜 스터핑 탐지가 실제 요구로 올라올 때) |

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
> ③ 개요(`/`)·foundation 데모 페이지 제거 ④ 회의록은 문서 관리(문서 카테고리 코드, H8-6 이후 DOC_CATEGORY)로 커버([04 §3](04-menu-structure.md)) — 신규 화면 없음.
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
| H7-2 | 역할·초대 | 최초 SYS_ADMIN 부트스트랩 시드(시스템 테넌트·임시 비밀번호·첫 로그인 변경 강제)·단지 생성+소장 초대 API/화면(web-admin SYS_ADMIN 뷰)·소장→직원 초대(직원 관리 화면)·`FACILITY`/`COUNCIL` 역할 제거·**STAFF 인가 축소**(민원·공지 초안·문서만; 관리비·시설·검수·발행·승인·명부·직원·설정은 소장 전용) | 역할별 인가 테스트(**CRITICAL** — STAFF의 소장 전용 엔드포인트 접근 거부, SYS_ADMIN의 단지 콘텐츠 접근 거부) | ✅ 완료 (PR #32) — users.must_change_password·신규 상태 invited 추가, 강제 변경 게이트+`POST /auth/password-change`. 시스템 테넌트는 단지 목록 제외·초대 불가 |
| H7-3 | 주민 가입 재설계 | web-resident 온보딩 개편(**초대코드 제거** — 검증 메일 확인 화면·비밀번호 재설정 화면 추가), 승인 화면 명부 일치 배지 유지(자동 승격 없음). 동의·만14세 게이트·동호수 입력은 유지 | 가입→검증→대기→소장 승인 흐름 테스트 | ✅ 완료 (PR #33) — /signup?t={tenant_id}(가입 링크 정본)·/reset-password 신설, 온보딩 프로필 폼 초대코드 전면 제거. 실여정 스모크(가입→검증→온보딩→대기→승인→active) 실측 |
| H7-4 | E2E 재작성 | (mock IdP 제거는 H7-1에서 선행 완료) 새 전 여정(설치 시드→단지 생성→소장 초대·수락→직원 초대→명부 업로드→주민 이메일 가입·검증→소장 승인→AI 질의), `seed_demo` 갱신(구글 계정·초대 행 → 이메일 계정·초대 토큰). 결정론 구간 CI 게이트, AI 질의는 `@llm` 로컬 | 가입~AI 전 여정 E2E 그린(CI 결정론 + 로컬 @llm) | ✅ 완료 (PR #34) — 여정 5단계 직렬 분할(단계별 타임아웃 예산), 메일 링크는 토큰 트릭(원문 아는 토큰 pg INSERT)으로 결정론 확보. seed_demo는 이메일 3종(FACILITY 삭제) |
| H7-5 | 온보딩 UX 보수 | 운영자 실사용 피드백(2026-07-21) 반영: ①주민 가입 진입 = 로그인 화면 **회원가입 버튼** + **단지 선택**(`GET /auth/tenants` 공개 단지 목록 — `?t=` 링크는 사전 선택, [ADR-0014] 개정) ②관리자 메뉴 **직원 관리** 최상위 승격(설정 하위 제거, `/settings`→`/staff`) ③직원 목록·`/me`에 **이메일 표시**(식별 불가 목록 해소 — [ADR-0014] 개정) ④관리자 로그인 문구 정리·사이드바 하단 실제 계정 표시(하드코딩 "관리자/관리사무소" 제거) ⑤목록 `ul` 스타일 리셋(카드 밀림·잘림 수정) | 전 화면 브라우저 시각 검증(스크린샷) + 단위·E2E 그린 | ✅ 완료 (PR #35) — E2E는 픽커(정본)·딥링크 두 경로 검증, 시각 검증은 데스크톱+모바일(375px) 실측 |
| H7-6 | 관리 계정·단지 수명주기 | 운영자 인터뷰(2026-07-22) 확정([ADR-0014] 개정, [00](00-requirements.md) FR-ONB-08·12): ①**단지당 소장 1명**(초대 409 + UI 현재 소장 표시) ②직원·타 소장 **삭제**(소프트 삭제+PII 비식별+세션 revoke — 직원←소장, 소장←타 소장·SYS_ADMIN, 자기 자신 불가) ③**빈 단지만 완전 삭제** + 운영 단지 **비활성화/재활성화**(로그인 403·가입 목록 제외·세션 revoke) ④소장 로그인 홈 = 대시보드 | 수명주기 인가 테스트(**CRITICAL** — 자기 자신 삭제 거부·비식별 후 평문 잔존 0·비활성 단지 로그인 차단) + 시각 스윕 + E2E 그린 | ✅ 완료 (PR #36) — pytest 212(신규 5종)·E2E 15/15·시각 스윕 8/8, UI 전 수명주기(생성→초대→소장 제거→비활성/재활성→삭제·409 거부) 실조작 검증. 비식별은 DB 실측(login_id·pw·email_enc 말소) |
| H7-7 | 명부 운영 도구 | 운영자 요청(2026-07-22): ①**명부 업로드 양식 다운로드**(`GET /admin/roster/template` — 헤더·예시 행을 파서(`EXPECTED_HEADER`)와 단일 출처로 생성, 가입 승인 화면 버튼) ②**세대 마스터 시드 스크립트**(`scripts/seed_households_xlsx.py` — households 시트(동·호·층) → buildings·households 멱등 upsert; 세대 마스터 관리 UI는 Phase 2, [04](04-menu-structure.md) 단지 관리) | 양식 라운드트립 테스트(생성 파일이 파서 통과) + 시드 스크립트 실측 | ✅ 완료 (PR #37) — 양식 다운로드 라운드트립·403 테스트, 시드 스크립트 322세대 실측(멱등 재실행 신규 0), 가입 승인 화면 링크 실측(200·xlsx) |
| H7-8 | 온보딩 동·호 숫자 입력 | 운영자 요청(2026-07-22): 온보딩 프로필의 동·호를 **숫자 직접 입력**으로 전환 — 기존 select는 90세대 레이아웃(101~103동·층당 2호) **하드코딩**이라 실단지(401~405동, 322세대) 주민이 선택 자체 불가. 최종 판정은 서버 세대 조회(없으면 422)로 불변 | 클라 검증(숫자·범위) 단위 테스트 + E2E 갱신 그린 | ✅ 완료 (PR #38) — 실명부(401동 201호)로 가입 신청→명부 일치(roster_matched=t)→대기 화면 실측 |
| H7-9 | 주민 관리 개편 | 운영자 인터뷰(2026-07-22): 명부가 쓰기 전용(업로드 결과만 반짝)이라 상태 확인 불가 → **가입 승인 화면을 '주민 관리'로 개편(목록 위주 UX)**. ①`GET /admin/roster` — 명부 목록(성함 마스킹·생년 비표시, 상태=미가입/가입완료(소진)/전출후보, 검색·페이지네이션)+총계+마지막 업로드 요약 ②승인 카드 **불일치 사유** 구체화(세대 없음/인적 불일치/이미 소진) ③메뉴·라우트 `/approvals`→`/residents` | 명부 상태 분류·검색 테스트 + 시각 실측 + E2E 갱신 그린 | ✅ 완료 (PR #39) — 실명부 892건으로 총계·검색(405→182건)·필터·페이지네이션·불일치 사유 실측, pytest 23(명부·사유 신규)·E2E 15/15 |

### 8.9 운영 절차: 메일 실발송(Gmail SMTP) 설정

local 기본은 `MAIL_BACKEND=console`(발송 없이 API stdout에 링크 출력 — 개발용). 실제 메일(소장 초대·가입 검증·비밀번호 재설정)을 보내려면 [ADR-0014](adr/0014-local-email-auth.md)의 Gmail SMTP를 켠다:

1. 발신 Gmail 계정(파일럿: sllm14628@gmail.com)에 **2단계 인증** 활성화 — 앱 비밀번호의 전제 조건.
2. <https://myaccount.google.com/apppasswords> 에서 **앱 비밀번호**(16자) 발급 — 일반 로그인 비밀번호는 SMTP에서 거부된다.
3. `apps/api/.env`에 설정(시크릿은 env로만 — 커밋 금지):

   ```bash
   MAIL_BACKEND=smtp
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587            # STARTTLS
   SMTP_USER=sllm14628@gmail.com
   SMTP_PASSWORD=<앱 비밀번호 16자>
   SMTP_FROM=sllm14628@gmail.com
   ```

4. API 재시작 후 소장 초대 1건으로 실발송 확인. 필수값 누락 시 부팅이 아닌 발송 시점에 fail-closed(RuntimeError).

> 앱 비밀번호는 `xxxx xxxx xxxx xxxx`로 표시된다 — 복사하면 공백(NBSP 포함)이 섞이지만 `get_mailer`가 유니코드 공백을 제거하므로 그대로 붙여넣어도 된다(2026-07-21 실측: NBSP가 SMTP AUTH에서 UnicodeEncodeError 유발 → 코드에서 방어).

무료 Gmail 일 발송 한도(약 500통)는 파일럿 규모에 충분 — 초과 시 어댑터 뒤에서 SES 등으로 교체.

### 8.10 H8 체크리스트 (게시판 전환 — 공지·문서)

> 근거: 운영자 인터뷰 확정(2026-07-22) — 공지·문서 모두 관리사무소가 직접 작성하는 게시판으로 전환. 공지는 키워드→AI 초안→검수 흐름이 실무에 불요하고 첨부파일이 실제 요구라 AI 초안 자산을 **완전 삭제**([ADR-0015](adr/0015-notice-board-replaces-ai-draft.md)), 문서는 첨부 1개·버전 이력 게시판([ADR-0016](adr/0016-document-board-versioned-attachment.md)).
> 권한 개정(H8-1): **MANAGER·STAFF 모두** 공지 작성·발행 — H7-2 STAFF 인가 축소 중 **공지 발행**만 STAFF에 개방(관리비·시설·검수·승인·명부·직원·설정은 소장 전용 유지). 공지 경로 AI 미개입으로 규칙 6(자동발송 금지)의 공지 표면은 원천 제거되며, 검수 게이트·규칙 6은 assistant 등 다른 AI 표면에 유지.
> 근거 설계: [00 §3.4](00-requirements.md)(FR-ADM-01·07·08) · [01 §13](01-architecture.md)(공지·문서·코드 API) · [03 §4.4·§4.10](03-database-design.md)(notices·notice_attachments·content_chunks·code_groups·codes) · [04](04-menu-structure.md)(메뉴).
> 코드 레지스트리 근거(H8-4~6): 운영자 인터뷰(2026-07-22) — 실단지 공지 샘플(분류·행사 기간·대상 동·키워드) 등록 요구가 스키마 확장을 부르는데, 분류를 하드코딩하지 않고 **공통 코드 관리 시스템**(설정 메뉴)으로 흡수한다([ADR-0017](adr/0017-tenant-code-registry.md)).
> 각 작업 단위는 §3.1 사이클(설계 갱신 → 구현 → 현행화 → PR)을 따르고, 머지는 단위별 사용자 확인 후 진행.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H8-1 | 공지 게시판 전환 | 공지 AI 초안 **완전 삭제**(ai-core `notice_draft.py`·초안 API 2개(`POST`·`GET /admin/notices/drafts`)·`notice_drafts` 테이블 drop) → 일반 게시판(작성·수정·삭제(soft)·상단 고정(pinned)·임시저장(draft)·예약 발행(scheduled)·첨부 pdf·hwp·hwpx·docx·xlsx·jpg·png 파일당 20MB·공지당 5개, MinIO 저장·다운로드 API 경유)·**STAFF 발행 허용**·메뉴명 "공지 초안"→"공지사항"·예약 발행 `ai-worker` arq cron(1분 폴링, scheduled_at 도달 시 published+알림)·eval 규칙6 케이스 2개(`broadcast-01-draft-only`·`review-02-notice-draft`) 제거([ADR-0015](adr/0015-notice-board-replaces-ai-draft.md)) | 첨부 인가 테스트(**CRITICAL** — 교차 tenant 첨부 접근 거부·미발행 공지 첨부 입주민 접근 거부)·예약 발행 cron 테스트·확장자/크기/개수 검증 테스트·E2E 갱신 그린·시각 실측 | ✅ 완료 (PR #42) — pytest 463(api 234·worker 19·db 103·ai-core 107)·E2E 결정론 12·시각 실측(데스크톱+375px). 목록 응답 첨부 메타 포함 정합 수정 포함 |
| H8-2 | 문서 게시판 전환 | [ADR-0016](adr/0016-document-board-versioned-attachment.md) — 관리자 전용 게시판(제목+본문(설명용)+첨부 1개 필수), `document_versions` 버전 이력(재업로드=version+1+재인제스트, 이력 다운로드만·롤백 없음), `document_chunks`→`content_chunks` 소스 일반화(notice 대비), soft delete+청크 즉시 삭제, 다운로드 API 경유 인가, 기존 데이터 폐기. web-admin 목록·작성·상세/수정·버전 이력 화면 | 인가·격리 테스트(**CRITICAL** — 교차 tenant 404·RESIDENT 거부), 재업로드→재인제스트→벡터 최신화 검증, 게이트 그린(pytest cov 80·vitest·E2E) | ✅ 구현 완료 — pytest 229/17/114/102(cov 95~98%)·vitest 100·build 그린. 실스택 실측: v1 색인→v2 재업로드 시 content_chunks 완전 교체 확인, UI 전 여정(작성 폼·목록·상세/수정·버전 이력·삭제·모바일 375px) 시각 검증. worker role의 청크 DELETE 권한 결함(재색인, superuser 접속에서만 잠복 동작) 교정. 로컬 E2E는 타 세션 dev 서버 포트 점유로 CI 위임 |
| H8-3 | 공지 벡터화 | 공지 본문+파싱 가능 첨부(.pdf/.txt/.md)만 임베딩 → `content_chunks(source_type=notice)`. **published만** 인제스트(발행 시점 인제스트·수정 시 재인제스트·삭제/비공개 시 청크 제거). 공지 첨부 화이트리스트(.hwp 등)는 축소 안 함 | 미발행 공지 검색 미노출(**CRITICAL**) + 발행→검색 반영 검증 | ✅ 완료 (PR #45) — pytest 495(api 252·worker 30·db 106·ai-core 107, 신규 15). CRITICAL은 실 PG 조인 배제 테스트(청크 강제 시드→검색 미노출)로 검증. 마이그레이션 c3d4e5f6a7b8(worker GRANT) |
| H8-4 | 공통 코드 관리 | `code_groups`·`codes` 스키마([03 §4.10](03-database-design.md)) + RLS·마이그레이션(단지 생성 시드+기존 단지 시드) + API 7종([01 §13](01-architecture.md) 설정·코드 관리) + 설정 메뉴(코드 관리 트리 — 그룹 선택→추가·수정·정렬·비활성·삭제) + 기본 코드 시드(NOTICE_CATEGORY·DOC_CATEGORY)([ADR-0017](adr/0017-tenant-code-registry.md)) | 코드 CRUD·순환 방지(parent_id)·is_system 그룹 보호(409)·STAFF 조회 전용 인가 테스트(**CRITICAL** — MANAGER 쓰기·STAFF 읽기 전용·교차 tenant 격리) + 게이트 그린 + 시각 실측 | ✅ 완료 (PR #48) — pytest api 266(cov 95%)·db 110(codes 100%)·vitest 117, 마이그레이션 e5f6a7b8c9d0 라운드트립. 시각 실측(그룹 전환·코드 추가 폼·시스템 그룹 잠금) |
| H8-5 | 설정>동/호수 관리 | 기존 `buildings`·`households` 스키마 재사용(마이그레이션 없음 — `status` 컬럼 기존). 백엔드 `households` 라우터(동 CRUD·세대 목록/일괄 생성·개별 수정/삭제, MANAGER 전용, `/admin/buildings`·`/admin/households`), 세대 층·호 범위 일괄 생성(멱등 — 기존 (층,호) skip)+1회 2000세대 상한. web-admin `/settings/households`(좌 동 목록·우 세대 그리드+일괄 생성 폼(라이브 미리보기)·개별 삭제). 기존 `seed_households_xlsx.py`는 초기 대량 등록용 유지 | **삭제 보호(CRITICAL)**: 세대에 입주민·명부(`users`)·민원(`inquiries`)·관리비(`fees`)·세대기기(`plan_devices`) 연결 시 409·동에 세대 있으면 409 + tenant 격리·인가(STAFF·RESIDENT 403) + 게이트 그린 | ✅ 완료 (PR #49) — pytest api 신규 17(삭제 보호·일괄 생성 멱등·범위 검증·tenant 격리)·vitest 신규 11. 시각 실측(동 목록·세대 그리드·일괄 생성 다이얼로그). #48 머지 후 rebase 정합 |
| H8-6 | 공지·문서 코드 적용 | notices: `+category_code_id` FK(NOTICE_CATEGORY)·`event_start` date NULL·`event_end` date NULL(표시용 행사/작업 기간)·`target_buildings` JSONB NULL(동 id 배열, NULL=전체동, 표시용 — 알림 타게팅 백로그)·`keywords` text NULL(콤마 구분, H8-3 임베딩 텍스트에 포함). documents: `source_type`→`category_code_id` FK(DOC_CATEGORY, NOT NULL) 전환 + 기존 데이터 label 일치 매핑 후 컬럼 drop 마이그레이션. notices.category_code_id는 NULL 허용, FK는 둘 다 RESTRICT — 참조 중 코드 삭제 409. category_code_id는 같은 tenant·해당 그룹 코드만(앱 검증) | 코드 참조 무결성 테스트(RESTRICT 삭제 거부) + 마이그레이션 라벨 매핑 검증 + 키워드 임베딩 반영 + 게이트 그린 | ✅ 완료 (PR #51) — pytest api 295·db 110·worker 31, 마이그레이션 f6a7b8c9d0e1(source_type→code_id label 매핑)·vitest 134·시각 실측(공지 분류/기간/대상동/키워드·문서 DOC_CATEGORY 필수·기존 데이터 매핑) |
| H8-7 | 관리비 고지서 + 검수 큐 제거 | 운영자 요청(2026-07-22): ①입력 엑셀을 세대별 행→**단지 총액 트리**(분류 들여쓰기 depth·`우리단지총액` 1열)로 전환, 파서 `parse_fee_total_xlsx`+분배 `divide_fee_tree`(각 행 독립 `/574` ROUND_HALF_UP·음수 허용, **코드 계산·AI 미개입** 규칙5) ②`Fee.breakdown` flat dict→**순서 보존 트리 리스트**(`[{name,level,amount}]`) ③업로드→분배→**401동 201호 1세대** apply(데모, 재업로드=해당 세대·월 교체) ④admin `/fees` = 동/호별 목록+**동/호·년월 검색**(`GET /admin/fees` building ilike·unit)+**2단 고지서 상세**(`GET /admin/fees/{household_id}`, 사진 스타일·트리·당월 1열·충당금잔액/적립요율 숨김·잡수입 참고행) ⑤주민 `/fees` 트리 렌더 ⑥**AI 검수 큐 완전 제거**(api `review_queue` 라우터·스키마, web-admin `/review-queue` 화면·내비, `messages` 검수 결정 컬럼 drop 마이그레이션 `b2d9e4f7a1c3`, 저신뢰 플래그·confidence 유지 — [ADR-0015](adr/0015-notice-board-replaces-ai-draft.md) 개정 노트) | 분배 순수함수 단위테스트(검산 176,601·음수 -273·household_count 0 예외)·tenant 격리·MANAGER 인가·게이트 그린(pytest cov·vitest·build)·시각 실측 | ✅ 구현 완료 — pytest 291(cov 90%)·vitest(admin 130·resident 105)·build·mypy(app/db/ai-core) 그린. 실스택 실측: migrate+seed 후 `/fees` API 트리 정합(176,601·91행·수도 공용 -273), 주민 고지서 라이브 렌더(트리·필터·합계·잡수입) 시각 검증. seed `_upsert_active_account` **approved_at 미설정→관리비 게이팅** 결함 발견·교정(활성=승인). admin 라이브 렌더는 타 세션 dev 서버 포트 점유(500)·CORS 포트 잠금으로 CI/후속 위임, 컴포넌트 코드·빌드·공유 buildInvoice(주민서 검증)로 확인 |
| H8-9 | 민원 개편(AI 제거·처리 워크플로) | 운영자 요청(2026-07-23, [ADR-0018](adr/0018-inquiry-manual-handling.md)): ①AI 분류 제거(`inquiry_classify.py`·`ai_classified` 생성 삭제) ②카테고리 `inquiry_categories`→코드 `INQUIRY_CATEGORY` 그룹(`category_code_id` composite FK RESTRICT·NULL 허용, 시드 설비/하자·소음·주차·공용부·보안·기타, 입주민 접수 시 선택), `ai_priority`→`priority`(수동 urgent\|normal\|low) 마이그레이션(label 매핑·구 테이블/FK drop) ③배정: 소장→직원·직원 self·직원 재배정(`GET /admin/staff` STAFF 조회 개방) ④답변 `POST /admin/inquiries/{id}/comments`(kind=reply, **담당자만**+소장) ⑤피드백 `POST /inquiries/{id}/comments`(kind=feedback, **작성자·처리중만**) ⑥상태: 처리중=담당자만(+소장), 완료=담당자만(+소장)+**reply≥1 게이트**(422), 소장 역행 오버라이드 유지 ⑦입주민 상세 재디자인(대화형 타임라인·칩·피드백창)·관리자 상세 뷰 신설(담당자 드롭다운·우선순위·상태·답변) | 완료 게이트(reply 없으면 422)·처리중 담당자 한정·피드백 처리중 한정·배정 인가·카테고리 코드 무결성(RESTRICT)·tenant 격리 테스트(**CRITICAL**) + 마이그레이션 라운드트립 + 게이트 그린(pytest cov·vitest·build·mypy) + 시각 실측 | ✅ 완료 — pytest api 300(cov 95.8%)·db 108(cov 98.5%)·vitest(resident 112·admin 140)·typecheck·lint·mypy 그린. 마이그레이션 c4a7e2f1b9d3 실 PG upgrade(기존 단지 INQUIRY_CATEGORY 시드·label 매핑). 라이브 실측(양 앱): 입주민 접수(AI배너 제거·카테고리 select 시드값 로드)·상세 대화 스레드(내 글 우측·관리사무소 답변 좌측·시스템 이벤트 레일)·피드백 게이트(접수됨 비활성→처리중 활성) 및 피드백 전송, 관리자 목록 재디자인(카테고리·수동 우선순위·담당 email)·상세 슬라이드오버·직원 배정 드롭다운·우선순위 지정·**처리중 게이트**(미배정 비활성→배정 활성)·**완료 게이트**(답변 전 비활성→답변 후 활성)·답변 스레드. 콘솔 에러 0. **v2(2026-07-24, 2차 피드백 — ADR-0018 개정 노트)**: 수동 상태 변경 제거→액션 부산물(ack/complete/reopen/category), received=미배정·reopened 추가, 완료 잠금, 담당자 성명(name_enc 복호), 입주민 우선순위 숨김·완료시 "재확인 요청". pytest api 312·resident 113·admin 138 그린. 라이브 실측: 완료 처리→완료 잠금(전 컨트롤 비활성), 담당자 성명 표기·카테고리 편집 select, 입주민 재확인→피드백 재활성. **후속(2026-07-24)**: 직원 초대 이름 입력(InviteStaffIn email+name→name_enc)+기존 직원 backfill 스크립트·직원 관리/민원 담당 성명 표기, 접수폼 사진 placeholder 제거, 입주민 나 알림 최근4+더보기→`/notifications` 전체 페이지·알림 개별 삭제(`DELETE /notifications/{id}`). pytest api 316·resident 118·admin 138 그린. 라이브 실측 전부 통과(사진 제거·알림 삭제·성명) |
| H8-10 | 관리자 콘솔 정리(메뉴·대시보드) | 운영자 요청(2026-07-24): ①사이드바 flat 10개→**섹션 그룹화** — 대시보드·공지사항 단독 + 입주민 관리(주민/관리비/민원)·관리소 운영(직원/문서/시설)·설정(동호수/코드). STAFF·SYS_ADMIN은 flat 유지(`roles.ts` NavItem[]→NavGroup[]). 대메뉴 헤더 가시성 — 한글 무효 uppercase 제거·블루 액센트 바·구분선 ②대시보드 개편: **검수 필요율 KPI 제거**(사후 검수 큐 H8-7 폐지로 stale, `needs_review_rate` 스키마·집계·프런트·api-types drop), **오늘 할 일 액션 큐**(`ActionQueueStats` 기간 무관 open 카운트 — 승인 대기·미배정/처리중 민원·임시저장/예약 공지, tenant+deleted_at 필터, 담당 화면 딥링크), 위계 재구성(액션 히어로→민원/시설→AI 도우미 sunken 강등) ③카드 색 체계: 액션 카드 카테고리 tone(상단 스트립+아이콘 칩)·데이터 카드 테두리 tone 틴트·기간 세그먼트 컨트롤(디자인 토큰만) ④문서 관리 검색 개편: 자동검색(debounce) 제거→**검색 버튼+Enter**(한글 IME 조합 중 자동검색이 자모로 필터돼 제목 검색 오작동하던 버그 수정)·분류(DOC_CATEGORY) select 검색 조건 추가·요약카드 대시보드 액션카드 스타일 통일·목록 헤더 강조(전량 로드 클라 필터) | 액션 큐 카운트 tenant 격리(**CRITICAL**)·MANAGER 인가·게이트 그린(pytest·vitest·build·api-types drift) + 시각 실측(라이트·모바일) | ✅ 완료 — pytest test_dashboard 10·vitest admin 139·typecheck·lint·build 그린, api-types 재생성(needs_review_rate 제거·actions 추가). 라이브 실측(1280·375px): 메뉴 그룹 헤더 액센트 바 구분·액션 큐 승인 대기 1 강조·카드 tone 색 전면 적용·콘솔 에러 0 |
| H8-8 | 입주민 프로필·나 개편 | 운영자 요청(2026-07-22): ①`GET /me`에 `display_name`·`unit_label` 추가 — 본인 세션 소유 pii_vault 복호(`crypto.decrypt`)+household·building 조인, `app.tenant_id` 격리(규칙 2·3, 타인 PII 아님·복호 실패 None 흡수·500 금지) ②홈 인사 "안녕하세요, {실명}님 ({동}동 {호}호)"(`greeting` 순수 헬퍼) ③나 헤더 `roleLabel`→실명+동/호 ④나 **설정 섹션 통째 제거**(AI추천·다크·언어·알림수신 토글, 알림함·개인정보·로그아웃 유지) ⑤마스킹 안내 '타인 정보' 한정으로 수정 ⑥나 **관리비 요약 카드**(당월 합계+`/fees` 자세히→) | 본인 실명 노출·미배정 폴백 단위테스트 + tenant 격리 + 게이트 그린(@liviq/ui 토큰 포함) + 시각 실측 | ✅ 완료 — pytest 293(cov 95.8%)·@liviq/ui 16·vitest(resident 109·admin 130)·build·mypy 그린. 라이브 실측: /me 반환(display_name=최주민·unit_label=401동 201호), 홈 인사·나 헤더·설정 제거·관리비 카드(176,601원·/fees 링크)·마스킹 문구 시각 검증. PII 복호는 본인 user_id+tenant_id 소유 vault만 |

### 8.11 H9 체크리스트 (단지 3D 트윈 · 주차장)

> 근거: 사용자 인터뷰 확정(2026-07-24, [ADR-0019](adr/0019-complex-twin-3d.md)) — 프로토타입(AI_digitaltwin_apartment repo)의
> 세대 3D geometry를 제품 기능 "단지 트윈"으로 흡수. **범용 설계**(geometry 있는 tenant만 활성) + deck.gl 3D 직행(2D 그리드 없음).
> **데이터 현황**: 파일럿 tenant = 첫마을 4단지 — `buildings`(401~405동)·`households`(322세대)는 H7-7,
> 명부 892건(페르소나 유래)은 H7-9로 **기존재**. 신규 적재는 geometry(units.json)뿐. 세대원·입주 상태는 기존 명부가 원천(신규 명부 테이블 없음).
> 근거 설계: [00 §3.8](00-requirements.md) FR-TWIN-07~10 · [01 §13](01-architecture.md) 단지 트윈 표 · [03 §4.8](03-database-design.md) `household_geometries` · [04](04-menu-structure.md) 메뉴 · [05 §5·§7](05-ui-ux-design.md) · [11 §3.4.1](11-data-architecture.md).
> 각 작업 단위는 §3.1 사이클을 따르고, 머지는 단위별 사용자 확인 후 진행.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H9-0 | 설계 갱신 | 00 §3.8(FR-TWIN-07~10)·01 §13(트윈 표+`/me` has_twin)·03 §2 ERD·§4.8·§7·04(메뉴·매트릭스·여정)·05(§5 트윈 UX·§7 번들 예외)·11 §3.4.1 + [ADR-0019](adr/0019-complex-twin-3d.md) 신설 | 설계 문서 PR 머지(구현 착수 전) | ✅ 완료 (PR #60) |
| H9-1 | 데이터 계층 + 3D 뷰 + 입주 오버레이 | `household_geometries` 마이그레이션(+표준 RLS — Alembic custom) · `POST/GET /admin/twin/geometry`(units.json 파싱·Pydantic 검증·동층호 매칭 검증 리포트·전체 교체) · `GET /admin/twin/overlay?kind=occupancy`(명부 인원 집계) · `GET /me`에 `has_twin` · web-admin `/twin`(deck.gl dynamic import — 3D 폴리곤·occupancy tint·범례·빈 상태) + 사이드바 '관리소 운영' 그룹에 조건 노출 · 첫마을 units.json 실업로드(운영 절차 — 322세대 matched 확인) | tenant 격리·MANAGER 인가 테스트(**CRITICAL**) + 매칭 검증 리포트(unmatched 스킵·리포트 반환) 테스트 + 재업로드 전체 교체 멱등 테스트 + 게이트 그린(pytest cov·vitest·build·api-types drift) + 시각 실측(1280·375px) | ✅ 완료 (PR #61) — pytest api 328(cov 95.9%)·db 113·vitest 152·마이그레이션 a9b1c2d3e4f5. 라이브 실측(래미안 한강 1단지): units.json 실업로드 322/322 매칭·미매칭 0, /twin 3D 렌더(5개 동·occupancy 색·범례·hover)·조건 노출 라운드트립·업로드 패널·콘솔 0·모바일 375px. deck.gl 9.3.7 dynamic ssr:false 격리(/twin First Load 113kB) |
| H9-2 | 오버레이 3종 + 세대 상세 패널 | `overlay` kind 확장 — inquiries(미종결, author→household 경유)·fees(당월 부과액 밴드)·facilities(**동 단위** — location≈동명 매칭 최악 상태) · `GET /admin/twin/households/{id}` 세대 상세(세대 정보·세대원 명부 **마스킹**·미종결 민원 목록·당월 관리비) · 폴리곤 클릭→상세 패널·오버레이 세그먼트 토글·범례 · 관리비 오버레이 재료: H8-7 apply의 1세대 데모 한정을 **전 세대 적용**으로 전환 | 소유권·tenant 격리 테스트(**CRITICAL** — 타 tenant 세대 상세 404) + 오버레이 집계 정합 테스트 + fees 전 세대 apply 회귀(기존 테스트 갱신) + 게이트 그린 + 시각 실측 | ✅ 완료 (PR #62) — pytest api 335(cov 95.8%)·vitest 160·overlay kind별 헬퍼 분리(OverlayOut 계약 불변). 관리비 apply 전 세대 전환(_target_household 제거·applied=세대수). 라이브 실측: 입주/민원/설비 오버레이 토글·범례 전환, 폴리곤 클릭→세대 상세 슬라이드오버(세대원 마스킹 김\*희·미종결 민원·당월 관리비)·콘솔 0. fees 오버레이는 균등분배라 부과/미부과 2단(전용 항목 분리 시 밴드 유효) |

| H9-3 | 실사 3D(VWorld) 뷰 토글 | ([ADR-0019](adr/0019-complex-twin-3d.md) 개정) 설계 갱신(00 FR-TWIN-11·05 실사 UX·06 CSP·본 표) → env·스캐폴드 배선(`NEXT_PUBLIC_VWORLD_API_KEY` 관례 읽기·`/twin` 뷰 토글·VWorldView 키 미설정 빈 상태·dynamic import 격리) → Cesium 실사 뷰 포팅(프로토타입 `dashboard_vworld.html` 로직을 LIVIQ 트윈 API(`geometry`·`overlay`·`households/{id}`)로 재배선한 세대 shell Primitive·오버레이 색·클리핑·`document.write`→동적 `<script>` append) | 키 미설정 시 기본 뷰 정상+실사 뷰 안내 · 라이브(키 등록 후 `localhost:3001`) 실사 3D 렌더·세대 오버레이·토글·콘솔 0·CSP 위반 0 · 게이트 그린(typecheck·lint·build — deck.gl+Cesium 격리) | ✅ 완료 (PR #64 배선 · PR #65 Cesium 포팅) — 라이브 검증 성공(첫마을 4단지 푸르지오/세종 한솔동). **핵심 발견**: VWorld SDK가 키 검증 후 `document.write`로 Cesium 엔진 주입 → SPA 동적 스크립트 로드에선 무시됨 → **iframe srcdoc 호스팅**으로 전환(문서 파싱 중 로드, 부모=색·React·iframe=순수 렌더, postMessage 브리지). **우리 단지만 표시**(운영자 요청): VWorld 3D 건물 타일셋을 세대 볼록껍질 ClippingPlaneCollection로 클립 + POI 라벨 폴링 숨김. 실측: 실사 위성 위 우리 5개 동만 3D·입주 shell·recolor·클릭 상세·콘솔 0. 지반고 샘플링·hover 하이라이트는 후속 TODO. **키**: `NEXT_PUBLIC_VWORLD_API_KEY`(도메인 잠금, `.env.local`)·서비스 URL `http://localhost:3001` 등록(스킴 필수) |

| H9-4 | 트윈 대시보드 개편 | 메뉴 개편(**"단지 트윈"→"트윈 대시보드"**, 대시보드 바로 아래 같은 레벨·hasTwin 게이트 유지) · 현황 패널(타일 4종: 총세대·입주율·미처리민원·설비이상 + 최근민원 6건 + 설비상태 목록 — `listAdminInquiries`·`listFacilities` 재사용, 총세대·입주율은 트윈 geometry/occupancy 파생, 신규 API 0) · **실사 3D 전용 컨트롤**(보기모드 오버레이 4종 + 렌더 스타일 쉘/포인트/끄기 + 시점 단지고정/360°회전 + 렌더링 우리단지만 clip 토글) · **실사 3D 오버레이 가독성 수정**(프로토타입 PointPrimitiveCollection 이식 — 반투명 쉘(α0.22)로 안 보이던 입주/민원/관리비를 포인트 도트로 식별) · postMessage 계약 확장(style·camera·clip) | 게이트 그린(typecheck·lint·vitest·build) + roles 테스트(메뉴 위치) + 라이브 실측(실사 3D 오버레이 4종·포인트·시점·clip·콘솔 0) | ✅ 완료 (PR #66) — 게이트 그린(typecheck·lint·vitest 166·build, /twin First Load 117kB). 라이브 실측(첫마을 4단지 푸르지오/세종 한솔동): 메뉴 이동(트윈 대시보드가 대시보드 바로 아래)·현황 패널(타일 총세대 322·입주율 100%·미처리민원 1·설비이상 0 + 최근민원 + 설비상태, 실데이터)·기본 3D deck.gl·실사 3D 오버레이 4종 recolor(민원=미처리 1건이 주황 도트로 식별, 관리비=부과/미부과 밴드)·**포인트 스타일로 반투명 쉘에서 안 보이던 오버레이 가독성 확보**·시점(단지고정/360°회전, 회전이 고정 함의)·우리단지만 clip·세대 클릭→상세(세대원 마스킹 김\*호 등)·콘솔 0 |

| H9-5 | 주차장 대시보드 (지도 이식) | **참조**: `AI_digitaltwin_apartment` 프로토타입 `/parking`(관리자용 2D 지하주차장 배치도) — 트윈 VWorld 이식과 동형. **관리자 지도만**(입주민 도우미 `/parking/resident`는 백로그). `parking_layouts`(tenant 1행·layout JSONB — viewBox·동 footprint(shp 유래)·박스·442면 spots{no,kind(일반/장애인/전기차),x,y,dir}) + `parking_vehicles`(tenant·household FK·**plate_enc**(bytea, PiiCrypto)·model·is_ev — 348대) 마이그레이션(표준 RLS ENABLE+FORCE·`liviq_app` GRANT) · **점유 = 시뮬레이션**(`simulateParking` 시드 20260725 고정·재실률 75%·자기동 선호·외부 8대 — ★ 추후 번호판 카메라 API 교체 · **H15-4에서 PG `parking_occupancy` 영속화로 대체, [ADR-0023](adr/0023-parking-occupancy-persisted.md)**) · `GET /admin/parking/layout`(레이아웃) + `GET /admin/parking/vehicles`(**MANAGER** · plate 복호) · 시드 스크립트(레이아웃 JSON + 348대 → households (동,호) 매핑·plate 암호화·매칭 리포트) · web-admin `/parking`(레이아웃+차량 fetch → 클라 시뮬 → **SVG 배치도** React 렌더 · 현황 카드(전체/주차/입주민/외부/빈자리) · 동별 칩(401~405동·외부 필터) · 입주민 파랑/외부 주황 · 면 클릭→동/호 or 외부 번호판·경과 · 목록 보기 표(필터·행→포커스)) · 메뉴 "주차장 대시보드"(🅿️ 트윈 대시보드 바로 아래·MANAGER 항상 노출) · `roles.ts` NavItem·`lib/api.ts` 함수 · **차량번호 개인정보(규칙 2)**: at-rest 암호화·관리자 세션에만 복호 노출·LLM 미노출 · 설계: [03 §4.11](03-database-design.md)·[11 §3.4.2](11-data-architecture.md)·[06 §4.1](06-security-privacy.md) | tenant 격리·MANAGER 인가(**CRITICAL**) + plate 암호화 왕복(DB 암호문·복호 원문) + 시드 매핑 리포트(matched/unmatched) + 레이아웃 442면·kind 집계 + 시뮬 결정성(시드 고정 재현) 테스트 + 게이트 그린(pytest cov·vitest·build·api-types drift) + 시각 실측(프로토타입 대조·1280·375px) | ✅ 완료 — 마이그레이션 `d3e4f5a6b7c8`(단일 head, 테이블 36→38). 게이트: pytest api 343(cov 95.74%)·db 126(cov 98.62%)·vitest 184·typecheck·lint·ruff·mypy·build 그린(`/parking` First Load 113kB)·api-types 재생성. 시드 실행: 442면(일반 406·장애인 15·전기차 21)·차량 348대 **전량 매칭(미매칭 0)**·274세대·EV 29. 라이브 실측(첫마을 4단지 푸르지오, MANAGER): 배치도 442면 렌더·현황 카드 **442/264/256/8/178**·동별 401동 53·402동 45·403동 48·404동 59·405동 51 + 외부 8 — **프로토타입 원본 수치와 완전 일치**. 면 클릭 안내(입주민면=동/호·차종·경과, 외부면="등록 차량 아님"+경과)·목록 264행↔지도 양방향 선택 연동·콘솔 에러 0·1600·1440·375px(body 오버플로 0). **운영자 요청 후속(2026-07-25)**: ①배치도 **전체 표시**(SVG minWidth 제거 — 컨테이너 폭에 맞춰 비율 축소, 가로 스크롤 없음) ②**줌 컨트롤**(1×전체/1.5/2/3× + '전체 보기') ③확대 상태 이동은 **드래그 팬**(pointer 이벤트로 스크롤 오프셋 이동·grab 커서·스크롤바 숨김·4px 임계 초과 시 면 선택 억제·`overflow:auto` 유지해 방향키 이동 보장) ④목록 토글 시 **지도 옆 2열**(≤1100px는 아래로) — 지도는 남은 폭에 맞춰 축소. 이 과정에서 버그 2건 수정: 전역 `svg{max-width:100%}`가 확대 배율을 잘라냄(줌 상태에서만 해제), 선택 면 포커스 이동의 `behavior:"smooth"`가 조용히 무시돼 이동 실패(→`auto` 고정). DB 실측: `plate_enc` 38B 암호문·실번호판 평문 0건·348개 전부 유니크 nonce(조회에 RLS 컨텍스트 필요). **중요 이력**: 최초 "세대별 주차 배정 표"(`parking_assignments`+CRUD, fbd7b00)로 구현했다가 참조 프로토타입 대조 후 **폐기** — 지도 이식으로 재설계(d630dc7 설계 정정 → 998b405 백엔드 교체). **의도적 제외**: 입주민 주차 도우미(`/parking/resident`) 백로그, 프로토타입 '🔄 점유 재배치' 버튼·`?list=1` 미이식, 외부 차량 램프 선호를 면 좌표로 근사(레이아웃 `boxes` 미전달 — 외부 8대가 앉는 **면**은 프로토타입과 다를 수 있음. 대수·입주민 배정 256면은 동일), `meters`/`PX_TO_M`은 이식했으나 관리자 화면 미사용(입주민 도우미용 export 유지) |
| H9-6 | 평면도 타입 표시 · 명부 차량 | **운영자 요청(2026-07-25)**: ①동/호수 관리 호수 옆 평면도 타입 ②주민 명부에 소유 차량 번호. 인터뷰 확정 — 차량은 `parking_vehicles` **단일 정본·조회 전용**(명부 엑셀 양식 불변, 입력은 추후 카메라 API/차량 등록), 관리자 화면 **복호 평문**(입주민 앱·LLM 미노출 — 규칙 2). 평면도 타입은 최초 `unit_types` 마스터+FK CRUD로 구현했다가 **과설계로 폐기**하고 **표시 전용**으로 축소 — 트윈 `household_geometries.unit_type_label`(units.json 업로드 산물, 84M 208·59C 114)을 세대 목록에서 1:1 outerjoin해 `201호(84M)`로 표시만 한다(마스터 테이블·수동 지정·승격 스크립트 없음, 갱신은 units.json 재업로드). 마이그레이션 없음 | 세대 목록 라벨 노출·기하 없는 세대 None + 명부 차량 복호 노출·미보유 빈 배열(**CRITICAL** — tenant 격리·MANAGER 인가) + unitLabel 접미사 + 게이트 그린 | ✅ 완료 — 마이그레이션 없음(기존 컬럼만 사용). 게이트: pytest api 345(cov 95.70%)·mypy·ruff·vitest 188·typecheck·lint·build 그린. 라이브 실측(첫마을 4단지 푸르지오, MANAGER): 동/호수 관리 세대 셀 `201호(84M)` 정상(401동 69세대)·주민 명부 50행 중 46행 차량 번호·4행 `—`·콘솔 에러 0·1280·375px 오버플로 0. 실측에서 잡은 결함 2건: ①`listRoster` 응답 매핑에 `vehicles` 누락(게이트는 통과했으나 화면 런타임 오류) ②트윈 라벨 실데이터가 `84M(공공임대)`라 괄호 중첩·셀 3줄 깨짐 → 부가설명 제거(`unitTypeCode`)·그리드 최소폭 150→190px. **폐기 이력**: 최초 `unit_types` 마스터+FK CRUD(백엔드 라우터 4종·설정 패널·세대 지정 폼·승격 스크립트)로 구현해 게이트까지 통과했으나 운영자 판단("표시만 하면 된다")으로 전량 폐기 — 트윈 라벨 표시 전용으로 축소 |
| H9-7 | 실사 3D 카메라 컨트롤 (확대·축소·현위치) | **운영자 요청(2026-07-25)**: 실사 3D에서 확대·축소·현위치가 동작하지 않음. **라이브 진단으로 원인 확정** — VWorld 네비게이션 위젯 버튼(`.dt-api-map--tool-bt-plus`·`-minus`·`-current`·`-max`)은 전부 `camera.flyTo`(애니메이션 tween) 기반인데, **우리 iframe 임베드에서는 tween이 시작조차 되지 않는다**(`startTime: undefined` · 유휴 시 렌더 0프레임/초 · `requestRender()` 강제에도 카메라 0mm). 비행이 시작되며 Cesium 규약대로 `screenSpaceCameraController.enableInputs=false`로 끄는데 완료 콜백이 영영 안 돌아 **입력이 영구 비활성** → 버튼뿐 아니라 휠·드래그까지 마비되고, 이후 클릭은 cesium-navigation의 `if(!enableInputs) return` 가드에 전부 막힌다. 반면 **직접 대입(`setView`·`lookAt`)은 정상**(우리 프레이밍 코드가 쓰는 방식 — 실측 370m→228m 이동 성공). 따라서 **위젯 버튼은 살릴 수 없고 우리 컨트롤로 대체**한다: ①iframe에 `zoom`·`home` postMessage 명령 추가(궤도 거리 `range`를 직접 대입 — 단지 고정을 유지한 채 확대·축소하므로 단지가 항상 화면 중앙) ②현위치=**단지 초기 시점 복귀**(GPS 아님) ③줌 하한 **150m**(그 이하는 VWorld 실사 건물 타일이 저해상 지형으로 바뀜 — 실측)·상한은 단지 궤도 거리 기준 ④유령 비행 정리(`cancelFlight()` + `enableInputs=true`)로 휠·드래그 복구 ⑤죽은 VWorld 버튼 4종 CSS 숨김(나침반·측정 도구는 유지) ⑥컨트롤 UI는 부모 React(LIVIQ 토큰 — iframe은 렌더 전용 유지) | 순수 로직 단위 테스트(줌 배율·150m 하한 클램프) + 게이트 그린(typecheck·lint·vitest·build) + 라이브 실측(확대·축소·현위치 동작·휠/드래그 복구·단지 중앙 유지·콘솔 0) | 🚧 진행 중 |

> **백로그(수요 확인 후)**: 페르소나 부가정보 — ~~차량~~(**H9-5 주차장 대시보드로 채택**, 2026-07-25)·관계·직업(세대원 확장 테이블 별도 설계) · 트윈 집계 AI 읽기 도구(동/단지 통계만 — 개인 단위 금지, 규칙 2) · ~~VWorld 실사 3D~~(**H9-3로 채택**, 2026-07-24) · 설비-세대 정식 매핑 · 대시보드 액션 큐↔트윈 딥링크 · hover 하이라이트·지반고 샘플링 · **입주민 주차 도우미**(`/parking/resident` — "내 차 어디?"·"빈자리 어디?" 자연어 2종 — "빈자리"는 **H15-4 최근접 빈자리 도구로 채택**, 나머지 백로그 유지) · ~~주차 점유 실데이터화~~(**H15-4에서 PG 영속화로 채택**, ADR-0023 — 카메라 API는 여전히 추후 적재 경로 교체점).

### 8.12 운영 절차: VWorld API 키 발급·등록 (H9-3)

실사 3D 뷰는 국토부 VWorld 지도([ADR-0019](adr/0019-complex-twin-3d.md) 개정)를 쓴다. 키는 **서비스 URL 도메인 잠금**:

1. <https://www.vworld.kr> → 오픈API → **인증키 발급/관리**. 활용 API에 **3D 지도(WebGL)** 포함(2D 배경 필요 시 지도 API 3.0도).
2. **서비스 URL 등록**: dev = `http://localhost:3001`(web-admin 오리진 — 트윈 화면이 여기서 로드). 운영은 배포 도메인 추가 등록(또는 별도 키). VWorld가 포트 포함을 거부하면 `localhost`로 등록.
3. 발급 키를 **`.env` 또는 `apps/web-admin/.env.local`**(gitignore)에 `NEXT_PUBLIC_VWORLD_API_KEY=<키>`. `.env.example`엔 **placeholder만**(도메인 잠금 반공개라도 실키 커밋 금지).
4. 미설정이어도 기본 deck.gl 뷰는 정상 — 실사 뷰만 "키 미설정" 안내.

### 8.13 H10 체크리스트 (컨테이너 배포 — 이미지·3-tier VM)

> 근거: 사용자 결정(2026-07-26, [ADR-0020](adr/0020-container-deploy-3tier-vm.md)) — 앱 4종(`api`·`ai-worker`·`web-resident`·`web-admin`)을 컨테이너 이미지로 GHCR에 게시하고 **3-tier VM(web/app/data)** 에 `infra/compose.prod.yml` 단일 파일 + compose profiles(`data`/`app`/`web`)로 배포한다.
> **로컬 개발 루프는 네이티브 유지**(HMR·reload 속도) — 컨테이너는 **배포 전 스모크**(1호스트 3프로필 동시 기동 = 배포 형상 그대로)와 운영 배포용(§2).
> **LLM은 컨테이너 밖 외부 엔드포인트**를 env로만 가리킨다([ADR-0005](adr/0005-single-llm-openai-compat.md) 유지 — 모델 서빙은 배포 대상이 아님).
> 근거 설계: [01 §14](01-architecture.md)(배포 토폴로지) · [02 §2·§9](02-directory-structure.md) · [06 §6.1·§7·§9](06-security-privacy.md) · 본 문서 §2·§2.1·§4·§4.3.
> 각 작업 단위는 §3.1 사이클(설계 갱신 → 구현 → 현행화 → PR)을 따르고, 머지는 단위별 사용자 확인 후 진행.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H10-0 | 설계 갱신 | [ADR-0020](adr/0020-container-deploy-3tier-vm.md) 신설 + [01 §14](01-architecture.md) 배포 토폴로지 + [02 §2·§9](02-directory-structure.md) + [06 §6.1·§7·§9](06-security-privacy.md) + 본 문서 §2·§2.1·§4·§4.3·§8 단계 표·§8.13 | 설계 문서 PR 머지(구현 착수 전) | ✅ 완료 (PR #78) |
| H10-1 | 이미지 + 로컬 전체 스택 스모크 | [`apps/api/Dockerfile`](../apps/api/Dockerfile)·[`apps/ai-worker/Dockerfile`](../apps/ai-worker/Dockerfile)(uv multi-stage — 빌더 `ghcr.io/astral-sh/uv:0.11.14-python3.12-trixie-slim` → 런타임 `python:3.12-slim-trixie` · `uv sync --frozen --no-dev --no-editable --package <멤버명>` 2단계(`--no-install-workspace` 선행) · 런타임은 `.venv`만 · non-root uid/gid 10001 · **런타임 apt 패키지 0개**(asyncpg·cryptography·argon2-cffi·uvicorn[standard] 전부 manylinux wheel) · Alembic 자산(`packages/db/alembic`·`alembic.ini`)·`bootstrap_sys_admin.py` 명시 복사 · api만 HEALTHCHECK(`/health` — slim에 curl 없어 venv python `urllib`)) · [`apps/web-resident/Dockerfile`](../apps/web-resident/Dockerfile)·[`apps/web-admin/Dockerfile`](../apps/web-admin/Dockerfile)(`node:20.20.1-alpine3.22` + pnpm, Next standalone 산출물만·`node` 사용자·`HOSTNAME=0.0.0.0`) · 두 `next.config.mjs`에 `output: 'standalone'` 추가 · 루트 [`.dockerignore`](../.dockerignore) · [`infra/compose.prod.yml`](../infra/compose.prod.yml)(profiles `data`/`app`/`web` + one-shot `migrate` + `healthcheck`·`depends_on` · 인프라 5종 고정 태그 핀(§2.1) · 호스트 포트 env화 · tier 간 `depends_on: required: false`) · [`infra/Caddyfile`](../infra/Caddyfile)(2사이트 · `/api` `strip_prefix` 프록시 · SSE `flush_interval -1` · 보안 헤더 일괄) · [`infra/env.prod.example`](../infra/env.prod.example) 운영 env 계약 · `NEXT_PUBLIC_API_BASE_URL=/api` 전환(빌드 인자) · `.gitignore`에 `infra/env.prod` | 로컬 1호스트 3프로필 전체 기동 → 전 여정 스모크(로그인 → 단지 → AI 질의 **SSE 스트리밍 실확인** → 트윈 → 주차장) · 브라우저 콘솔 에러 0 · 기존 게이트 그린(typecheck·lint·test·build) · **api 컨테이너가 퍼블릭 바인드 아님 확인** | ✅ 완료 — 게이트: `ruff format --check` 166 files·lint 7/7·typecheck 8/8(mypy 포함)·test 7/7(api **345 passed, cov 95.70%**)·build 2/2 그린(TS prettier는 프로젝트 미설정 — `ci.yml` format 단계 TODO대로 format 게이트는 ruff만). 이미지 크기 api 417MB·ai-worker 353MB·web-resident 301MB·web-admin 303MB. **1호스트 3프로필 동시 기동 실측**: 9/9 up, data 4종 healthy, `minio-init` exit 0(버킷 생성), `migrate`(head `d3e4f5a6b7c8`) 완료 후 api·ai-worker → caddy 순서 강제 동작. **퍼블릭 노출면 1개 확인**: api `127.0.0.1:18000`·postgres `127.0.0.1:15433`·redis `127.0.0.1:16379`·minio `127.0.0.1:19000/19001`·neo4j `127.0.0.1:17687`, 웹 2종 호스트 퍼블리시 0, caddy만 `0.0.0.0:8080/8443`. **온보딩 전 여정**(프록시 경유 `/api`): 이미지 내 스크립트로 SYS_ADMIN 부트스트랩 → 임시 비밀번호 변경 204 → 단지 생성 201 → 소장 초대 202(**초대 메일 링크가 프록시 경유 퍼블릭 URL** `http://admin.localhost:8080/invite?token=…`) → 수락 204 → MANAGER 로그인 200 → `/api/me` `roles:["MANAGER"]`·`tenant_name:"스모크 단지"`. 세션 쿠키 `liviq_session; HttpOnly; SameSite=lax; Path=/`(Secure 없음 — `API_ENV=local` HTTP 스모크 의도), same-origin 프록시라 CORS 0. **문서 업로드→인제스트**: 업로드 201 → ai-worker `ingest_document_task` → `{'status':'indexed','chunks':3}` → `content_chunks` 3행 embedding 전부 채움(bge-m3, 외부 엔드포인트 `host.docker.internal`) → 화면 "색인 완료 v1". **AI 질의 SSE(핵심)**: `status(searching)`→`status(generating)`→**token 30개가 4.47~5.36s에 20~50ms 간격 점진 도착**→`status(verifying)`→`citation`→`done{status:"answered"}` — 버퍼링이면 30개가 `done` 시점에 몰렸을 것이므로 `flush_interval -1` **확증**. 근거 없는 질의는 `done{status:"fallback",fallback_reason:"no_evidence"}`로 규칙 1 폴백 정상. **브라우저 실측**(Caddy 경유): admin 로그인·대시보드(실데이터 — AI 질의 4건·답변률 25%·폴백률 75%가 위 SSE와 일치)·문서 관리·주차장 대시보드, resident 로그인. 콘솔 에러 0·전 `/api` 요청 same-origin 200·`has_twin=false`로 트윈 메뉴 정상 숨김·375px body 오버플로 0. 정리: `down -v`로 컨테이너·볼륨 0, 개발 인프라 볼륨(`infra_*`) 무손상. **설계와 달라진 것**: ①uv 공식 이미지 bookworm 변형이 0.9.30에서 단절 → **trixie 전환**(빌더·런타임 Debian 릴리스 일치 필요 — `.venv`의 glibc wheel) ②`uv sync --no-editable` 필수(editable이면 `.venv`가 빌더 소스 경로를 가리켜 런타임 import 붕괴 → 런타임에 앱 소스 미복사) ③**호스트 포트 env화**(`POSTGRES_PORT`·`REDIS_PORT`·`MINIO_PORT`·`MINIO_CONSOLE_PORT`·`NEO4J_BOLT_PORT`·`API_PORT`) — 스모크 호스트의 네이티브 postgres가 5432를 선점해 실제로 충돌 ④tier 간 `depends_on: required: false`(없으면 `--profile app up`이 다른 VM의 postgres를 기다리거나 app VM에 로컬 postgres를 띄운다. 같은 tier 내 `migrate → api`·`minio → minio-init`은 `required: true` 유지) ⑤neo4j 힙 상한 env 추가(`NEO4J_server_memory_heap_max__size` 등, 기본 512m — Neo4j 5 규약 `.`→`_`, `_`→`__`) ⑥`.gitignore`에 `infra/env.prod` 추가(점 없는 이름이라 기존 `.env.*` 패턴에 안 걸려 시크릿 커밋 위험). **의도적 제외**: 운영 이미지에 seed 스크립트 미포함(bootstrap_sys_admin.py만 — §4.3) · **CSP 미적용**(VWorld Cesium 예외 정리 후 별도 작업 — [`infra/Caddyfile`](../infra/Caddyfile) 주석에 근거. 적용 헤더는 HSTS·nosniff·X-Frame-Options DENY·Referrer-Policy·Permissions-Policy + `Server` 제거) · ai-worker·웹 2종 HEALTHCHECK 없음(찍을 엔드포인트 없음). **데이터 기반 화면 추가 검증(2026-07-26, 미검증 ① 해소)**: 프로토타입 레포의 `units.json`·`첫마을4단지_호수별_페르소나반영_322세대_정리.xlsx`(둘 다 VCS 밖 — 경로는 [ADR-0019](adr/0019-complex-twin-3d.md) 참조 프로토타입)를 **배포 이미지 스택에 적재**해 실측. 적재는 시드 스크립트를 `run --rm`에 bind mount(이미지 미오염): 동 5개·세대 322 · geometry `matched 322/unmatched 0` · 주차 442면(일반 406·전기차 21·장애인 15)·차량 348 전량 매칭 — 전부 §8.11 H9-1·H9-5 기록과 일치. 화면: `/me` `has_twin:true`로 트윈 메뉴 노출, 트윈 3D 5개 동 렌더(375px에서도 canvas 정상), 세대 클릭 → 상세 `403동 1202호 · 12층 · 59C(공공임대)`(H9-6 평면도 타입 라벨 포함), 주차 현황 카드 **442/264/256/8/178** + 동별 401동 53·402동 45·403동 48·404동 59·405동 51 + 외부 8 — **H9-5 실측 수치와 완전 동일**. 면 클릭 → `002면 — 401동 1603호 · 투싼(142구2049) · 5시간 21분 경과`(번호판 복호가 관리자 세션에서만). DB 실측: `plate_enc` 348행 전부 38B 유니크 암호문·평문 번호판 0건 → **배포 이미지에서도 규칙 2 암호화 왕복 정상**. 콘솔 에러 0·1280·375px 오버플로 0. **부분 검증**: 입주 오버레이는 세대원 명부를 시드하지 않아 전부 공실(입주율 0%) — 범례·토글은 동작하나 **색 구분 자체는 미검증**. **미검증(잔여)**: ①`X-Frame-Options: DENY`와 web-admin 트윈 VWorld **iframe srcdoc 공존** — **스모크에서 구조적으로 검증 불가**: VWorld 프론트 키는 서비스 URL 도메인 잠금(§8.12)이라 `admin.localhost:8080` 오리진에서 거부되고, 키도 `apps/web-admin/.env.local`에 있어 이미지 빌드 인자로 넣을 수 없다 → **실배포 도메인을 VWorld에 등록한 뒤** 확인(H10-3) ②**GHCR 게시·sha 태그 롤백 실연** — 레지스트리 미연결(H10-3). **함께 발견한 CRITICAL**: 런타임이 RLS 우회 롤로 접속(owner=superuser+BYPASSRLS) → 별도 작업 단위 **H10-2에서 해소**(아래 행) |
| H10-2 | 런타임 DB 접속 롤 분리 (RLS 이중 방어 2층 활성화) | 마이그레이션(`liviq_app`·`liviq_worker` LOGIN 전환 준비 + **누락 GRANT 보강** — `tenants` INSERT·UPDATE(단지 생성·상태 전환이 owner 접속에 가려 있었다)) · `packages/db` 수렴 스크립트 `python -m liviq_db.runtime_roles`(env의 `APP_DATABASE_URL`·`WORKER_DATABASE_URL`에서 비밀번호 파싱 → `ALTER ROLE … LOGIN PASSWORD` 멱등 적용 + **롤 속성 검증**(`rolsuper`·`rolbypassrls` 부재)·**컨텍스트 없는 조회 0행 프로브** → 어긋나면 비영점 종료로 배포 중단) · [`infra/compose.prod.yml`](../infra/compose.prod.yml)(`migrate`가 `alembic upgrade head` 후 수렴 스크립트 실행 · api·ai-worker의 `DATABASE_URL`을 런타임 URL로 **서비스별 오버라이드**) · [`infra/env.prod.example`](../infra/env.prod.example) 3-URL 계약 + H10-1에 남긴 ★경고 블록 해소 · 실접속 롤 격리 테스트(owner + `SET LOCAL ROLE` 경로만이 아니라 **`liviq_app`·`liviq_worker` 실접속 세션**으로 재확인) · 설계: [03 §5.1](03-database-design.md)·[06 §3·§7·§9](06-security-privacy.md) | **CRITICAL 게이트**: 실접속 롤 격리 테스트 그린(컨텍스트 없이 0행·타 tenant 0행·워커 큐 cross-tenant 성립) + 배포 스모크에서 **owner URL을 런타임에 넣으면 기동 전 중단**됨을 실연 + 배포 이미지 스택 전 여정 스모크 그린(로그인→단지 생성→문서 업로드→인제스트→AI SSE→트윈·주차장) + 기존 게이트 그린(ruff·mypy·pytest cov 80·vitest·build) | ✅ 완료 — 게이트: `ruff format` 168 files·lint 그린·typecheck 8/8(mypy api 80·db 26·ai-worker 18)·test 7/7(**db 136 passed cov 98.22%** — 신규 실접속 스위트 10건 포함 · api 345 cov 95.37% · ai-worker 34 cov 97.16%). **배포 이미지 스택 실측**(1호스트 3프로필, 파일럿 데이터 적재 상태 유지): `migrate` 2단계 그린(`f1a9c3e5b7d2` → `[runtime_roles] 접속 롤 수렴·검증 완료: liviq_app, liviq_worker`) · `pg_stat_activity` 실측으로 **api=liviq_app · ai-worker=liviq_worker · owner 접속 0**(내 psql 세션 제외) · 롤 속성 `rolcanlogin=t rolsuper=f rolbypassrls=f`. **fail-closed 2건 실연**: ①`APP_DATABASE_URL`에 owner URL → migrate 스텝 `exit=1`("APP_DATABASE_URL의 사용자가 'liviq'이다 — 'liviq_app'이어야 한다") → 앱 미기동 ②api를 `DATABASE_URL=owner·API_ENV=production`으로 기동 → 라이프스팬에서 `RuntimeRoleError` → `Application startup failed. Exiting.`. **전 여정 실측(프록시 경유 `/api`)**: 관리자 GET 19개 전부 200(파라미터 필수 2건은 값 부여 후 200) · geometry 322 · 주차 442면/차량 348(EV 29·번호판 복호 정상) · 문서 업로드 201 → 워커 인제스트 `{'status':'indexed','chunks':2}` → `content_chunks` 2행 embedding 채움(**워커 쓰기가 liviq_worker로 성립**) · AI 질의 SSE 토큰 점진 도착 + `citation`(제25조 납부기한) + `done{status:"answered",confidence:0.875}` · 공지 발행 201 → `notifications` 1행 · 시설 생성 201 → `outbox_events` 처리 완료(pending 0 — 워커 cross-tenant 큐 정책이 **실접속 롤에도 적용**) · SYS_ADMIN 여정(부트스트랩 → 임시 비밀번호 변경 204 → 단지 생성 201 → 비활성 204 → 재활성 204 → 소장 초대 202 → 빈 단지 삭제 204). 브라우저 실측: 주차장 대시보드 **442/264/256/8/178**·동별 53/45/48/59/51+외부 8(H9-5 기록과 동일) · 트윈 3D 322세대 렌더 · 콘솔 에러 0. **발견·수정**: ①프로브 테이블을 `households`로 뒀다가 `permission denied`(liviq_worker에 권한 없음) → 두 롤 모두 SELECT 가능하고 실배포에서 비어 있지 않은 `users`로 교체 ②`tenants` DELETE GRANT 누락(위) ③테스트 픽스처 정리 순서 — 런타임 커넥션이 FK 잠금을 쥔 채로 시드 DELETE가 돌면 무한 대기(`lock_timeout` + 의존 명시로 해결). **의도적 제외**: 로컬 개발(네이티브)은 owner 접속 유지 — 개발 DB는 superuser 단일 롤이고 런타임 롤 비밀번호를 개발자 `.env`에 넣는 비용이 이득보다 크다(기동 가드가 경고로 남긴다). 운영 스크립트(시드·부트스트랩)는 owner 접속 필요 → `migrate` 서비스로 실행(§2 절차에 반영) | ✅ 완료 |
| H10-3 | CI 릴리스 + 배포 런북 | `.github/workflows/release.yml`(buildx matrix 4종 · GHCR push · **sha + latest** 태그 · `cache-from/to: gha` 앱별 스코프 · PR은 `paths` 한정 **빌드만**(push 없음 — 워크플로 버그를 머지 전에 잡는다) · `workflow_dispatch` — 스펙 §4.3) · **[docs/12 배포 런북](12-deployment-runbook.md) 신설**(VM 3대 프로비저닝·방화벽 규칙(§6.1 경계와 대조)·GHCR private 패키지 pull 자격증명·시크릿 주입(`env_file` 0600 레포 밖·tier 최소 배치)·기동 순서(data → migrate → app → web)·**접속 롤 3-URL 계약**(H10-2)·백업(§7.1 연계)·롤백(이전 sha 재기동)·업그레이드 순서와 파괴적 스키마 변경 2단계 규칙) · `docs/README.md`·`CLAUDE.md` 문서 지도 등록 | **2단계 검증**(릴리스는 main push에서만 실제 push되므로) — ①**머지 전**: PR 빌드 job이 4개 이미지 빌드 그린 + 기존 게이트 그린 ②**머지 후**: main 릴리스 실행으로 **GHCR에 4개 이미지 게시 확인**(sha 태그) → 게시된 이미지로 스모크 스택 재기동(`IMAGE_PREFIX=ghcr.io/<owner>/liviq`·`IMAGE_TAG=<sha>`) → **롤백 1회 실연**(이전 sha 태그로 재기동 후 정상 동작) → 결과를 이 행에 현행화 커밋 | ✅ 완료 — **머지 전**: PR 빌드 job 4/4 그린(api 47s·ai-worker 48s·web-resident 1m50s·web-admin 3m15s) + 기존 게이트 그린. **머지 후 실측(2026-07-26)**: main 릴리스 2건 성공(`d8f9c87` #81 · `862d200` #82) → 각 4개 이미지가 `ghcr.io/romis9724/liviq-<앱>:<sha>` + `:latest`로 게시(로그의 `pushing manifest … @sha256:…` digest 확인). **게시 이미지로 스모크**: `IMAGE_PREFIX=ghcr.io/romis9724/liviq`·`IMAGE_TAG=862d200…`으로 app·web 재기동 → 4개 컨테이너 전부 GHCR 이미지로 교체 확인 · `migrate` 2단계 그린(`[runtime_roles] 접속 롤 수렴·검증 완료`) · api healthy · 로그인 200 · GET 7종 200 · 차량 348(번호판 복호 정상)·geometry 322 · 감사 4행 기록. **롤백 1회 실연**: `IMAGE_TAG`를 이전 sha(`d8f9c87…`)로 되돌려 pull·재기동 → 4종 교체 확인 · 로그인·차량·트윈 200 · 스키마는 최신 head(`f1a9c3e5b7d2`) 유지 · **그 버전에 없는 감사 로그만 0행** = 코드만 되돌아간다는 성질 관측. 이후 롤 포워드 정상. **발견 2건**: ①이미지가 **`linux/amd64` 단일 아키텍처**(`platforms` 미지정 = 러너 아키텍처) → **배포 VM도 amd64여야 한다**. Apple Silicon에서 검증할 때 `--platform linux/amd64` 필요(`no matching manifest for linux/arm64` 실측). 멀티아치는 QEMU 크로스 빌드로 CI 시간이 크게 늘어 실제 arm64 요구 시 도입(YAGNI) — 런북 §1에 기록 ②GHCR pull 자격증명은 `read:packages`가 최소 권한이지만 실측에선 `repo` 스코프 classic 토큰으로도 성공 — 런북 §3 정정. **미검증(잔여)**: VWorld 실사 3D iframe은 여전히 **실배포 도메인 등록 후**에만 확인 가능(도메인 잠금 키 — 런북 §6에 절차) | ✅ 완료 |

> **백로그/의도적 제외**: 무중단 배포(blue-green)·Kubernetes·중앙 로그 수집·모니터링 스택은 **H10 범위 밖**(부하·운영 요구 실증 후 — YAGNI) · 운영 env 계약은 H10-1에서 [`.env.example`](../.env.example)이 아니라 **별도 파일** [`infra/env.prod.example`](../infra/env.prod.example)로 분리했다(compose `--env-file` 치환 소스 겸 컨테이너 `env_file`이고, tier별로 나눠 배치(app tier 파일에만 `PII_MASTER_KEY`·`DATABASE_URL`·SMTP — [06 §7](06-security-privacy.md))하므로 로컬 `.env` 계약과 한 파일에 섞지 않는다).

### 8.14 H11 체크리스트 (운영 정합 — 감사 로그·문서 드리프트)

> 근거: H10-2 스모크 중 발견(2026-07-26) — `audit_logs`는 모델·RLS·append-only 권한 테스트까지 있는데
> **애플리케이션이 단 한 곳도 쓰지 않아 dev·배포 스모크 모두 0행**이었다. [06 §9](06-security-privacy.md)
> 배포 전 게이트에 "감사 로그 누락 없음" 항목이 있으므로 **실배포 차단 항목**이다.
> 범위는 사용자 결정(2026-07-26): **보안 핵심 subset**(전량 11종 구현이 아니라, 보안상 의미 있는 행위만
> 배선하고 나머지는 §8.3 백로그로 명시).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H11-1 | 감사 로그 실배선 (보안 핵심) | `apps/api/app/audit.py`(행위 상수 + `record_audit`(업무 트랜잭션 공유) + `record_audit_standalone`(로그인 실패 전용 별도 트랜잭션)) · 11개 지점 배선(로그인 성공·실패 · 가입 승인·거절 · 계정 비활성화 · 직원·소장 초대 · 명부 업로드 · 관리비 확정 · 차량번호 복호 열람 · 명부 조회) · [06 §8](06-security-privacy.md) 기록 대상 표를 단일 출처로 재작성(구현/백로그 구분) | 행위별 기록 테스트 + **개인정보 비저장 테스트**(`meta`에 이메일·이름·번호판·거절 사유 원문 0건 — **CRITICAL**) + 업무 롤백 시 감사도 롤백(거짓 기록 없음) + 로그인 실패는 401에도 기록 남음 + 게이트 그린 | ✅ 완료 — 게이트: ruff format 170 files·lint·typecheck 8/8·test 15/15(**api 359 passed cov 95.46%** — 신규 test_audit 13 + test_fees 확정 감사 1 · db 136 · ai-core 107 · ai-worker 34 · vitest 314)·check:paths 646건. **배포 이미지 스택 라이브 실측**(런타임 롤 `liviq_app` 접속): `auth.login`·`auth.login_failed`(401 응답에도 행 남음)·`pii.roster_viewed`·`pii.plates_viewed`(count 348)·`manager.invited`·`staff.invited` 기록 확인, meta에 이메일·성함·번호판 0건. **실측으로 잡은 결함 4건**(모두 코드에 반영): ①composite FK `(tenant_id, actor_user_id)` 때문에 **SYS_ADMIN 크로스테넌트 소장 초대에서 FK 위반** — 테스트가 아니라 운영에서도 터진다. 감사 행은 대상 단지에 남기고 행위자는 `meta.actor_user_id`·`meta.actor_tenant_id`로 기록, SYS_ADMIN 소속은 요청 컨텍스트가 아니라 **정의상 시스템 테넌트**를 넘긴다 ②로그인 실패 기록이 예외를 올리면 **401이 500으로** 바뀐다(인증 계약이 감사 저장소 장애에 묶임) → best-effort + ERROR 로그 ③프로세스 전역 엔진은 생성 시점 이벤트 루프에 묶여 재사용 시 깨진다 → standalone은 호출마다 NullPool 엔진 생성·dispose ④`audit_logs.ip`가 전부 **프록시 IP**로 찍힘 — uvicorn은 `FORWARDED_ALLOW_IPS`(기본 `127.0.0.1`) peer의 XFF만 신뢰 → env 계약 추가. Caddy가 XFF 끝에 실제 peer를 붙이고 uvicorn이 마지막 항목을 쓰므로 **프록시 경유 위조는 성립하지 않음**(실측). **의도적 제외**: 문서 공개범위 변경·공지 발행·ERP 동기화 감사와 이상 징후 알림은 §8.3 백로그 | ✅ 완료 |
| H11-2 | 문서·스키마 드리프트 정정 | [03 §4.8](03-database-design.md) 평면도 설계를 **미구현·대체됨**으로 정정(`unit_types`·`floor_plans`·`plan_devices`는 0행·코드 참조 사실상 0 — H9가 `household_geometries`로 대체, H9-6이 `unit_types` 마스터를 과설계로 폐기). **테이블은 남긴다**(사용자 결정 2026-07-26 — 스키마 변경 0이라 위험이 없고, 입주민 평면도 기능을 살릴 때 재사용) · 조사 기록(테이블 수 오탐 정정) | 문서가 실제 스키마·코드와 일치 · `pnpm check:paths` 그린 | ✅ 완료 — [03 §4.8](03-database-design.md) 머리에 미구현·대체 경고 삽입(테이블 실존·0행·코드 참조 0/0/2 실측치 포함)하고 구현된 `household_geometries` 구간을 명시적으로 구분. 스키마 변경 0. 테이블 수는 **오탐**으로 확정(위 주석) | ✅ 완료 |

> **테이블 수 오탐 정정(2026-07-26 실측)**: "dev DB 40개 vs 문서 38개"는 오탐이었다. dev·배포 스모크 모두
> `relkind='r'` **39개로 집합까지 동일**(diff 0)이고, 그중 `alembic_version`을 빼면 **업무 테이블 38개** —
> 문서가 맞다. 40은 `alembic_version` + 뷰 `v_users_safe`를 함께 센 값이다.

### 8.15 H12 체크리스트 (사내 GitLab 배포 — 단일 호스트 WSL)

> 근거: [ADR-0021](adr/0021-gitlab-ci-single-host-wsl.md)(2026-07-26 사용자 결정) — 사내 Windows Server
> (192.168.10.140) WSL2 Docker에 사내 GitLab(`dhkim/liviq`, [ADR-0021](adr/0021-gitlab-ci-single-host-wsl.md))
> 파이프라인으로 배포한다. **GitHub 정본 유지** — GitLab은 배포용 복제이고 `release.yml`은 그대로 둔다.
> 스펙은 §4.4. 형상 차이·불변 계약은 ADR-0021 결정 1~7.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H12-0 | 설계 갱신 | [ADR-0021](adr/0021-gitlab-ci-single-host-wsl.md) 신설 + [ADR-0020](adr/0020-container-deploy-3tier-vm.md) 개정 노트(결정 2는 단일 호스트에서 미성립·좌표 규약 변경) + 본 문서 §4.4 스펙·§8 단계 표·§8.15 + [01 §14](01-architecture.md) 두 번째 형상 + [12 §9](12-deployment-runbook.md) 단일 호스트 절 | 설계 문서 PR 머지(구현 착수 전) | ✅ 완료 |
| H12-1 | 파이프라인 + 이미지 좌표 | [`.gitlab-ci.yml`](../.gitlab-ci.yml) 신설(build matrix 4종 → GitLab 레지스트리 sha 태그 · deploy 잡은 `tags: [wsl-140]` 러너에서 `--profile data/app/web up -d` · MR은 빌드만) — **H12-2에서 실측판으로 대체됨**(러너 태그·배포 소스·게시 순서, 아래 행) · [`infra/compose.prod.yml`](../infra/compose.prod.yml) 이미지 참조를 `${IMAGE_PREFIX:-liviq-}<앱>`으로(구분자를 env로 이동 — GitLab 레지스트리는 슬래시 하위 저장소) · [`infra/env.prod.example`](../infra/env.prod.example) 좌표 예시 3종 | 기존 게이트 그린 + 로컬 1호스트 스모크가 **바뀐 좌표로도** 기동(회귀 없음) + `.gitlab-ci.yml` 문법 검증 | ✅ 완료 — **GitLab lint API `valid: True`**(첫 시도 실패: 평문 YAML 스칼라의 `": "`가 매핑으로 파싱 → 블록 스칼라로 수정). 좌표 렌더 3종 확인(`liviq-api:local` / `ghcr.io/<owner>/liviq-api:<sha>` / `<registry>/dhkim/liviq/api:<sha>`). **로컬 1호스트 3프로필 재기동 회귀 0**: 4종 이미지 해석 정상 · `migrate` 2단계 그린(빈 DB에 전체 체인 → head `f1a9c3e5b7d2` → `[runtime_roles] 접속 롤 수렴·검증 완료`) · 부트스트랩 → 로그인 200 → 비밀번호 변경 204 → `/me` 200 → 단지 생성 201 · 감사 로그 `auth.login_failed`·`auth.login` 기록(H11-1 배선이 이 스택에서도 동작). `check:paths` 708건 그린 | ✅ 완료 |
| H12-2 | 러너·호스트 준비 + 실배포 | 러너 등록(`shell` executor · 태그 `wsl`,`docker` · `clone_url` 오버라이드 · `gitlab-runner` docker 그룹) · WSL 운영 설정 · `/etc/liviq/env.prod`(0640) 배치 · [`infra/deploy-wsl.sh`](../infra/deploy-wsl.sh) 공용 진입점 · [`infra/compose.wsl.yml`](../infra/compose.wsl.yml) 오버레이 · [`13`](13-gitlab-wsl-deploy.md) 런북 · H12-1 초안 정정(러너 태그·배포 소스·`IMAGE_PREFIX` 규약 정합) | main push로 대상 호스트 배포 그린 + 전 여정 스모크 + **롤백 1회 실연** | ✅ 완료 — main 파이프라인 #118·#119·#120·#121·#123 그린(외부 기기 push → 사내 WSL 배포 실연). **롤백 1회 실연**(2026-07-27): `rollback` 수동 잡 + `ROLLBACK_TAG=083c18d7-vworld` → 스모크 4건 통과, **코드는 되돌아가고**(신규 UI 문자열 0건) **데이터·스키마는 유지**(households 322 · users 912 · alembic head `f1a9c3e5b7d2` 불변 · 감사 25건) → 현재 태그로 복귀·스모크 그린. SYS_ADMIN 부트스트랩 완료(`romis97@hotmail.com`), 로컬 개발 DB 이관 완료(PII 키 동반 — 키가 다르면 `login_id` HMAC 불일치로 로그인 불가·`pii_vault` 복호 불능). **남은 것**: WSL 부팅 자동 시작(`wsl_autostart_liviq` — 관리자 PowerShell 필요, 미등록. 없으면 Windows 재부팅 후 잡이 `pending`) |
| H12-3 | 실배포 후속 (외부 접속·게시·보존) | 포트 기반 외부 접속([13 §9](13-gitlab-wsl-deploy.md) — Caddy 사이트 주소 2개 + Windows portproxy) · 게시 대상을 **Nexus** 로 전환(GitLab 레지스트리 미노출 실측, [13 §8](13-gitlab-wsl-deploy.md)) · `publish` `allow_failure` 제거 · 태그 보존 30일 정책 · 두 호스트 `logrotate`(로그 25GB 사고 대응) | 외부에서 두 앱 200 + Nexus 게시 그린 + 보존 정책 문서화 | ✅ 완료 — 외부 `17000`·`17001` **200**(입주민·관리자 화면 확인) · 파이프라인 #123 **전 잡 그린**(build 7.9s → deploy 11.5s → smoke 1.1s → **publish 23.0s**) · Nexus `liviq/<앱>:2509b396` + `latest` 4종 `201 Created`. 실측 함정 3개: ①`listenaddress=0.0.0.0` 이 루프백까지 점유해 `→127.0.0.1` portproxy 는 자기 루프(`Empty reply`) ②protected CI 변수는 비보호 브랜치에 미주입 → 잡 토큰 폴백이 남의 레지스트리에 401 ③`docker start` 는 env 를 재적용하지 않는다(재생성 필요) |

> **의도적 제외**: 무중단 배포·다중 호스트·중앙 로그 수집은 H12 범위 밖(ADR-0021 재검토 신호에 조건 명시).
> 멀티아치 이미지도 제외 — 러너·대상 모두 amd64(§8.13 H10-3 실측).

### 8.16 H13 체크리스트 (시설 그래프 대시보드 · 세대 평면도)

> 근거: 사용자 인터뷰 확정(2026-07-27, [ADR-0022](adr/0022-facility-graph-dashboard.md)) — 시설관리 메뉴 메인을
> **3D force-directed 시설 그래프**로 개편(레퍼런스: careerhackeralex.vercel.app/memory — 3D 별자리·렌즈·클릭 패널).
> **데이터 현황**: Neo4j 시설 그래프는 H3부터 **쓰기만 가동** 중이다 — PG(SoR) → `outbox_events` →
> [`graph_sync`](../apps/ai-worker/src/ai_worker/graph_sync.py)(15초 arq cron) → Neo4j MERGE, 접근은
> [`GraphClient`](../packages/ai-core/src/ai_core/graph/client.py) typed 레이어만(**raw Cypher 금지**).
> 지금까지 이 그래프를 **읽는 화면이 없었다** — H13-1이 첫 읽기 소비자라 파생 그래프 end-to-end 검증 가치가 함께 있다.
> **불변**: PG SoR·Neo4j 파생([11 §5](11-data-architecture.md)) · LLM 출력이 부수효과를 직접 트리거하지 않음(규칙 8) ·
> 마스킹 fail-closed(규칙 2) · tenant 격리 이중 방어(규칙 3).
> 근거 설계: [00 §3.5](00-requirements.md) FR-FAC-04~06 · [01 §13](01-architecture.md) 시설 표 · [04](04-menu-structure.md) 메뉴·여정 ·
> [05 §5·§7](05-ui-ux-design.md) · [11 §1·§2](11-data-architecture.md) · [ADR-0022](adr/0022-facility-graph-dashboard.md).
> 각 작업 단위는 §3.1 사이클(설계 갱신 → 구현 → 현행화 → PR)을 따르고, 머지는 단위별 사용자 확인 후 진행.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H13-0 | 설계 갱신 | [ADR-0022](adr/0022-facility-graph-dashboard.md) 신설 + [adr/README](adr/README.md) 목록 · [00 §3.5](00-requirements.md)(FR-FAC-04~06) · [01 §13](01-architecture.md)(`GET /admin/facilities/graph`) · [04](04-menu-structure.md)(시설 관리 하위 개편·매트릭스·여정) · [05 §5·§7](05-ui-ux-design.md)(그래프 UX·접근성 대체 수단·번들 예외) · [11 §1·§2](11-data-architecture.md)(첫 화면 소비자·커버리지 확장 주석) · 본 문서 §8 단계 표·§8.16 | 설계 문서 PR 머지(구현 착수 전) | ✅ 완료 (PR 머지 후 확정) |
| H13-1 | 3D 그래프 메인 | `GraphClient` typed 조회 메서드 신설(예 `fetch_facility_graph(tenant_id)` — **tenant 필터 강제**, raw Cypher 미노출) · `GET /admin/facilities/graph`(MANAGER · `{nodes, links}` — `Facility`·`Incident`·`Maintenance` + `HAS_INCIDENT`·`HAS_MAINTENANCE` · **Neo4j 미가용 시 PG `facilities` 축약 그래프(노드만·관계 없음) + `degraded`**) · web-admin 시설관리 **메인 교체**(react-force-graph-3d `dynamic import` `ssr:false` 격리 · **계통 렌즈**(`facilities.type` 계통색·포스 그룹핑, 가상 허브 노드 없음) · **검색→카메라 fly-to 강조** · 옆 패널은 기존 `GET /admin/facilities/{id}`(FacilityDetail) 재사용 · 관련 민원은 **위치 추정 + "추정" 배지**만 · 기존 FacilityManager는 **목록 보조 뷰 토글**로 유지) · `packages/api-types` 재생성 | tenant 격리·MANAGER 인가 테스트(**CRITICAL** — 타 tenant 노드 0건) + **Neo4j 미가용 폴백 테스트**(503 아님·`degraded=true`·노드만) + 게이트 그린(pytest cov 80·vitest·build·api-types drift) + 시각 실측(1280·375px·콘솔 0 — 그래프↔목록 토글·검색 fly-to·상세 패널) | ✅ 완료 — 게이트: pytest api 365(cov 95.57%)·ai-core 109(94.40%, 실 Neo4j 픽스처 포함)·vitest 224(신규 31)·typecheck·lint·build 그린. 번들: `/facilities` First Load 119kB(+5kB), three.js 348kB는 지연 청크 고립(초기 로드 포함 페이지 0·`/twin` 118kB 불변 — 05 §7 예외 조건 충족). 시각 실측(첫마을 4단지 푸르지오, MANAGER): 검색→fly-to→상세 패널 자동 오픈(현황·장애·정비 이력·관련 민원 "추정" 배지)·그래프↔목록 토글·degraded/정상 양 경로(로컬 api env에 NEO4J_* 추가로 정상 경로 실증 — degraded 배너 문구 정상)·콘솔 0·375px(검색 행 줄바꿈 결함 발견 즉시 수정). **구현 노트**: oklch 토큰을 three.js가 파싱 못해 그래프 전용 sRGB 변수를 facilities.css `:root` 단일 출처로 정의(캔버스 getComputedStyle·범례 var() 공유). 민원 매칭은 마운트 1회 전량 조회 후 클라 필터(수천 건 규모면 서버 필터 필요). 민원 딥링크는 H13-2 정식 연결과 함께 |
| H13-2 | 위치 렌즈 + 민원 정식 연결 | **위치 렌즈**(`facilities.location` 동 단위 그룹핑 — 렌즈 토글 2종 완성) · `inquiries.facility_id` **nullable FK 마이그레이션**(composite FK + 표준 tenant RLS 경로 확인 — [03 §5](03-database-design.md)) · **담당자 지정 UI**(민원 상세에서 설비 선택 → 정식 연결) · **LLM 추천**(마스킹 후 후보 추출 — [ADR-0002](adr/0002-mask-before-external-llm.md) fail-closed, **승인 전 DB 쓰기·부수효과 0**, 원클릭 승인 액션 엔드포인트만 FK를 쓴다) · 상세 패널 민원의 **정식/추정 배지 구분** | **승인 게이트 테스트**(**CRITICAL** — 추천 호출만으로 `facility_id`·감사·알림 어느 것도 변하지 않음) + 마스킹 fail-closed 테스트 + tenant 격리·인가 테스트(**CRITICAL** — 타 tenant 설비로 연결 거부) + 게이트 그린 + 시각 실측 | ✅ 완료 — 마이그레이션 `a2b3c4d5e6f7`(단일 head, composite FK — 타 단지 설비 참조 DB 거부). `PUT /admin/inquiries/{id}/facility`·`POST .../facility-suggest` **MANAGER 전용**(민원 일반 처리의 STAFF 포함 `_ADMIN_ROLES`와 구분). suggest는 환각 id 폐기·name은 DB 행·reason은 unmask 후 표시·LLM 미가용/마스킹 실패 503(폴백 없음). 게이트: pytest api 372(cov 95.38%)·db 136(98.22%)·vitest 232(렌즈 9 추가)·typecheck·lint·build 그린. 시각 실측: 렌즈 전환(범례 위치별 101동)·민원 연결→해제 왕복·AI 추천 미가동 안내 문구·그래프 패널 '연결'/'추정' 배지+각주·콘솔 0. **비고**: 529 장애로 Opus worker가 파일 끝 `</content>` 아티팩트 2건 남김 → 후속 worker가 발견·제거(게이트가 잡아냄) |
| H13-3 | 평면도 데이터 + 입주민 뷰 | (별도 인터뷰 확정 — apt-facility-finder 포팅) 죽은 스키마 기동(`floor_plans`·`plan_devices`·`unit_types` — 초기 마이그레이션 `d5422d3f35d5`에 **실존·0행**, [03 §4.8](03-database-design.md) 계약 재사용) · `plan_devices`에 `room`·`dir` **nullable 컬럼 2개** 추가 · 세대 오버라이드 미구현(`action='base'`만) · 입주민 홈 "우리집 평면도" 카드 → **본인 세대 직행**(동·호 선택 없음 — [06:11](06-security-privacy.md) 소유권 계약 유지) · **상세 설계 갱신(00·03 §4.8·05·06 본문)은 H13-3 자체 ①설계 커밋에서** 수행(H13-0은 본 표 요약 행까지) | 소유권 격리 테스트(**CRITICAL** — 타 세대 평면도 접근 거부) + 마이그레이션 회귀(기존 0행 테이블 살리기·단일 head) + 게이트 그린 + 시각 실측 | ✅ 완료 — 설계 커밋(00 FR-PLAN·03 §4.8 기동 계약·05·06·01 §13·11) 선행. 마이그레이션 `b3c4d5e6f7a8`(room·dir, 왕복 검증·단일 head). `GET /me/floor-plan`: 세션 household 직행(우회 표면 없음)·라벨 정규화 매칭·실패 4분기 404·**presigned GET URL(TTL 600s) 최초 구현**(docs/06 §5 계약 — Storage 프로토콜 확장). 시드: finder annotations 이식(rooms 14·elements 40)+B 미러, 84M·59C 각 54 devices·이미지 MinIO 업로드(실행 완료). 입주민 뷰: 홈 카드→/floor-plan(픽셀→% 마커·카테고리 칩 6종 토글·마커 button+aria 40개·팝오버 상단 플립·목록 대체 표). 게이트: pytest api 384(95.45%)·db 136(98.23%)·vitest 132(신규 11)·build(/floor-plan First Load 105kB) 그린. 시각 실측(최주민=401동 201호→84M, 데스크톱·375px): 도면 렌더·토글·팝오버(잘림 결함 발견→플립 수정)·관리자 세션 403 방어·콘솔 0 |
| H13-4 | 평면도 편집 + 트윈 상세 평면도 탭 | 시설관리 안의 편집 UI(배경 이미지·마커 좌표 배치·방/방향 지정) · 트윈 세대 상세 패널에 **평면도 탭** 추가(기존 세대 상세 계약 재사용) | 편집 인가·tenant 격리(**CRITICAL**) + 좌표 저장 왕복 + 게이트 그린 + 시각 실측 | ✅ 완료 — admin API 4종(목록·상세·multipart 업로드(기존 도면은 이미지만 교체·마커 보존, 크기는 클라이언트 제출 — Pillow 미도입)·devices 전체 교체(좌표 범위·dir Literal·tenant facility 검증·상한 500·base 고정)). 시설관리 세 번째 탭 '평면도'(도면 카드+업로드→에디터: 클릭 추가·선택 폼·facility 연결·저장 게이트·이탈 confirm). TwinDetailPanel 평면도 아코디언(lazy·정규화 매칭·읽기 전용). 게이트: pytest api 397(95.53%)·vitest 245(헬퍼 13 추가)·build 그린. 시각 실측: 에디터 추가→저장(84M 55 API 실확인)→삭제·원복(54)·검증 문구·콘솔 0. **한계**: 트윈 아코디언 실렌더는 deck.gl 피킹이 자동화 합성 이벤트를 안 받아 미확인(헬퍼 유닛+API 계약 검증) — 실브라우저 확인 백로그 |
| H13-5 | 평면도 어시스턴트 도구 | 자연어 질의("우리집 공유기 어디?")를 **읽기 전용 도구**로([ADR-0007](adr/0007-readonly-tool-agent.md)) — **규칙 파서 1차(0ms·LLM 미호출)** + 실패 시 LLM 보조 spec 추출. 도구는 본인 세대 범위만 조회하고 쓰기 없음 | 규칙 파서 우선 경로 테스트(LLM 호출 0) + 소유권·마스킹 테스트(**CRITICAL**) + 게이트 그린 | ✅ 완료 — `floor_plan_parser.py`(query.js 정본 이식 — 요소 14종·동의어 47·묶음 3·방 14·묶음 6, 순수 함수) + `find_in_floor_plan`(RESIDENT 전용, ToolContext.user_id로 세대 해석 — 인자에 세대·타입 없음, 도면 미준비 5분기 note). **파서 성공 경로 LLM 호출 0을 트랜스포트 레벨 AssertionError로 강제**(CRITICAL). LLM 보조는 파서 실패 시만(도면 실제 device_type·room enum 제약·enum 밖 폐기). registry 7종. 게이트: ai-core 136(94.41%)·api 397(95.53%) 그린, 테스트 29건. **한계·백로그**: 어시스턴트 라이브 E2E는 로컬 LLM 미가동으로 미실측(도구 단위 검증 완료 — @llm E2E에 질의 추가 백로그) · 출처 카드 /floor-plan 딥링크는 ToolCitation 계약이 링크 필드 미지원이라 제외(계약 변경 별도 단위) |
| H13-6 | 그래프 커버리지 확장 + 시설물 실데이터 | (사용자 요청 2026-07-27) ①**평면도 그래프 투영**: `floor_plans` 쓰기 경로(admin 업로드·devices 전체 교체·시드)에 `outbox_events(aggregate_type='floor_plan')` 스냅샷 기록(도메인 행과 한 트랜잭션 — 이중 쓰기 금지 §4.9) · graph_sync 핸들러 + GraphClient `replace_floor_plan`(FloorPlan 노드 merge + 기존 PlanDevice 노드 전체 교체 + `facility_id` 있는 마커는 `LINKED_TO`→Facility) · facility 삭제(deleted_at) tombstone 반영 ②**시설물 실데이터 시드**(K-apt 첫마을4단지 A33982105): 승강기 11(동별)·화재수신반 R형·부스타 급수·지역난방 열교환·수전 2250kW·CCTV 78대·주차관제(정문·긴급차 자동인식)·EV 완속 8기(서울씨엔지)·부대복리 7종(관리사무소·노인정·문고·어린이놀이터·유치원·커뮤니티·자전거보관) + 표준 필수 설비(소방펌프·스프링클러·옥내소화전·비상발전기·저수조·배수펌프·지하주차장 환기·공동현관 출입시스템 등) — **도메인 행+outbox 한 트랜잭션** 시드(그래프 자동 반영), name 기준 upsert 멱등 | 평면도 투영 tenant 격리·전체 교체 멱등 테스트(**CRITICAL**) + facility tombstone 테스트 + 시드 멱등·리포트 + 게이트 그린 + 그래프 화면 실측(시설 수십 노드·렌즈 그룹핑) | ✅ 완료 — outbox `_json_safe` **Decimal 누락 버그 발견·수정**(PlanDevice x/y). `replace_floor_plan`(전체 교체·LINKED_TO·역전 방지)·facility tombstone·`include_plan` opt-in(기본 false — 마커 108 과밀 방지)·`drain_outbox.py`(로컬 1회 러너). 시드 실행: 시설 36 신규(10계통·(tenant,name) upsert·status 보존) → drain 51 이벤트(ollama 기동 — 구 incident 임베딩 5건 포함) → **Neo4j 실측: Facility 37·FloorPlan 2·PlanDevice 108(HAS_DEVICE)**. 게이트: ai-core 143(94.52%)·api 401(95.54%)·ai-worker 35(97.54%)·vitest 245·build 그린. 화면 실측: 39노드 계통 클러스터·검색 fly-to(소방펌프)→패널·위치 렌즈(401~405동+미지정)·콘솔 0. **백로그**: 비주거 위치(기계실·관리사무소 등)를 미지정 대신 자체 그룹으로 — 위치 렌즈 개선 · `seed_floor_plans` 재실행 시 plan pg_id 교체로 옛 FloorPlan 노드 잔존 가능(도면 재시드 후 drain 전 수동 정리 또는 tombstone 이벤트 추가) |
| H13-7 | 그래프 연관 관계 실체화 | (사용자 지적 2026-07-27 — "연관 관계가 없다" + "중심에 단지 노드") ⓪**Complex 루트 노드**: 스냅샷에 `complex_name`(tenants.name) → `(:Complex {tenant_id})` merge + `(loc)-[:PART_OF]->(complex)`·`(fp)-[:PART_OF]->(complex)` — 단지가 그래프 중심 ①**Location 노드**: `merge_facility`가 `location` 문자열로 `(:Location {name, tenant_id})` merge + `(f)-[:LOCATED_IN]->(loc)`(위치 변경 시 옛 관계 제거) — docs/11 §4 원 모델("설비·…·위치") 복원, ADR-0022 결정 2 개정 노트(화면이 노드를 발명하지 않는다는 원칙은 유지 — 위치는 그래프 실체) ②`fetch_facility_graph`에 Location 노드·LOCATED_IN 포함 ③화면: Location 노드 렌더(중립색·라벨) + **"평면도 표시" 토글**(include_plan — FloorPlan·PlanDevice·HAS_DEVICE 108선 노출) ④기존 데이터 backfill(시설 재시드 upsert → outbox → drain) | Location 관계 tenant 격리·위치 변경 재배선 테스트(**CRITICAL**) + 게이트 그린 + 화면 실측(설비-위치 엣지·평면도 토글) | ✅ 완료 — Neo4j 실측: **Complex 1('첫마을 4단지 푸르지오') ← PART_OF 14 ← Location 14 ← LOCATED_IN 37 ← 설비 37**(backfill=재시드+drain, 구 승강기는 PATCH 터치로 소급). 화면: 엣지 렌더·위치/단지 상시 라벨(three 스프라이트)·location/complex 클릭 패널·'평면도 표시' 토글(마커 108 opt-in)·콘솔 0. 게이트: ai-core 153(94.63%)·api 402(95.55%)·vitest 260·build 그린. ADR-0022 개정(가상 허브 금지 원칙 유지 — 위치·단지는 그래프 실체) |

> **백로그(수요 확인 후)**: ~~그래프 커버리지 확장~~(**H13-6로 채택**, 2026-07-27 — 사용자 요청: 평면도·마커 Neo4j 편입 + 시설물 K-apt 실데이터 등록 + 쓰기 경로 전부 그래프 반영) ·
> **부품/증상 유사도 렌즈**(`Part`·`SAME_MODEL` 관계와 Incident 임베딩 활용 — [11 §4](11-data-architecture.md) 모델엔 있으나 현재 미동기화) ·
> **3D 성능 재검토**(설비 500+ 노드에서 프레임·상호작용 저하 시 렌즈 필터 기본 적용 → 2D/클러스터 축약, [ADR-0022](adr/0022-facility-graph-dashboard.md) 재검토 신호) ·
> 평면도 **세대 오버라이드**(`action='override'`) · 그래프 노드에서 민원·정비 **바로 등록**(현재는 조회 전용).

### 8.17 H14 체크리스트 (시설관리 UX 개편 · 시설 코드 체계)

> 근거: 사용자 피드백(2026-07-27) — "시설관리 화면 구성 UI/UX 10점". 인터뷰 확정:
> **B안** = 탭(그래프/목록/평면도) 폐지 → 전체화면 그래프 + 플로팅 패널(트윈 대시보드·주차장 3D 프로토타입 문법 —
> 좌상단 현황판·우측 상세·목록 플로팅, 평면도 편집은 오버레이). **A안** = 시설 코드 `계통약어-위치약어-연번`(예 EL-401-01).
> 빼기 승인 2건: 그래프의 PlanDevice 마커 108개 제거(도면 클릭→평면도 오버레이로) · AI 도우미 패널 접기(플로팅 버튼).
> incident/maintenance 소노드는 유지. FloorPlan 잔존 노드 버그(재시드 pg_id 교체→고아 노드가 "떨어진 중복"으로 노출) 실증 — 정리+재발 방지 필수.
> **불변**: PG SoR·Neo4j 파생 · tenant 격리 이중 방어 · MANAGER 인가 · 코드 부여는 서버(코드가 실행 — 규칙 8).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H14-1 | 시설관리 한 화면 개편 | 탭 3종 폐지 → **전체화면 그래프** + 플로팅 패널(좌상단 현황 요약·우측 상세(기존 FacilityGraphPanel 재사용)·목록은 플로팅 패널 토글·평면도 편집은 도면 노드/목록 진입→**전체 오버레이**(기존 FloorPlanManager/Editor 재사용)) · 그래프에서 **PlanDevice 마커 제거**(include_plan 화면 소비 중단 — FloorPlan 노드는 **기본 표시**·토글 삭제) · AI 도우미 진입은 플로팅 버튼 · **FloorPlan 잔존 노드 정리+재발 방지**(seed_floor_plans가 (tenant, unit_type) 기준 기존 행 upsert — pg_id 보존) | 잔존 노드 0 실측 + 재시드 멱등 테스트 + 게이트 그린 + 시각 실측(1280·375px — 그래프 기본 도면 노드·플로팅 패널·평면도 오버레이·콘솔 0) | ✅ 완료 — 전체화면 그래프+플로팅(도구 3버튼은 좌상단 현황판 위, 폭 정렬 --fac-left-col). **사용자 재지시로 마커 재구조화**: 제거 대신 도면→방(PlanRoom 28)·종류(PlanKind 28) 허브→마커 80 계층으로 Neo4j 실체화(room 항목은 허브 승격, 구 직결 엣지 0 실측). 잔존 노드 2건 정리·시드 pg_id 보존·prune_floor_plans 신설. 목록 20건 잘림 결함 수정(limit 100). 375px 도크 잘림 수정 |
| H14-2 | 시설 코드 체계 | `facilities.code` 컬럼(**서버 자동 부여** `계통약어-위치약어-연번`, unique(tenant_id, code)·수정 불가) · 계통 약어는 공통코드([ADR-0017](adr/0017-tenant-code-registry.md) codes) 등록 · 기존 37건 backfill 마이그레이션 · 그래프 패널·목록에 코드 표시·코드 검색 · **민원 접수: 코드 직접 입력→즉시 설비 연결** · 평면도 **종류·방 공통코드** 등록(에디터는 select — `room` 종류 수정 불가 고정) | 코드 유일성·자동 부여·수정 거부 테스트(**CRITICAL** — tenant 격리 포함) + 코드로 민원 연결 왕복 + 게이트 그린 + 시각 실측 | ✅ 완료 — 마이그레이션 `c5d6e7f8a9b0`(백필 42건 실측·유일성 그린, 규칙 단일 출처 `liviq_db.facility_systems`). 공통코드 3그룹(FACILITY_SYSTEM 약어 10·PLAN_DEVICE_TYPE 14·PLAN_ROOM 14, floor_plan_parser 사전과 드리프트 가드). 민원 code 연결(타 단지 404)·목록 ?code= 필터·그래프/Neo4j code 흐름. 화면: 코드 뱃지·코드 검색·민원 코드 입력 폼·에디터 공통코드 select(room 고정). **주의**: dev 반영 시 마이그레이션 선적용 필요(미적용 창에서 상세 500 실증) |
| H14-3 | 트윈 UX 2건 | ①설비 상태 목록 길어지면 **스크롤**(고정 높이) ②세대 상세의 평면도를 상세 아래가 아니라 **왼쪽 영역 전체 오버레이**(뒤 건물 3D 반투명 노출) | 게이트 그린 + 시각 실측(설비 스크롤·세대 클릭→평면도 오버레이·닫기 왕복) | ✅ 완료 — 설비 목록 min(32vh,22rem) 스크롤. **사용자 재지시로 강화**: 버튼 없이 세대 상세 열리면 딤 영역 전체에 평면도 자동 표시 + 입주민 뷰와 기능 동일(FloorPlanViewer를 @liviq/ui로 공용화 — 칩·방라벨·방향 마커·팝오버 플립·목록 표, 입주민 FloorPlanView 287→70줄). 실측: 세대 클릭→즉시 평면도·칩 토글·팝오버·콘솔 0 |
| H14-4 | 주차장 3D | 프로토타입 `parking_view3d.js`(AI_digitaltwin_apartment 커밋 700fd04·b77e154 — three.js InstancedMesh 442면·raycast 픽킹·카메라 플라이) 이식 — 주차장 대시보드 2D 배치도에 **3D 토글**(dynamic import ssr:false·2D 폴백 유지) | 게이트 그린 + 시각 실측(3D 렌더·픽킹→상세·2D 폴백·콘솔 0) | ✅ 완료 — ParkingScene3D(InstancedMesh·raycast·카메라, 색 CSS 변수·WebGL 폴백·reduced-motion·dispose). /parking First Load 116kB(three 지연 청크). 이식 중 실버그 3건 수정(boundingSphere 컬링·라벨·조명). **사용자 추가 지시 2건**: 주행 차량 5대(통로 경로 파생·픽킹 제외·2프레임 이동 실증) · 진입 스윕 제거(즉시 전체 부감). 장식(비콘·팔레트)은 YAGNI 제외 |
| H14-5 | 관리자 UI 일관화 | (사용자 피드백 2026-07-27 — "가이드 없이 마음대로 만든 느낌, 30점" · 헤더가 본문보다 작음) [05 §5A](05-ui-ux-design.md) **공통 패턴 가이드** 신설(타이포 위계 강제·StatCard·page-toolbar·목록 2형·radius/간격/색 규율) → ⓐ기반: admin-shell 타이포 h1>본문 복구 + `@liviq/ui` StatCard/StatGrid·공통 툴바/목록 CSS ⓑ메뉴별 적용(대시보드·공지·주민·관리비·민원·직원·문서 — 병렬) ⓒ접근성 패스(focus-visible 전수·대비·tablist·th scope) | 7개 메뉴가 §5A 패턴만 사용 + h1 위계 복구 + 게이트 그린 + 시각 실측(7개 메뉴 데스크톱·375px·콘솔 0) | ✅ 완료 — ⓐ기반(@liviq/ui StatCard/StatGrid·PageToolbar·FilterChips·SearchField·.data-list, h1 --text-2xl 복구) ⓑ7메뉴 적용(죽은 CSS 대량 삭제 — dashboard 355→141줄 등, residents controlled 검색 IME 버그 수정) ⓑ'나머지 메뉴 폴리시+카드 패딩 16px 단일화 + 보완(순서 강제 §5A 개정: 현황→툴바→목록·StatGrid 한 줄 최대 5칸·직원 thead 표·기간 칩 제목 라인·섹션 h2 통일·트윈/주차장 헤더 1줄). 실측: 대시보드·민원·주민·관리비·동호수(직접)+직원·문서·375px(Worker 스크린샷) 콘솔 0. 잔여: 직원 초대 폼 위치(순서 강제 시 토글 상시화 필요 — 사용자 결정 대기) |

### 8.18 H15 체크리스트 (LLM 백엔드 런타임 전환 · 성능 비교)

> 근거: 사용자 요청(2026-07-28) — 로컬 ollama·내부 vLLM·외부 OpenAI API 성능 비교, **env 아닌 관리자 UI에서
> AI 접속 정보 직접 설정·교체**. 인터뷰 확정: 목적=운영 백엔드 선정 · ollama/vLLM은 동일 모델(llama3.1:8b)로
> 순수 서빙 비교, OpenAI는 mini급 1종 별도 축 · 선정 기준=evals 전 케이스 pass 게이트 + 지연(TTFT·총응답)·동시처리,
> 비용은 참고치 · 골든셋 비교는 기존 `evals/run.mjs` 재사용(H5-1 선례, 신규 러너 금지).
> **불변**: 마스킹 게이트는 호출자 경로라 백엔드 무관 자동 적용(규칙 2 — OpenAI 외부 전송도 동일 경로) ·
> 설정 변경은 서버 인가(규칙 4) · 임베딩은 전환 제외([03 §4.7](03-database-design.md) — 색인 정합).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H15-1 | 관리자 AI 설정 | `ai_backend_config` 전역 단일 행 테이블(마이그레이션·liviq_app grant·RLS 없음) · API `GET/PUT /system/ai-config`+`POST /system/ai-config/test`(SYS_ADMIN — GET은 api_key 끝 4자 마스킹, PUT은 api_key 생략 시 기존 유지, test는 1회 chat 스모크+지연 ms 반환) · `get_llm()`이 DB 설정 우선·env `LLM_*` 폴백(요청 단위 — 재시작 불필요) · answer_cache 키를 env 모델명 대신 활성 백엔드(`model@host`)로 분리 · web-admin `/system/ai` 페이지(§5A 패턴 — 폼+저장+연결 테스트, SYS_ADMIN 네비 추가) | 비 SYS_ADMIN 403·api_key 원문 미노출(CRITICAL) + env 폴백·백엔드 전환 캐시 분리 테스트 + 게이트 그린 + 시각 실측 | ✅ 완료 — 마이그레이션 `e9f0a1b2c3d4`. NULL 컬럼(api_key·reasoning_effort)은 env 폴백(키를 비워 저장해도 env 키 유지 — UI가 원문을 되돌릴 수 없어 조용한 401 방지, `app.ai_backend.merge_settings` 단일 지점). 테스트 api 432·db 160·ai-core 161·web 328 그린(cov 95.6/98.3/94.5%). 시각 실측: 연결 테스트 성공(로컬 ollama 230ms)·실패(미가용 요약)·저장→DB 우선 전환·375px·콘솔 0 |
| H15-3 | AI 설정 확충(임베딩·튜닝 노브) | (사용자 인터뷰 2026-07-28 — 목적: 백엔드 비교·품질 튜닝) `ai_backend_config` 컬럼 확장([03 §4.7](03-database-design.md)): ①임베딩 백엔드(base URL·모델·API 키 — 차원 1024 고정, 연결 테스트가 실측 차원 검증·불일치 저장 거부) ②안전 노브 5종(top_k·LLM 출력 상한·timeout·도구 confidence·캐시 TTL — NULL=env/코드 기본값 폴백, 즉시 반영) ③위험 노브(임베딩·chunk_max_tokens)는 저장 시 경고 + **명시적 재색인 버튼**(전 문서·공지 재인제스트 enqueue, jobs 카운트로 진행 표시) · `liviq_worker` SELECT grant(인제스트가 활성 설정 소비) · UI 섹션 확장(§5A) | 비 SYS_ADMIN 403·키 마스킹(CRITICAL) + 차원 검증 거부 + 노브 폴백·즉시 반영 + 재색인 enqueue 테스트 + 게이트 그린 + 시각 실측 | ✅ 완료 — 마이그레이션 `f1a2b3c4d5e6`. 해석 단일 지점 `ai_core.backend_config`(api 요청·worker 잡 공유, BackendConfigRow Protocol — ai-core는 liviq-db 미의존 유지). PUT 임베딩 변경 시 차원 실측 가드(1536 → 422 실증). 테스트 api 459·ai-core 169·worker 37·db 161·web 362. 시각 실측: 임베딩 테스트 bge-m3 1024차원·노브 저장 DB 왕복·**재색인 34/34 실왕복**(arq worker 기동, 문서 재인제스트 전건 indexed)·375px·콘솔 0. 부수 발견: `color-mix(in oklch)` 무채색 hue 끌림(초록 틴트→분홍) — ai-config.css는 srgb로 수정, 전역 161곳은 별도 작업 분리 |
| H15-2 | LLM 성능·품질 분석 보고서 | (사용자 인터뷰 2026-07-28 재정의 — **운영 선정 아님, 분석 보고서**) 측정 환경 **4080Ti vLLM 고정**(하드웨어 비교 장은 변인 통제 불가로 삭제 — 맥북은 신규 모델 게이트 스크리닝만, 스택별 차이는 부록 참고치). 2단: ①모델 2~3종(llama3.1:8b·exaone3.5·qwen3 reasoning-off — 게이트 탈락도 사유와 함께 보고) → 승자로 파라미터 스윕(top_k 4/8/16·청크 2값 — 청크는 재색인 동반) ②로컬 최적 조합 vs OpenAI mini·상위 1종(비용 실측 포함). 측정: 품질 3층(근거 적중률·폴백률 자동 / LLM 블라인드 심사 4축 / 사람 확인) + TTFT·총응답 p50/p95·토큰/초 + 동시 1·5·10. 재현 조건 명기(반복 3회·캐시 off·골든셋 10~15문항·네트워크 조건). H15-1·H15-3 UI로 백엔드 교체, 러너는 기존 evals 재사용(신규 하네스 금지) | 실측 표 + 차트 포함 분석 보고서(부적격 모델 사유 포함) | 🚧 진행 — **로컬 축 측정 완료, OpenAI 축만 대기**(키 필요). 전 과정 기록은 [MEASUREMENT-LOG.md](../evals/results/rag500/MEASUREMENT-LOG.md) R1~R21이 단일 출처. ①모델 8종 스크리닝 → **llama3.1-8B-AWQ(vLLM) 단독 적격**(Qwen3는 자격 통과·지연 4.8배, xLAM은 도구호출 10/10인데 스텝 상한 위반, EXAONE은 chat_template에 도구 문법 부재). 부적격 판정의 신뢰 조건 성문화(파서 2종·VRAM 단독·10회 반복) ②튜닝 스윕 8후보 중 **채택 2·기각 6** — top_k 8→16 채택(규약 인용 53→80%), 청커 제목 상한·조항 경계 채택(청크 1,211→242토큰·조항 라벨 정합 284/284), 컨텍스트 예산 4,000·MIN_SCORE 스윕·리랭커·하이브리드·임베딩 교체·프롬프트 강화·인용 재요청은 기각(각 기각 사유는 R17·R20·R21). ③기준선 확정 pass 116~125(중위 120)·인용 69.2~74.0%·hardfail 0(반복 3회·캐시 off). **결론: 8B 급에서 RAG 품질 상한은 검색이 아니라 인용 규율** — 정답 청크가 유사도 1위(0.70~0.72)로 올라오는데 모델이 [n]을 붙이지 않아 폐기되는 건이 17~21%이고, 프롬프트·사후 재요청 둘 다 실패했다(모델 능력 한계 → OpenAI 축의 핵심 질문). 측정 중 실제 결함 7건 수정(채점 라벨 27건·NO_EVIDENCE 스트리밍 누출·청커 제목 삼킴·조항 라벨 오류·clause 미배선·평면도 도구 오선택·E2E 시드 FK) · **GraphRAG 비교(G1~G4 확장, 개발서버 실측 R24~R26)**: pgvector vs Neo4j를 병렬 표현(같은 장애 이중 적재)+클래스 분담(문서=사실·그래프=다단계 인과) 두 축으로 측정 — 인프라(incident 인과 self-FK `CAUSED_BY`·세대 기기→설비 `LINKED_TO`·RESIDENT 도구 `trace_home_device_issue`·비교 케이스 40·백엔드별 채점) 구축, 양 모델·양 백엔드 격리 유지(hard_fail 0). **3대 결론**: ①**검색 품질은 백엔드 중립**(R26 forced-backend: 양쪽 hit@k=1.0·rank≈1, pgvector ~5ms·Neo4j ~8ms 원시) — R24/R25의 pass 차이는 전적으로 도구 라우팅 아티팩트 ②**그래프 자산 활용은 모델 티어에 강하게 의존**(R25: 8B는 그래프 도구 과소 선택해 문서로 기본 라우팅, Qwen2.5-14B는 적극 선택 → 그래프 클래스 인용 81→96%) — 8B의 under-selection은 능력 상한이고 상위 모델이 뚫는다(8B 인용 규율 상한 결론과 동형) ③**Neo4j의 고유 가치는 검색 속도가 아니라 관계·다단계 인과 표현**(pgvector가 못 주는 CAUSED_BY 연쇄 근거) — 단 8B 파일럿에선 그 자산이 도구 라우팅에 막혀 회수율 낮음. 방법론 주의: 병렬 쌍 인용 지표는 백엔드 품질이 아니라 모델 도구 선호를 재므로 순수 비교엔 forced-backend 필요(R25→R26). 상세·재현은 MEASUREMENT-LOG R24~R26 |
| H15-4 | 멀티-검색 라우팅 + Qwen3.5-9B 후보 + 주차 최근접 | (인터뷰 확정 2026-07-31, 계획 `plans/resilient-hugging-ripple.md`) 복합 질의(그래프+벡터+구조화)를 LLM 자율로 멀티툴 라우팅. **P1** 주차 점유 PG 영속화([ADR-0023](adr/0023-parking-occupancy-persisted.md) — 프론트 시뮬 폐기)+RESIDENT 최근접 빈자리 도구 `find_nearest_available_parking`(공간 거리, 읽기 전용). **P2** 케이스에 복합·그래프·주차 추가 + `required_tools`(AND) 채점. **P2e** codex·cursor CLI 모델 무관 감사 후 케이스셋 동결. **P3** Qwen3.5-9B-AWQ(thinking-off) 배포 → 8B/9B/14B 동일세트 3자 측정(R28 — 라우팅·인용·지연·토큰·VRAM). **P4** 사전 승격 기준으로 파일럿 8B 유지/9B 채택 판정. 깃: GitLab 전용(GitHub 수동). OpenAI 축은 여전히 별도(키 대기) | 주차 tenant 격리·RLS·최근접 순수함수 단위테스트(CRITICAL) + 복합 PII 마스킹 게이트 + thinking 누출 스모크 + 게이트 그린 + 3자 측정표 | ✅ **완료** — P1 점유 PG SoR·최근접 도구·뷰 전환(시각 실측 통과·GitLab MR!2 머지) · P2 복합·주차 케이스 34건+`required_tools`(AND) 채점·resolve_parking(74건 gen) · P2e codex·cursor 모델무관 감사·동결 · **P3 3자 측정(R28)**: 8B(pass 59·라우팅 91.5%·인용 90%·2s) > 14B(51·83%·83%·4s), **Qwen3.5-9B는 라우팅 100%(qwen3_coder)이나 멀티모달-단일변형·thinking-off 불가(전건 폴백)·15~20배 지연으로 비적합** · **P4 결정: 8B 파일럿 유지**(14B·9B 승격기준 미달). [n] 인용 상한 최종 돌파는 OpenAI 축 잔여(키 대기). 로컬 스택 측정(원격 dev 오프라인) |

### 8.19 H16 체크리스트 (주차 점유 실데이터화)

> 근거: 사용자 요청(2026-07-31) — "주차 차량이 동/호수-차량번호-주차위치로 연결돼야 한다".
> 인터뷰 확정: 점유의 단일 출처를 DB로 전환(프론트 시뮬 폐기) · 대수 제한 없음(시뮬 산출 규칙 그대로 영속화 —
> 재실률 0.75·자기 동 근처 선호·EV/장애인면 규칙) · 외부 차량 8대·입차시각 포함(`household_id NULL` 완화 + `entry_at`) ·
> AI 어시스턴트 도구 연결("○동 ○호 차 어디?")은 **후속 작업으로 제외**.
> **불변**: 차량번호는 암호문만 저장(규칙 2) · API는 읽기 전용·MANAGER 인가(규칙 4) · RLS 표준 tenant 격리(규칙 3).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H16-1 | 점유 영속화(백엔드+웹) | ①마이그레이션: `spot_no text NULL`·`entry_at timestamptz NULL`·`household_id` NULL 완화·부분 유니크 `(tenant_id, spot_no) WHERE spot_no IS NOT NULL`([03 §4.11](03-database-design.md)) ②`seed_parking.py` 확장: 결정적 배정(고정 시드 — 규칙은 구 parking-sim과 동일, 비트 일치 불요) + 외부 차량 8대 생성 ③API: `ParkingVehicleItem`에 `spot_no`·`entry_at`·`external` 추가(dong·ho nullable) ④웹: `simulateParking` 삭제, API 데이터로 `bySpot` 구성(2D·3D·목록·필터·경과시간 유지), "점유는 시뮬레이션" 문구 제거 | 부분 유니크·RLS(CRITICAL) + 시드 멱등(재실행 개수 동일) + 게이트 그린 + 주차장 대시보드 2D/3D 시각 실측 | ✅ 완료 — 마이그레이션 `b4c5d6e7f8a9`. 시드 실측(첫마을): 주차 256면(입주민 248+외부 8)·빈 186, 2회 실행 356행 동일(멱등)·spot_no 중복 0·장애인면 배정 0·비EV 전기차면 0. 웹은 `occupancyFromVehicles`로 인덱싱만(sim PRNG 전량 삭제). 테스트 db 171·api 478·web 362. 시각 실측: 2D 면 클릭 상세(002면—401동 1103호·카니발·경과 8h28m)·3D·목록·동별 칩·콘솔 0. mypy override 1건(scripts 직접 import 관행 — 기존 5건 포함 해소) |

### 8.20 H17 체크리스트 (AI 비서 에이전트 확충 — 민원 트리아지 · 입주민 주차맵)

> 근거: 사용자 요청(2026-08-01) — "AI 비서에 에이전트로 구현: ①공지·문서 답변 ②민원성 질문이면 접수 연결 또는
> 이전 유사 민원 답변 제시, 시설·설비 고장 신고도 접수 ③빈 주차자리를 입주자 동에서 가까운 순으로, **주차위치
> 버튼 클릭 시 주차맵 표시**".
> 인터뷰 확정(2026-08-01): ①은 `search_documents`로 이미 충족 — 최근 공지 전용 도구는 추가하지 않음(8B 라우팅
> 예산) · ②는 [ADR-0024](adr/0024-assistant-inquiry-triage.md) — 판정은 도구 라우팅, 노출은 제목·분류·처리결과
> 요약만, 접수는 딥링크 프리필(AI가 INSERT 안 함) · ③ 최근접 빈자리 도구는 H15-4·H16으로 이미 충족, **신규는
> 입주민 주차맵 화면**(입주민 앱에 주차 화면 자체가 없었음).
> **불변**: 도구는 전량 읽기 전용(ADR-0007) · 민원 분류·우선순위는 사람이(ADR-0018) · 시설 정식 연결은 담당자
> 승인(H13-2) · 타 입주민 차량정보·민원 본문 미노출(규칙 2) · tenant 격리(규칙 3) · 인가는 서버(규칙 4).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H17-1 | 민원 트리아지 도구 + 접수 딥링크 | ①마이그레이션: `CREATE EXTENSION pg_trgm` ②ai-core 도구 `search_similar_inquiries`(RESIDENT — `word_similarity` 정렬, 같은 tenant `done` 건 + 본인 진행중 건, 반환은 제목·카테고리 라벨·담당자 reply 발췌 120자, 상한 5) ③`default_registry` 등록(9→10종) ④web-resident: SSE done의 `tool_path` 파싱 추가 → 도구 호출 or 폴백 시 "민원 접수하기" CTA → `/inquiries?compose=1&title=&body=` ⑤`InquiryCenter` searchParams 프리필(compose=1이면 접수 탭 + 제목·본문 초기값) ⑥골든셋 민원 케이스 + `required_tools` | tenant 격리·본인 외 민원의 작성자·본문 미노출(CRITICAL) + 도구 라우팅 회귀(골든셋 pass·라우팅률 기존 범위 내) + 게이트 그린 + 시각 실측 | ✅ 완료 — 마이그레이션 `c6d7e8f9a0b1`(pg_trgm). 도구 SQL은 `is_mine` 불리언만 내보내고 작성자·본문·동호수는 SELECT 자체를 안 한다(테스트가 SQL 문자열도 단언). **로컬 라우팅 실측(단발, ollama 8B)으로 초안 2개를 되돌렸다**: 도구 설명이 정확히 반대로 갈려(신고→평면도, "내 민원"→유사검색) 설명 앞머리를 증상 신고로 재작성, 임계 0.3→0.5(0.385짜리 무관 사례가 붙어 모델이 옳게 NO_EVIDENCE를 냄). 결과 신고 3건 중 도구 선택 2·answered 1, 경계 케이스 정정 2회 재현. 접수 CTA는 유사 민원 도구가 라우팅된 답변에만 뜬다(사용자 지시 2026-08-01로 폴백 경로 CTA는 제거 — 답을 못 준 자리에 버튼을 두지 않는다). 상세는 [ADR-0024 §실측](adr/0024-assistant-inquiry-triage.md). 골든셋 케이스 9건(IQ-01~09)은 draft·리졸버까지 완료 — **dev에서 `gen` 재생성 후 반복 측정은 후속**(로컬 gen은 문서 UUID가 달라 기존 라벨을 오염시킴). 부수 수정: `evals/adapter.mjs` READ_TOOLS에 누락돼 있던 읽기 도구 3종(H13·H15-4 누적) — 안전게이트 위양성 경로였다. 테스트 ai-core 229·db 171·web-resident 142 |
| H17-2 | 입주민 주차맵 | ①API `GET /parking/map`(RESIDENT — layout + 면별 점유 여부 **불리언만** + 본인 세대 차량의 `spot_no`·`entry_at`. 타 세대 번호판·동호수 미포함) ②`ParkingMap` 2D를 `@liviq/ui`로 승격(FloorPlanViewer 선례 — 면 상태·툴팁을 props로 일반화, admin은 어댑터로 기존 표시 유지) ③web-resident `/parking` 화면(빈/점유·본인 차 위치·추천 면 강조, `?spot=` 딥링크로 포커스) ④어시스턴트 답변의 `find_nearest_available_parking` 결과에 "주차위치 보기" CTA → `/parking?spot=<면번호>` | 타 세대 차량정보 미노출(CRITICAL) + RESIDENT 인가·tenant 격리 + admin 주차뷰 회귀 없음 + 게이트 그린 + 2D 맵 시각 실측(375px 포함) | ✅ 완료 — `GET /parking/map`(RESIDENT)은 `occupied_spot_nos`(불리언 성격의 면 번호 목록)와 본인 세대 `spot_no`·`entry_at`만 낸다 — 번호판·동호수·세대 식별자·입주민/외부 구분은 **스키마에 필드 자체가 없다**(복호 경로 없음 → 감사 로그 불필요). `ParkingMap`을 `@liviq/ui`로 승격(admin은 330→69줄 어댑터, 툴팁·dim 판정은 앱 책임 — ui는 PII를 모른다). 입주민 화면은 폭 ~430px라 볼 면이 정해진 진입은 3× 확대로 열고 포커스(`initialZoom`). 면 번호는 도구 카드 quote에서만 파싱한다(모델이 본문에 쓴 숫자는 근거가 아님). 시각 실측: "빈자리 186면 / 전체 442면"·"내 차: 208면 · 8시간 33분 전 입차"·`?spot=012,034` 보라 점선 강조·admin 툴팁(번호판·동호수) 회귀 없음. 테스트 api 483·ui 50·web-admin 362·web-resident 153. 부수 수정: `parseViewBox("")`가 `[NaN,0,0,0]`을 반환하던 기존 버그, 프론트 `Citation.documentId` 타입이 서버(도구 카드 null)와 어긋나던 것 |

### 8.21 H18 체크리스트 (에이전트 심화 — 계획·멀티턴·되묻기·구조화 응답)

> 근거: 사용자 평가(2026-08-01) — "답이 단조롭다. 에이전트가 아니라 단순 챗봇 같다. 다른 에이전트
> UI/UX를 참고해 디자인하고, 프롬프트·실행 설계도 다시 하라."
> 인터뷰 확정: 실행 구조는 **직접 구현 유지 + 계획 단계**(LangChain·LangGraph 미도입) · 멀티턴
> 컨텍스트와 **명확화 되묻기 둘 다** · 응답은 구조화 블록·맥락 기반 다음 행동·도구 과정 노출·길이
> 완화 · UI 레퍼런스는 **Perplexity 계열**(출처 우선·단계 표시·후속 질문). 상세: [ADR-0025](adr/0025-agent-depth-plan-clarify-structured.md).
> **불변**: 마스킹 fail-closed(규칙 2)는 히스토리에도 적용 · 화면 숫자는 도구 확정값 그대로(규칙 5·8 —
> LLM이 표를 재작성하지 않음) · 근거 없는 답변 금지(규칙 1, 되묻기는 저촉 아님) · SSE는 **4종 유지**,
> 필드만 additive 확장.

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H18-1 | 대화 컨텍스트 + 되묻기 | ①`answer_question(question, history=...)` — 직전 3턴 답변 본문만(턴당 400자 상한), 도구 결정·최종 답변 turn 양쪽에 주입, `ensure_masked` 통과 ②히스토리 있으면 답변 캐시 우회 ③특수 도구 `ask_clarification` — 실행 대신 `DoneEvent(status="clarify")`로 즉시 되묻고 종료, 직전 턴이 clarify면 스펙에서 제외(연속 금지) ④api가 대화 히스토리를 로드해 전달 ⑤web-resident가 `clarify` 상태를 되묻기 말풍선으로 렌더 | 히스토리 마스킹(CRITICAL) + 연속 되묻기 차단 + 캐시 우회 + 멀티턴 골든셋 케이스 + 게이트 그린 | ✅ 완료 — clarify 종료 분기를 도구 루프 안 `messages.append` **직전**에 두어 근거 조립·`chat_stream`·`verify_citations`가 코드상 도달 불가(테스트가 `streams == []`로 고정). 연속 차단은 api가 직전 assistant 메시지의 `status`를 읽어 `allow_clarify=False`로 전달 + 오케스트레이터 이중 방어. DB 정렬 함정 발견 — 같은 요청의 user/assistant가 동일 `created_at`이라 `(created_at desc, role asc)`로 순서 보장. 테스트 ai-core 266·api 493·web-resident 166
| H18-2 | 계획 turn + 구조화 응답 | ①루프에서 **무-도구 turn을 계획으로 재해석**(1회 한정), `MAX_TOOL_STEPS` 3→4, `AGENT_SYSTEM_PROMPT`에 계획 지시 ②`ToolCard.data` 추가 — 관리비 항목표·주차 자리목록·시설 상태를 구조화 페이로드로(LLM은 재작성하지 않음) ③SSE additive: `status.tool`·`citation.data`·`done.suggestions`·`done.status="clarify"` ④다음 행동 제안은 `tool_path` 기반 **코드 규칙**(LLM 호출 0) ⑤`packages/api-types` 재생성 | 무한 루프 없음(계획 1회 상한) + 숫자 재작성 0(도구 값과 화면 값 일치 테스트) + 기존 SSE 소비자 하위호환 + 게이트 그린 | ✅ 완료 — 무한 루프 방지 이중(계획 카운터 1 + `range(MAX_TOOL_STEPS)`), "항상 계획만 뱉는 LLM"으로 결정 turn 2회 종료를 테스트가 고정. `data`가 LLM에 안 가는 것은 **나간 요청 본문 전량 수집** 후 고유 키 부재로 단언(공허한 통과 방지로 본문 비어있지 않음도 확인). SSE 4종·stage 3종 불변, 새 필드는 기본값으로 하위호환
| H18-3 | Perplexity형 응답 UI | ①답변 상단 출처 우선 배치·단계 표시(어떤 도구를 왜 썼는지 접이식) ②구조화 블록 렌더러(표·목록·상태 카드) ③맥락 기반 후속 질문 칩(고정 추천 아님) ④되묻기 UI ⑤375px·다크 대비·키보드 접근 | 시각 실측(375px 포함) + a11y(색 단독 전달 금지·포커스) + 기존 화면 회귀 없음 | ✅ 완료 — 위계는 답변 과정(접힘 `<details>`) → 출처 스트립(가로 스크롤) → 배지 → 본문 → 구조화 블록. 칩↔CTA 중복은 **CTA를 남기고 칩을 제거**(칩은 질문을 보내는 물건이라 "민원 접수하기"를 누르면 폼이 아니라 설명이 나온다). 시각 실측(375px): 관리비 표 합계 176,601원·전월 대비 문구, 주차 ①217면 28m, 민원 사례 1건, 되묻기 말풍선(배지·출처·칩·피드백 전부 없음·입력창 포커스), 출처 스트립 가로 오버플로 0px. 미확인: `facility_status` 블록은 입주민 역할로 도달 불가(admin 파서가 `citation.data`를 안 읽음 — 후속)
| H18-4 | 프롬프트 재설계 + 측정 | ①`ANSWER_SYSTEM_PROMPT` 길이 지시 → 형식 지시로 교체(인용·NO_EVIDENCE 규칙 불변) ②`AGENT_SYSTEM_PROMPT` 계획·되묻기 지시 ③골든셋에 멀티턴·되묻기 케이스 신설 ④dev 3회 측정 — 인용률·도구 선택·되묻기 오남용률 | R29 대비 인용·도구 선택 회귀 없음 + 되묻기 오남용(단순 질의에 clarify) 10% 미만 + 측정 기록 | ⚠️ **부분 완료** — 되묻기 오남용 2.3~5.7%로 기준 충족·hardfail 0·복합 완전호출 유지. 다만 **인용률 완료 기준 미충족**: 동일 82건 중위 87.3% → 82.3%. 가설(목록 항목 인용 누락)을 세워 규칙 2에 명시하고 재측정했으나 **기각**(79.7·86.1%로 무변화). 더 정확한 관찰은 중위 하락이 아니라 **분산 증가**(2.5pp → 6.4pp, 5회 중 2회는 H17 범위 내). 형식 지시는 사용자 요구 UX의 근간이라 롤백하지 않고, 인용 상한 돌파는 기존 잔여 과제(상위 모델·OpenAI 축)로 이관. 상세 [R30·R30b](../evals/results/rag500/MEASUREMENT-LOG.md). 프론트 마크다운 방어(`- ` 목록만 렌더·잔여 기호 제거, 마스킹 표기 보존)와 채점기 확장(clarify behavior·오남용률·원질문 에코 검출) 포함

| H18-5 | 사용자 지적 반영(2026-08-01) | ①**출처 중복 제거** — 도구 카드는 서버가 `(source_kind, quote)`로(같은 도구 반복 호출이 출처 N개로 뜨던 문제), 문서 인용은 프론트가 `documentId`로 묶어 표시(청크 단위 `[n]` 번호 체계는 불변) ②**되묻기 문장을 코드가 생성** — 인자를 자유 문장에서 `missing`+`context`(항목 이름)로 교체, 모르는 항목은 **낱말을 문장에 넣지 않는** 일반 문구로 폴백 ③CTA(민원 접수·주차위치)와 피드백 버튼을 한 줄로, 피드백은 우측 정렬 ④피드백은 아이콘만(`aria-label`·`title`로 접근 가능한 이름, 32×32) ⑤**폴백 경로의 접수 버튼 삭제** — 답을 못 준 자리에 버튼을 두지 않는다 | 접근 가능한 이름 회귀 가드 + 카드 중복 제거 테스트 + dev 실측 + 게이트 그린 | ✅ 완료 — dev 실측으로 `get_fees` 2회 호출 시 출처 2건(도구 카드 1+문서 1)임을 확인. 되묻기 문구는 1차 수정 후에도 모델이 항목 대신 주제어를 넣어 `"온수에 대해 온수를…"`로 무너져(dev 실측) 폴백에서 모델 낱말을 아예 제거. 시각 실측(375px): 한 줄 배치·아이콘 버튼·폴백 버튼 없음 |

### 8.22 H19 체크리스트 (AI 비서 운영 도구 확충 — 공지 동 타게팅 · 관리자 집계 · 시나리오 케이스셋)

> 근거: 사용자 요청(2026-08-01) — 시나리오 자료 2종. **(A)** `260725공지사항정리_질문시나리오추가완료.xlsm`
> "질문시나리오" 탭 6건(Q08-01~06) + 구두 추가 5건(관리비 세대평균 비교 · 커뮤니티 놀이터 이용시간/사용료 ·
> 주민공동시설 이용시간 · 관리비+납부규정 하이브리드 · 우리집 6월 관리비). **(B)** `LLM_질의응답_시나리오_0801_손종혁.xlsx`
> — 첫마을4단지 디지털트윈 LLM 질의응답 시나리오(관리자 3 · 입주자 3 + 공통 규칙). B 원문은 별도 데모
> (FastAPI+SQLite+주차 시뮬)를 전제로 쓰였고, **LIVIQ 본체로의 이식이 이번 범위**다.
> 갭 분석(착수 전 확인 완료): 현재 도구 12종 중 RES-2(`find_nearest_available_parking`)·RES-3(`find_in_floor_plan`)는
> 충족, **RES-1(내 차 위치)·ADM-1(외부차량 장기주차)·ADM-2(민원 현황 집계)는 도구 자체가 없다**. Q08-01·04는
> 8월 공지 86건 시드([`apps/api/scripts/data/notices_demo.py`](../apps/api/scripts/data/notices_demo.py) — 승강기·저수조·전기설비는
> 401~405 **동별 5건씩 본문이 거의 동일**)가 유사도만으로 구분되지 않아 타 동 일정을 답할 위험이 있다.
> Q08-02("이번 달")는 8B 상대날짜 매핑 한계(R23 #3 기록)라 도구가 아니라 케이스·측정 문제, Q08-03·05·06과
> 커뮤니티 시설 이용시간은 **경로는 이미 있고 케이스만 없다**.
> 인터뷰 확정: 공지 동 타게팅은 **검색 필터**로(도구 인자 추가는 8B 라우팅 예산을 쓴다 —
> [`tools/notices.py`](../packages/ai-core/src/ai_core/tools/notices.py) 주석의 R22 계열 실패) · 관리자 도구는 **집계·상태만**
> 노출(민원 본문·작성자·번호판 비노출, H17-1 선례) · **입주민 앱은 3D로 확장하지 않는다** — B문서 공통 규칙의
> "화면 연동(3D 카메라 이동·비콘)"은 이미 있는 관리자 화면에 그대로 두고, 입주민은 H17-2의 2D 주차맵 +
> `?spot=` 딥링크로 충족시킨다(**입주민 3D는 범위 밖 — 백로그**, H19에 3D 작업 단위 없음) ·
> 단지 평균 관리비 비교는 **채택**(같은 면적대 평균만 · 개별 세대 금액 미노출 · 표본 수 하한 미달 시 거부).
> 상세: [ADR-0026](adr/0026-assistant-ops-tools-and-dong-targeting.md).
> **불변**: 도구는 전량 읽기 전용(규칙 8 · [ADR-0007](adr/0007-readonly-tool-agent.md)) · 출처 없는 답변 금지(규칙 1) ·
> 타 세대·타 입주민 개인정보 미노출(규칙 2 — B문서 "공통 규칙 · 권한 분리"와 동일 취지) · tenant 격리(규칙 3) ·
> 인가는 서버(규칙 4) · **관리비는 확정 업로드 데이터가 단일 출처이고 AI는 계산하지 않는다**(규칙 5 — 평균 비교도
> 조회된 집계값을 **제시**하는 것이지 계산이 아니다).

| 순서 | 작업 | 산출물 | 완료 기준 | 상태 |
|------|------|--------|-----------|------|
| H19-1 | 공지 동 타게팅 검색 | (Q08-01·04의 근간 — 나머지 공지 케이스가 여기에 의존) ①`ToolContext`에 로그인 세대의 동을 추가(LLM이 지정할 수 없는 격리 값 — 기존 `tenant_id`·`visibilities`와 동일 취급, api가 요청별 주입) ②`_SEARCH_SQL`([`rag/retrieval.py`](../packages/ai-core/src/ai_core/rag/retrieval.py))의 notice 분기에 대상 동 조건 추가 — `notices.target_buildings`(JSONB, `buildings.id` **문자열** 배열 · 배열이 아니면 전체동 — SQL NULL과 jsonb `null` 둘 다 실재)를 이미 조인하고 있으므로 컬럼 신설 없이 필터/감점 ③관리자 역할·동 미상(비입주민)일 때는 필터 미적용(전 동 검색 유지) ④골든셋에 동별 공지 케이스 | **타 동 공지 인용 0건**(동별 5건 세트에 대해 로그인 동 외 청크가 근거로 들어오지 않음) + 전체동 공지(`target_buildings` NULL) 회귀 없음 + tenant 격리·RLS 회귀 없음(CRITICAL) + 게이트 그린 | ✅ 완료 — 실 PG 테스트가 함정 둘을 잡았다: 전체동 판정은 `IS NULL`로 부족(작성 경로가 파이썬 `None`을 넣으면 JSONB엔 jsonb `null`로 저장 — `jsonb_typeof <> 'array'`로 판정)·**답변 캐시 tenant 키에 동 세그먼트 필수**(빼면 401동 답변이 403동에 재생돼 SQL 필터 무력화). 관리자 면제는 세대 배정 여부가 아니라 **역할로 판정**(`RESIDENT_ROLES` 재사용 — 세대 있는 겸직 관리자가 조용히 자기 동으로 좁혀지는 회귀를 테스트로 고정). 임베딩 동일 청크로 필터만 분리 검증 + 뮤테이션 확인. ④동별 케이스는 V2-QA-0331·CX-R14로 draft 완료(dev `gen`·측정은 H19-5). 상세 [ADR-0026 결정 1](adr/0026-assistant-ops-tools-and-dong-targeting.md) |
| H19-2 | 내 차 위치 도구(RES-1) | ①ai-core 도구 `find_my_vehicle`(RESIDENT — 본인 세대 등록차량의 주차면 번호·입차 경과시간·본인 동 승강기까지의 거리. **타 세대 번호판·동호수는 반환 필드 자체를 두지 않는다** — H17-2 `GET /parking/map` 선례) ②`default_registry` 등록(12→13종) ③답변의 "주차위치 보기" CTA 재사용 → `/parking?spot=<면번호>`(H17-2 딥링크, 신규 화면 없음) ④골든셋 RES-1 케이스 | 타 세대 차량정보 미노출(CRITICAL — 반환 스키마·SQL 문자열 단언, H17-1 관례) + RESIDENT 외 역할 비노출 + tenant 격리 + 미등록 차량 시 폴백 + 게이트 그린 | ✅ 완료 — `plate_enc`는 SELECT 자체를 안 한다(SQL 문자열 단언). 번호판 미반환은 의도적 결정(규칙 2 — 차종+면 번호로 충분, docstring 기록). 전부 미주차는 note가 아니라 **카드**(확정 근거 — ⓪ 계약) + 빈자리 안내. CTA는 `isParkingAnswer` 술어로 두 주차 도구 공용화. geometry 파싱 헬퍼 공개 승격. ④골든셋 RES-1 케이스는 H19-5로 이관(`parking:mine` 리졸버가 dev DB 필요). ai-core 307·web-resident 209 그린 |
| H19-3 | 관리자 운영 도구 2종 | ①`find_longterm_parking`(`FACILITY_ROLES` = MANAGER·FACILITY — 입주민 미등록 차량(`household_id IS NULL`) 중 `entry_at` 경과가 임계 초과인 면, 경과 내림차순. 번호판 비노출) ②`summarize_inquiries`(MANAGER·STAFF — 기간·동·상태별 **집계 수치** + 미처리 우선 목록(제목·분류·상태·경과만). 민원 **본문·작성자 미노출** — H17-1 `search_similar_inquiries` 선례) ③`default_registry` 등록(→15종) ④골든셋 ADM-1·ADM-2 케이스 + `required_tools` | **역할 밖 호출 차단**(RESIDENT에게 스펙 비노출 + 실행 경로 거부, CRITICAL) + 본문·작성자·번호판 미노출(CRITICAL) + tenant 격리 + **8B 라우팅 회귀 없음**(도구 3종 추가 후 기존 골든셋 라우팅률이 R30 범위 내 — 회귀 시 도구 설명 경계 재작성, H17-1 실측 관례) + 게이트 그린 | ✅ 완료(라우팅 측정 제외 — H19-5) — `summarize_inquiries`는 `OFFICE_ROLES`(MANAGER·STAFF) 신설: FACILITY_ROLES를 안 쓴 이유는 민원이 사무소 업무 + FACILITY는 H7-2 제거 잔존 값(ADR-0026). 거부 시 쿼리 자체 미발행을 테스트가 단언. 미처리 목록 머리말에 건수 미표기(상한 5로 잘린 수가 집계와 어긋나는 것 방지). 빈 입력 `ROLLUP` 총계 행·`CAST(:dong AS text)` NULL 분기는 실 PG로 확인. 미처리=received·assigned·reopened(처리중 제외 — `_PENDING_STATUSES` 한 줄 조정 가능). ④골든셋 ADM 케이스는 H19-5 이관 |
| H19-4 | 관리비 비교 + 다음 점검 노출 | ①**단지 평균 비교**(채택 — [ADR-0026](adr/0026-assistant-ops-tools-and-dong-targeting.md) 결정 3): `get_fees` 결과에 **같은 단지·같은 면적대**의 같은 월 평균 **집계값**을 덧붙인다 — 개별 세대 금액은 어떤 경로로도 미노출 · **표본 수 하한 k 미달이면 비교를 거부하고 본인 세대 값만 답한다**(소표본에서 특정 세대 금액이 역산되는 것을 막는다 · k의 구체 값은 착수 시 데이터 분포를 보고 정한다) · AI는 계산하지 않고 확정 업로드 데이터의 조회된 집계값을 제시한다(규칙 5) ②ADM-3의 **다음 정기점검 예정일** 노출 — `get_overdue_checks`는 임박·초과만 내므로 착수 시 현행 스키마·도구 반환 필드를 먼저 확인하고 부족분만 보완 ③골든셋 케이스(관리비 세대평균 · ADM-3 설비 이력+다음 점검) ④**`V2-QA-0337` 라벨 전환** — 현재 `label_source=fallback:absent`(도구 부재라 폴백이 정답)로 라벨돼 있으나 ①이 구현되면 **평균 비교 답변이 정답**이 된다. `label_source`·`acceptable_tools`·`expected_facts`를 갱신하고(`forbidden_content`의 "타 세대 금액 노출·임의 평균 계산"은 유지) **신규 리졸버 필요 여부를 함께 판정한다**(집계값은 dev DB에서 뽑아야 하므로 `gen_labels.py`에 리졸버 추가가 필요할 수 있음). **이 전환은 H19-5의 `gen` 재생성보다 먼저 끝나야 한다** — 라벨이 낡은 채로 재생성하면 구현된 기능이 실패로 채점된다 | 표본 수 하한 미달 시 비교 거부(본인 세대 값만 답함) + 개별 세대 금액 미노출(CRITICAL) + tenant 격리(집계는 같은 단지 안에서만) + 관리비 수치는 확정 업로드 데이터 그대로(규칙 5 — AI 재계산 0) + 게이트 그린 | ✅ 완료 — ①평균은 새 도구가 아니라 `get_fees` 결과에 붙는다(도구 수 = 8B 라우팅 예산). 하한 **k=10**(322세대·소수 평형도 수십 세대 — 역산 불가·비교 거의 항상 성립). 평형 키는 `unit_type_label` prefix(seed_fees_demo와 동일 규칙), 미상이면 CTE 조인 불성립 = 자연 생략. `data.peer`는 성립 시에만 키 존재. 실 PG 3건: 평균 정확성 + **타 평형·타 단지 미혼입** + 하한 미달·geometry 없음 ②다음 예정일은 `get_overdue_checks` 반환에 추가(get_facilities는 라우팅 역전 위험 — 실측 후 판단). dev는 `next_check_at` 전 NULL이 시드 불변식이라 "예정일 미등록" 문구 고정(규칙 1) ④V2-QA-0337 `fallback:absent`→`fees:2026-06` 전환 완료(리졸버 미추가 — expected_facts는 채점 게이트가 아니라 검수 필드, 평균 로직 이중 구현 드리프트 회피). 화면 `peer` 렌더는 후속 |
| H19-5 | 케이스셋 v2.1 + dev 재측정 | ①신규 시나리오 케이스 — `V2-QA-0331`~`0337` + `CX-R13`~`R15`(별도 세션에서 [`cases-draft.csv`](../evals/fixtures/chetmaeul-v2/cases-draft.csv)에 추가 완료) + H19-2·H19-3 도구 케이스. **선행: H19-4의 `V2-QA-0337` 라벨 전환**(폴백 → 평균 비교 답변 · 리졸버 추가 시 그것까지) — 낡은 라벨로 `gen`을 돌리면 구현된 기능이 실패로 채점된다 ②**선행: 공지 데모 시드의 dev 실행**(`notices_demo.py` 공지 86건은 `ebc08a7`로 main에 있으나 **시드 실행은 미완** — 데이터 반영이 사용자 판단이라 보류됐다. 시드 없이는 동 타게팅·8월 공지 케이스가 성립하지 않음) ③dev DB에서 `gen_labels.py gen` 재생성(로컬 gen은 문서·시설 UUID가 dev와 달라 라벨을 오염시킴 — R23 관례) ④3회 측정 후 MEASUREMENT-LOG에 회차 기록 | 신규 케이스 라벨 정합(리졸버 미해결 0) + hard_fail 0 + 라우팅률 R30 범위 내 + **인용률 비교는 3회 이상 중위로만**(CLAUDE.md 규율 — 단발 회차로 증감 판정 금지) + 측정 기록 커밋 | ⬜ 대기 |

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
