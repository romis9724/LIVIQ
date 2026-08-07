# 02. 디렉토리 구조 설계

> 아키텍처: [01-architecture.md](01-architecture.md) · 인덱스: [README.md](README.md)
> 스택: Turborepo + pnpm(TS) · uv workspace(Python) · Next.js(웹) · FastAPI + SQLAlchemy + arq(백엔드) · PostgreSQL/pgvector · Neo4j

> 본 문서는 **목표 구조**다. 현재 구현 현황은 [CLAUDE.md](../CLAUDE.md) '구조' 절 참조.

## 1. 원칙

- **기능/도메인 단위 구성** (파일 타입별 X). 고응집·저결합.
- **공유 코드는 `packages/`**, 실행 단위는 `apps/`.
- **타입·스키마는 단일 출처**: DB 모델은 `packages/db`(SQLAlchemy), 웹↔api 계약은 FastAPI OpenAPI에서 생성한 `packages/api-types`(TS)를 웹이 import.
- 파일 200~400줄 표준, 800줄 상한. 큰 모듈은 분할.

## 2. 모노레포 최상위

```text
LIVIQ/
├── apps/
│   ├── web-resident/      # 입주민 반응형 웹/PWA (Next.js, TS)
│   ├── web-admin/         # 관리자 콘솔(MANAGER·STAFF + SYS_ADMIN 뷰) (Next.js, TS)
│   ├── api/               # FastAPI (도메인 API + BFF + AI 오케스트레이션 진입, Python)
│   └── ai-worker/         # arq 워커 (인제스트/OCR/임베딩/평가/graph-sync, Python)
├── packages/
│   ├── ai-core/           # RAG·오케스트레이션·LLM 어댑터·토큰예산 (Python, 프레임워크 비의존)
│   ├── db/                # SQLAlchemy 모델·Alembic 마이그레이션·RLS·시드 (Python)
│   ├── api-types/         # FastAPI OpenAPI → openapi-typescript 생성물 (TS, 웹이 import)
│   ├── ui/                # 공용 React 컴포넌트·디자인 토큰 (web 공유, TS)
│   ├── config-eslint/     # 공유 ESLint (TS)
│   └── config-ts/         # 공유 tsconfig (TS)
├── docs/                  # 설계 문서 (본 디렉토리)
├── refs/                  # 경쟁/참고 자료 (추출 이미지)
├── tests/
│   ├── e2e/               # Playwright (크로스 앱 시나리오)
│   └── ai-eval/           # 골든셋·AI 평가 하네스
├── infra/
│   ├── docker-compose.yml # 로컬 개발 인프라 (현존 — pg16+pgvector·redis·minio·neo4j)
│   ├── compose.prod.yml   # 운영 배포 (현존 — profiles: data/app/web)
│   ├── Caddyfile          # web tier 리버스 프록시·TLS 종단 (현존)
│   └── env.prod.example   # 배포 env 계약 placeholder (실값 infra/env.prod는 gitignore)
├── .github/workflows/     # CI/CD
├── turbo.json
├── pnpm-workspace.yaml
├── pyproject.toml         # uv workspace 루트 (members: apps/api·ai-worker·packages/ai-core·db)
├── package.json
├── CLAUDE.md              # 프로젝트 가이드 (루트, Claude Code 자동 로드)
└── README.md             # 기획/계획서
```

> 앱 4종의 `Dockerfile`은 **각 앱 디렉토리에 현존**한다([api](../apps/api/Dockerfile)·[ai-worker](../apps/ai-worker/Dockerfile)·[web-resident](../apps/web-resident/Dockerfile)·[web-admin](../apps/web-admin/Dockerfile), 제외 규칙은 루트 [`.dockerignore`](../.dockerignore)). uv workspace(단일 lock) + pnpm workspace 구조상 앱 디렉토리만으로는 빌드 불가 — **빌드 컨텍스트는 레포 루트**, Dockerfile은 앱 디렉토리에 둔다.

