# 02. 디렉토리 구조 설계

> 아키텍처: [01-architecture.md](01-architecture.md) · 인덱스: [README.md](README.md)
> 스택: Turborepo + pnpm + Next.js + NestJS + Drizzle + PostgreSQL/pgvector + Neo4j (TypeScript 전 영역)

> 본 문서는 **목표 구조**다. 현재 구현 현황은 [CLAUDE.md](../CLAUDE.md) '구조' 절 참조.

## 1. 원칙

- **기능/도메인 단위 구성** (파일 타입별 X). 고응집·저결합.
- **공유 코드는 `packages/`**, 실행 단위는 `apps/`.
- **타입·스키마는 단일 출처**: DB 스키마(`packages/db`)와 DTO(Zod, `packages/shared`)를 앱이 import.
- 파일 200~400줄 표준, 800줄 상한. 큰 모듈은 분할.

## 2. 모노레포 최상위

```text
LIVIQ/
├── apps/
│   ├── web-resident/      # 입주민 반응형 웹/PWA (Next.js)
│   ├── web-admin/         # 관리자·시설·입대의 콘솔 (Next.js)
│   ├── api/               # NestJS (도메인 API + BFF + AI 오케스트레이션 진입)
│   └── ai-worker/         # BullMQ 워커 (인제스트/OCR/임베딩/평가/graph-sync)
├── packages/
│   ├── ai-core/           # RAG·오케스트레이션·LLM 어댑터·토큰예산 (프레임워크 비의존)
│   ├── db/                # Drizzle 스키마·마이그레이션·RLS·시드
│   ├── shared/            # 도메인 타입, Zod 스키마, 상수, 에러, 유틸
│   ├── ui/                # 공용 React 컴포넌트·디자인 토큰 (web 공유)
│   ├── config-eslint/     # 공유 ESLint
│   └── config-ts/         # 공유 tsconfig
├── docs/                  # 설계 문서 (본 디렉토리)
├── refs/                  # 경쟁/참고 자료 (추출 이미지)
├── tests/
│   ├── e2e/               # Playwright (크로스 앱 시나리오)
│   └── ai-eval/           # 골든셋·AI 평가 하네스
├── infra/                 # docker-compose, IaC, 마이그레이션 러너
├── .github/workflows/     # CI/CD
├── turbo.json
├── pnpm-workspace.yaml
├── package.json
├── CLAUDE.md              # 프로젝트 가이드 (루트, Claude Code 자동 로드)
└── README.md             # 기획/계획서
```

> `mcp/`(레포 실존): Python 프로토타입 **동결** — 참고용. 신규 AI 기능은 `packages/ai-core`([ADR-0008](adr/0008-freeze-mcp-prototype.md)).

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

## 4. `apps/api` (NestJS, 도메인 모듈)

```text
api/
├── src/
│   ├── main.ts
│   ├── app.module.ts
│   ├── common/                    # 가드, 인터셉터, 필터, 파이프(Zod), 데코레이터
│   │   ├── guards/                # AuthGuard, RolesGuard, TenantGuard
│   │   ├── interceptors/          # logging, audit
│   │   └── pii/                   # 마스킹 미들웨어
│   ├── modules/
│   │   ├── auth/                  # 인증·세대검증·세션
│   │   ├── tenants/               # 단지
│   │   ├── users/
│   │   ├── documents/             # 업로드·공개범위·인제스트 트리거
│   │   ├── search/                # RAG 검색 엔드포인트
│   │   ├── assistant/             # 질의 오케스트레이션 (ai-core 사용)
│   │   ├── inquiries/             # 민원·자동분류
│   │   ├── notices/               # 공지 초안·발송
│   │   ├── fees/                  # 관리비 조회(엑셀 업로드 원천)+AI 설명
│   │   ├── facilities/            # 시설·이력
│   │   ├── review/                # AI 검수 큐
│   │   ├── consents/              # 개인정보 동의
│   │   └── audit/                 # 감사 로그
│   ├── integrations/
│   │   └── erp/                   # (추후) ERP 어댑터 — 도입 시 활성, 현재는 인터페이스 자리만
│   └── config/                    # env 검증(Zod), 시크릿 로더
└── package.json
```

규칙:
- 모듈 = 도메인 경계. controller(경계) → service(로직) → repository(데이터, `packages/db`).
- 입력은 controller에서 Zod로 검증. 외부(ERP/LLM)는 어댑터 인터페이스 뒤로 숨김(테스트 모킹 용이).

## 5. `packages/ai-core` (프레임워크 비의존)

```text
ai-core/
├── src/
│   ├── orchestrator.ts            # 캐시→의도분류→에이전트 루프(스텝 상한)→후처리
│   ├── intent/                    # 분류기 (AI처리/사람연결/캐시 1차 분기)
│   ├── tools/                     # 도구 레지스트리 — retrieval(pgvector)·graph(Neo4j)·sql(고정 조회). 전부 읽기 전용, 파라미터 Zod 검증·tenant/소유권 강제
│   ├── retrieval/                 # 임베딩·벡터검색·리랭킹
│   ├── generation/                # 프롬프트 빌더·LLM 호출
│   ├── llm/                       # OpenAI-호환 클라이언트(env로 프로바이더 교체), 토큰 카운트
│   ├── budget/                    # 컨텍스트 예산·청크 선택 ([08])
│   ├── cache/                     # 정확/의미 캐시 인터페이스
│   ├── pii/                       # 마스킹/가명화 (api와 공유)
│   ├── citations/                 # 인용 검증
│   └── confidence.ts              # 신뢰도 산출·폴백 판정
└── package.json
```

> NestJS/Next에 의존하지 않음 → 테스트·재사용·서비스 분리(ADR-4) 용이.

## 6. `packages/db` (Drizzle)

```text
db/
├── src/
│   ├── schema/                    # 테이블별 파일 (tenants.ts, users.ts, documents.ts, chunks.ts ...)
│   ├── rls/                       # RLS 정책 SQL
│   ├── index.ts                   # 클라이언트·타입 export
│   └── seed.ts
├── drizzle/                       # 생성된 마이그레이션
└── drizzle.config.ts
```
상세 스키마: [03-database-design.md](03-database-design.md).

## 7. `packages/shared`

```text
shared/
├── src/
│   ├── types/                     # 도메인 타입 (Role, Visibility ...)
│   ├── schemas/                   # Zod (API DTO) — web/api 공유
│   ├── constants/                 # 역할, 위험도, 임계치
│   ├── errors/                    # 표준 에러·코드
│   └── result.ts                  # API 응답 envelope (성공/에러 일관)
└── package.json
```

## 8. 네이밍 규칙 (사용자 web 규칙 준수)

- 컴포넌트: `PascalCase` (`CitationCard.tsx`)
- 훅: `useXxx` (`useAssistantStream.ts`)
- 디렉토리/CSS: `kebab-case`
- 상수: `UPPER_SNAKE_CASE` / 타입·인터페이스: `PascalCase`
- DB 테이블·컬럼: `snake_case`
- 자산(refs 이미지): `kebab-case`

## 9. 환경/설정

- 시크릿은 코드에 두지 않음. `.env`(로컬)·시크릿 매니저(운영). `.env.example` 제공.
- env는 부팅 시 Zod로 검증(누락 시 즉시 실패) — `apps/*/src/config`.
- 로컬: `infra/docker-compose.yml` (postgres+pgvector, redis, minio).
