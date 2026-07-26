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
│   ├── compose.prod.yml   # 운영 배포 (profiles: data/app/web) — H10-1에서 추가
│   └── Caddyfile          # web tier 리버스 프록시·TLS 종단 — H10-1에서 추가
├── .github/workflows/     # CI/CD
├── turbo.json
├── pnpm-workspace.yaml
├── pyproject.toml         # uv workspace 루트 (members: apps/api·ai-worker·packages/ai-core·db)
├── package.json
├── CLAUDE.md              # 프로젝트 가이드 (루트, Claude Code 자동 로드)
└── README.md             # 기획/계획서
```

> 앱 4종의 `Dockerfile`은 **H10-1에서 각 앱 디렉토리**(`apps/api/Dockerfile`·`apps/ai-worker/Dockerfile`·`apps/web-resident/Dockerfile`·`apps/web-admin/Dockerfile`)에 추가된다. uv workspace(단일 lock) + pnpm workspace 구조상 앱 디렉토리만으로는 빌드 불가 — **빌드 컨텍스트는 레포 루트**, Dockerfile은 앱 디렉토리에 둔다.

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

> `web-admin`도 동일 패턴. 라우트: `documents/`, `inquiries/`, `notices/`(초안·검수), `review-queue/`(AI 검수), `facilities/`, `fees/`(엑셀 업로드), `onboarding/`(가입 승인), `dashboard/`, `settings/`.

## 4. `apps/api` (FastAPI, 도메인 라우터)

```text
api/
├── app/
│   ├── main.py                    # FastAPI 앱·미들웨어·라우터 등록
│   ├── config.py                  # env 검증(Pydantic Settings), 시크릿 로더
│   ├── deps.py                    # 공통 의존성 (인증·역할·테넌트·세션 주입)
│   ├── middleware/                # 로깅·감사·PII 마스킹
│   ├── routers/                   # 경계 — auth·tenants·users·documents·search·assistant·inquiries·notices·fees·facilities·review·consents·audit
│   ├── services/                  # 도메인 로직 (라우터가 호출, `packages/db` 사용)
│   ├── schemas/                   # 요청·응답 Pydantic 모델 (→ OpenAPI)
│   └── integrations/
│       └── erp/                   # (추후) ERP 어댑터 — 도입 시 활성, 현재는 인터페이스 자리만
├── pyproject.toml
└── package.json                   # turbo 태스크 연결 (lint=ruff·typecheck=mypy·test=pytest)
```

규칙:
- 라우터 = 도메인 경계. router(경계) → service(로직) → repository(데이터, `packages/db`).
- 입력은 라우터에서 Pydantic v2로 검증. 외부(ERP/LLM)는 어댑터 인터페이스 뒤로 숨김(테스트 모킹 용이).

## 5. `packages/ai-core` (Python, 프레임워크 비의존)

```text
ai-core/
├── src/ai_core/
│   ├── orchestrator.py            # 캐시→의도분류→에이전트 루프(스텝 상한)→후처리
│   ├── intent/                    # 분류기 (AI처리/사람연결/캐시 1차 분기)
│   ├── agent/                     # 도구 레지스트리 — retrieval(pgvector)·graph(Neo4j)·sql(고정 조회). 전부 읽기 전용, 파라미터 Pydantic 검증·tenant/소유권 강제
│   ├── rag/                       # 임베딩·벡터검색·리랭킹·프롬프트 빌더
│   ├── llm/                       # OpenAI-호환 클라이언트(env로 프로바이더 교체), 토큰 카운트
│   ├── budget/                    # 컨텍스트 예산·청크 선택 ([08])
│   ├── cache/                     # 정확/의미 캐시 인터페이스
│   ├── masking/                   # PII 마스킹/가명화 (api와 공유)
│   ├── citations/                 # 인용 검증
│   └── confidence.py              # 신뢰도 산출·폴백 판정
├── pyproject.toml
└── package.json                   # turbo 태스크 연결 (lint=ruff·typecheck=mypy·test=pytest)
```

> FastAPI/Next에 의존하지 않음 → 테스트·재사용·서비스 분리(ADR-4) 용이.

## 6. `packages/db` (SQLAlchemy + Alembic)

```text
db/
├── src/liviq_db/
│   ├── models/                    # 테이블별 SQLAlchemy 2.0 async 모델 (tenants.py, users.py, documents.py, chunks.py ...)
│   ├── rls/                       # RLS 정책 SQL
│   ├── __init__.py                # 엔진·세션·모델 export
│   └── seed.py
├── alembic/                       # 생성된 마이그레이션 (env.py + versions/)
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
- **운영 배포**: 앱 4종(`api`·`ai-worker`·`web-resident`·`web-admin`)을 컨테이너 이미지로 빌드해 GHCR에 게시하고, `infra/compose.prod.yml`(H10-1에서 추가) **단일 파일 + profiles(`data`/`app`/`web`)** 로 3-tier VM에 배포([ADR-0020](adr/0020-container-deploy-3tier-vm.md)). 로컬 스모크는 같은 파일을 1호스트에서 3프로필 동시 기동으로 검증하고, 개발 루프 자체는 네이티브 유지.
- **웹 env는 빌드타임 인라인**: `NEXT_PUBLIC_*`은 Next 빌드 시 번들에 박히므로 **이미지 빌드 인자로 주입**된다(런타임 교체 불가). 따라서 API 주소는 환경별 절대 URL이 아니라 **상대경로 `NEXT_PUBLIC_API_BASE_URL=/api`** 로 고정하고, 오리진 차이는 web tier 리버스 프록시가 흡수한다(same-origin `/api` 프록시 — [06 §6.1](06-security-privacy.md)).
- **런타임 env는 이미지에 굽지 않음**: `DATABASE_URL`·`REDIS_URL`·`PII_MASTER_KEY`·S3·SMTP·LLM 설정은 컨테이너 기동 시 **런타임 주입**(시크릿 취급은 [06 §7](06-security-privacy.md)).