> `mcp/`(레포 실존): Python 프로토타입 **동결** — 신규 AI 기능은 `packages/ai-core`([ADR-0008](adr/0008-freeze-mcp-prototype.md)). 백엔드가 Python으로 통일되어 mcp 코드는 **참고·복사·개작** 대상으로 승격([ADR-0013](adr/0013-python-backend.md)).

## 3. `apps/web-resident` (Next.js, 기능 단위)

```text
web-resident/
├── src/
│   ├── app/                       # App Router (라우트=화면)
│   │   ├── (auth)/login/
│   │   ├── assistant/             # AI 생활 비서 (핵심)
│   │   ├── notices/
│   │   ├── inquiries/             # 민원/하자
│   │   ├── fees/                  # 관리비 조회+AI 설명
│   │   ├── me/                    # 내 활동
│   │   └── layout.tsx
│   ├── features/                  # 기능별 (UI+훅+API클라이언트)
│   │   ├── assistant/
│   │   │   ├── components/        # ChatPanel, CitationCard, FeedbackButtons
│   │   │   ├── hooks/             # useAssistantStream
│   │   │   └── api.ts
│   │   ├── inquiries/
│   │   └── fees/
│   ├── components/                # 화면 공용 (ui 패키지 외)
│   ├── lib/                       # fetcher, auth client, format
│   └── styles/                    # tokens.css, global.css
├── public/                        # manifest.json, icons (PWA)
├── next.config.mjs
└── package.json
```

> `web-admin`도 동일 패턴. 라우트: `assistant/`(MANAGER 첫 진입 AI 비서 — [ADR-0028](adr/0028-admin-assistant-home.md)), `inquiry-status/`(민원현황 — 구 `dashboard/`), `inquiries/`, `notices/`, `documents/`, `facilities/`, `fees/`(엑셀 업로드), `residents/`(가입 승인·명부), `staff/`, `parking/`, `twin/`, `settings/`, `system/`(SYS_ADMIN). AI 검수 큐 화면은 H8-7에서 제거됐다([ADR-0015](adr/0015-notice-board-replaces-ai-draft.md) 개정 노트).

## 4. `apps/api` (FastAPI, 도메인 라우터)

```text
api/
├── app/
│   ├── main.py                    # FastAPI 앱 조립 — credentials CORS(웹 출처)·라우터 등록
│   ├── config.py                  # env 검증(Pydantic Settings), 시크릿 로더
│   ├── deps.py                    # 공통 의존성 (세션 인증·역할 가드·테넌트 세션·LLM/그래프/스토리지/큐 주입)
│   ├── routers/                   # 도메인 경계 — auth·onboarding·approvals·staff·roster·admin_tenants·households·codes·documents·notices·inquiries·fees·facilities·floor_plans·twin·parking·assistant·dashboard·notifications·ai_config·ai_reindex
│   ├── schemas/                   # 요청·응답 Pydantic 모델 (→ OpenAPI, 라우터와 1:1 파일)
│   ├── session.py · password.py · auth_tokens.py · invites.py · mail.py   # 인증·계정 헬퍼
│   ├── pii.py · audit.py · rate_limit.py · answer_cache.py               # 횡단 관심사(암복호·감사·레이트 리밋·정확 캐시)
│   └── fees_excel.py · facility_suggest.py · facility_code.py · outbox.py · accounts.py …  # 도메인 헬퍼
├── scripts/                       # 시드·운영 스크립트 (seed_demo.py·seed_parking.py·bootstrap_sys_admin.py·export_openapi.py 등)
├── tests/                         # pytest (라우터 단위 + 인가·격리 CRITICAL 게이트)
├── pyproject.toml
└── package.json                   # turbo 태스크 연결 (lint=ruff·typecheck=mypy·test=pytest)
```

규칙:
- 라우터 = 도메인 경계. 그 아래 서비스·리포지토리 **계층은 두지 않는다** — 라우터가 `packages/db` 모델·세션을 직접 쓰고, 재사용 로직만 `app/` 루트의 **flat 헬퍼 모듈**로 뽑는다(`pii.py`·`fees_excel.py`처럼). 계층을 미리 만들지 않는 쪽이 파일럿 규모에 맞다(YAGNI).
- 입력은 라우터에서 Pydantic v2로 검증. 외부(LLM·스토리지·큐)는 `deps.py`가 주입하는 어댑터 뒤로 숨김(테스트 모킹 용이). ERP 어댑터는 **미구현**(도입 시 신설 — [ADR-0006](adr/0006-fees-excel-upload-source.md)).

## 5. `packages/ai-core` (Python, 프레임워크 비의존)

```text
ai-core/
├── src/ai_core/
│   ├── orchestrator.py            # 에이전트 루프(계획 turn·스텝 상한·되묻기 종료)→생성→후처리
│   ├── tools/                     # 도구 레지스트리(17종) — registry.py(Tool·ToolCard·ToolContext) + library.py(조립)
│   │                              #   + clarify·floor_plan(+parser)·inquiries·notices·parking·fees_common·fees_compare·trace_home_device
│   │                              #   전부 읽기 전용, 인자 Pydantic 검증·tenant/소유권은 코드가 강제
│   ├── rag/                       # 청킹(chunking)·벡터검색(retrieval)·프롬프트 빌더(prompt)
│   ├── graph/                     # Neo4j typed 클라이언트·설정 (raw Cypher 금지)
│   ├── llm/                       # OpenAI-호환 클라이언트(env로 프로바이더 교체), 토큰 카운트
│   ├── budget/                    # 컨텍스트 예산·청크 선택 ([08])
│   ├── masking/                   # PII 마스킹/가명화 + fail-closed 게이트 (api와 공유)
│   ├── parking/                   # 주차면 기하(거리·코어 좌표) — 주차 도구가 사용
│   ├── citations.py               # 인용 실재 검증
│   ├── confidence.py              # 신뢰도 산출·폴백 판정
│   ├── history.py                 # 멀티턴 히스토리(직전 3턴) 구성
│   ├── suggestions.py             # 후속 질문 칩(질문형만)
│   ├── synonyms.py                # 생활어→표준어 질의 확장(임베딩 텍스트 한정)
│   ├── fee_explain.py             # 관리비 설명 전용 경로(/fees/explain)
│   └── config.py · backend_config.py  # LLM·임베딩 env 검증(fail-closed) + DB(`ai_backend_config`) 우선·env 폴백 병합
├── pyproject.toml
└── package.json                   # turbo 태스크 연결 (lint=ruff·typecheck=mypy·test=pytest)
```

> FastAPI/Next에 의존하지 않음 → 테스트·재사용·서비스 분리(ADR-4) 용이.
> 정확 캐시는 ai-core가 아니라 **api**에 있다(`apps/api/app/answer_cache.py`) — 캐시는 에이전트 앞단(요청 경계)에서 Redis로 판정하기 때문([01 §5.2](01-architecture.md)). 의도분류 전용 모듈도 없다 — 도구 선택이 그 역할을 흡수했다([ADR-0007](adr/0007-readonly-tool-agent.md)).

## 6. `packages/db` (SQLAlchemy + Alembic)

```text
db/
├── src/liviq_db/
│   ├── models/                    # 도메인 묶음별 SQLAlchemy 2.0 async 모델 (tenants·users·documents(+ContentChunk)·
│   │                              #   conversations·inquiries·notices·facilities·fees·parking·plans·codes·ops·base)
│   ├── engine.py                  # 엔진·세션 팩토리(tenant 컨텍스트 SET LOCAL)
│   ├── runtime_roles.py           # 접속 롤 계약(liviq_app·liviq_worker — [03 §5.1](03-database-design.md))
│   ├── codes_seed.py · facility_systems.py   # 기본 코드·시설 계통 시드 데이터
│   ├── config.py
│   └── __init__.py                # 엔진·세션·모델 export
├── alembic/                       # 마이그레이션 (env.py + versions/) — **RLS 정책·GRANT SQL도 여기**(별도 rls/ 디렉토리 없음)
├── alembic.ini
├── pyproject.toml
└── package.json                   # turbo 태스크 연결 (lint=ruff·typecheck=mypy·test=pytest)
```
상세 스키마: [03-database-design.md](03-database-design.md).

## 7. `packages/api-types` (생성물, TS)

웹↔api 타입 공유는 별도 DTO 패키지가 아니라 **FastAPI가 발행하는 OpenAPI 스키마**를 단일 출처로 삼는다. `openapi-typescript`로 변환한 생성물을 웹이 import한다(손으로 편집하지 않음 — api 스키마 변경 시 재생성).

```text
api-types/
├── src/
│   └── generated.ts               # openapi-typescript 출력 (수정 금지)
└── package.json                   # 생성 스크립트 (openapi-typescript)
```

> 서버 경계 검증은 Pydantic(api), 웹 폼 검증은 Zod로 각각 유지. 응답 envelope·역할·위험도 등 계약 타입은 OpenAPI에서 흘러온다.

## 8. 네이밍 규칙 (사용자 web 규칙 준수)

- 컴포넌트: `PascalCase` (`CitationCard.tsx`)
- 훅: `useXxx` (`useAssistantStream.ts`)
- 디렉토리/CSS: `kebab-case`
- 상수: `UPPER_SNAKE_CASE` / 타입·인터페이스: `PascalCase`
- Python 모듈·함수·변수: `snake_case`, 클래스: `PascalCase` (PEP 8 준수)
- DB 테이블·컬럼: `snake_case`
- 자산(refs 이미지): `kebab-case`

## 9. 환경/설정

- 시크릿은 코드에 두지 않음. `.env`(로컬)·시크릿 매니저(운영). [`.env.example`](../.env.example)(레포 루트) 제공.
- env는 부팅 시 검증(누락 시 즉시 실패) — 서버는 Pydantic Settings(`apps/api/app/config.py`), 웹은 Zod(`apps/web-*/src/config`). 검증 소유는 패키지별([09 §2](09-implementation-harness.md)).
- 패키징: Python은 **uv workspace**(루트 `pyproject.toml`의 members로 단일 lock), 각 Python 패키지의 얇은 `package.json`이 turbo 태스크(lint=ruff·typecheck=mypy·test=pytest)를 루트 pnpm 명령에 연결. 웹/TS는 pnpm workspace 그대로.
- 로컬: [`infra/docker-compose.yml`](../infra/docker-compose.yml) — postgres+pgvector, redis, minio, neo4j([ADR-0009](adr/0009-neo4j-in-mvp.md)).
- **운영 배포**: 앱 4종(`api`·`ai-worker`·`web-resident`·`web-admin`)을 컨테이너 이미지로 빌드해 GHCR에 게시하고, [`infra/compose.prod.yml`](../infra/compose.prod.yml) **단일 파일 + profiles(`data`/`app`/`web`)** 로 3-tier VM에 배포([ADR-0020](adr/0020-container-deploy-3tier-vm.md)). 배포 env 계약은 [`infra/env.prod.example`](../infra/env.prod.example)(compose `--env-file` 치환 소스 겸 컨테이너 `env_file` — 실값 `infra/env.prod`는 gitignore). 로컬 스모크는 같은 파일을 1호스트에서 3프로필 동시 기동으로 검증했고([09 §2·§8.13](09-implementation-harness.md)), 개발 루프 자체는 네이티브 유지.
- **웹 env는 빌드타임 인라인**: `NEXT_PUBLIC_*`은 Next 빌드 시 번들에 박히므로 **이미지 빌드 인자로 주입**된다(런타임 교체 불가). 따라서 API 주소는 환경별 절대 URL이 아니라 **상대경로 `NEXT_PUBLIC_API_BASE_URL=/api`** 로 고정하고, 오리진 차이는 web tier 리버스 프록시가 흡수한다(same-origin `/api` 프록시 — [06 §6.1](06-security-privacy.md)).
- **런타임 env는 이미지에 굽지 않음**: `DATABASE_URL`·`REDIS_URL`·`PII_MASTER_KEY`·S3·SMTP·LLM 설정은 컨테이너 기동 시 **런타임 주입**(시크릿 취급은 [06 §7](06-security-privacy.md)).
