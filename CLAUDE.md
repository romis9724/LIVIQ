# CLAUDE.md — LIVIQ 프로젝트 가이드

아파트 관리 **AI 플랫폼**. 기존 시스템·문서 위에 얹는 **AI 검색·응대·요약 계층**이다.
입주민 앱/관리 웹을 재구현하는 프로젝트가 아니다.

상세 설계는 [docs/](docs/README.md). 이 파일은 매 세션 로드되니 **간결 유지**.

## 절대 규칙 (어기면 안 됨)

1. **출처 없는 AI 답변 금지.** 모든 답변에 검증된 근거(문서 조항 **또는** 확정 데이터·도구 결과) 인용. 근거 없으면 지어내지 말고 **담당자 연결 폴백**.
2. **개인정보는 LLM에 전송 금지(전 프로바이더, self-hosted 포함).** 호출 직전 마스킹/가명화, 실패 시 호출 중단(fail-closed).
3. **단지(tenant) 격리.** 모든 쿼리에 `tenant_id` + DB RLS 이중 방어. 단지 간 데이터 혼입 절대 금지.
4. **인가는 서버에서.** 프론트 메뉴 숨김은 보조일 뿐. 모든 엔드포인트가 역할·테넌트·소유권 검증.
5. **관리비는 확정 업로드 데이터(엑셀, 추후 ERP)가 단일 출처.** AI는 설명만, 계산·부과 금지.
6. **위험 출력은 사람 검수.** 입주민 자동발송 공지 금지(초안까지만). 신뢰도 낮은 답변은 검수 큐.
7. **토큰은 비용.** 캐싱·컨텍스트 예산·에이전트 스텝 상한 적용(단일 모델, 라우팅 보류)([docs/08](docs/08-llm-token-optimization.md)).
8. **액션은 코드가 실행.** LLM 출력으로 권한·발송 등 부수효과를 직접 트리거하지 않음. (에이전트 도구는 읽기 전용 — 쓰기는 UI/폼)

## 스택

**웹(TypeScript)** Next.js(web-resident·web-admin) · Turborepo + pnpm · 공유 `@liviq/ui`·`config-ts`.
**백엔드(Python 3.12+)** FastAPI + Pydantic v2(경계 검증) · SQLAlchemy 2.0(async) + Alembic(RLS SQL) · arq(Redis 큐) · uv workspace ([ADR-0013](docs/adr/0013-python-backend.md)).
데이터: PostgreSQL 16 + pgvector · Neo4j(시설 그래프, 파생) · Redis(세션·캐시·큐) · MinIO.
LLM: OpenAI-호환 단일 엔드포인트(Ollama·vLLM·OpenAI 등, env 교체) · **파일럿 확정 모델 llama3.1:8b**(H5-1 실측 — tool calling·인용 규율·지연 3단계 통과, [docs/09 §8.6](docs/09-implementation-harness.md)) · 임베딩 bge-m3(1024).
타입 공유: FastAPI OpenAPI → openapi-typescript 생성(`packages/api-types`).

## 구조 ([docs/02](docs/02-directory-structure.md) · 상세는 [ARCHITECTURE.md](ARCHITECTURE.md))

현재 구현된 것(현실, H1(RAG)+H2(입주민/관리자)+H3(시설 그래프·AI 도우미)+H4(레이트 리밋·정확 캐시·대시보드·토큰 예산 경고)+H5(모델 확정·평가 확대·알림 루프)+H6(전 화면 실연동·세션 인증·가입→AI E2E)+H7(자체 이메일 인증 전환 — SYS_ADMIN/초대 위계·역할 축소·주민 가입 UI·E2E 재작성, ADR-0014) 완료):

```text
apps/      web-resident                      # Next.js — 전 화면 실연동(홈·비서 SSE·민원·공지·관리비·나/알림함·가입/온보딩·비밀번호 재설정), 세션 쿠키 인증
           web-admin                         # Next.js — 전 화면 실연동(대시보드·문서·민원·공지 초안·관리비·검수 큐·시설·가입 승인/명부·직원 관리·단지 관리(SYS_ADMIN 뷰)), 세션 쿠키 인증
           api                               # FastAPI — documents·assistant·inquiries·notices·fees·review-queue·facilities(+outbox)·dashboard + 인증·레이트리밋·정확캐시 (liviq-api)
           ai-worker                         # arq — 문서 인제스트(파싱·청킹·임베딩·pgvector) (liviq-ai-worker)
packages/  ui · config-ts                    # 공유 컴포넌트/설정 (TS)
           api-types                         # OpenAPI→openapi-typescript 생성물 (TS)
           ai-core                           # RAG 전체 — LLM·마스킹·검색·인용검증·도구 에이전트(읽기 전용 6종)·그래프 (liviq-ai-core)
           db                                # SQLAlchemy 30테이블 · Alembic · RLS 정책+role (liviq-db)
mcp/       gmail·apt MCP 서버 · management_agent (Python — 프로토타입 동결, 신규 AI는 ai-core)
evals/     규칙 회귀 러너 · env 게이트 어댑터  # LIVIQ_EVAL_API_URL 설정 시 실측(규칙 1·2·3·5·6·8)
tests/     e2e                               # Playwright 결정론 여정 (@liviq/e2e — @llm 태그는 로컬 전용)
docs/ refs/                                  # 설계 문서 · 참조 자료
```

Python은 uv workspace(루트 `pyproject.toml`) + 얇은 package.json으로 turbo 태스크 연결([ADR-0013](docs/adr/0013-python-backend.md)).
인증: Redis 세션+**자체 이메일+비밀번호**(Argon2id·검증 메일·auth_tokens — H7-1, [ADR-0014](docs/adr/0014-local-email-auth.md))+역할 가드 — 웹은 세션 쿠키 1차(credentials CORS), dev 헤더(`X-Dev-*`)는 api의 local 보조(evals용). E2E는 시드 계정 API 로그인 + 전 여정(설치→단지→초대→명부→가입→승인→AI, H7-4). 다음 단계·백로그: [docs/09 §8.8·§8.3](docs/09-implementation-harness.md).
로컬 인프라는 `infra/docker-compose.yml`(pg16+pgvector·redis·minio·neo4j — 호스트 포트는 파일 상단 주석), env 계약은 `.env.example`.

## 자주 쓰는 명령

```bash
pnpm install
pnpm dev         # turbo run dev — 웹 앱 병렬 (apps/*, packages/*)
pnpm build       # turbo run build
pnpm lint        # turbo run lint
pnpm typecheck   # turbo run typecheck
pnpm test        # turbo run test — vitest(web 2종+ui) + pytest(Python 4종, cov 80 게이트)
pnpm start       # turbo run start (build 후)
uv sync --all-packages    # Python 전 멤버 설치 (plain `uv sync`는 dev 도구만 — 부족)
pnpm db:migrate           # Alembic upgrade head (DATABASE_URL 필요)
pnpm generate:api-types   # FastAPI OpenAPI → packages/api-types 재생성 (CI 드리프트 게이트)
pnpm e2e                  # Playwright 여정 (infra 기동 필요 — CI는 @llm 자동 제외)
```

> 없는 명령을 문서에 적지 말 것 — stale 참조는 없는 것보다 나쁘다.
> Python 패키지 디렉토리에서 plain `uv run` 금지(형제 멤버 deps를 prune함) — `uv run --no-sync` 사용.

## 코드 컨벤션 (사용자 web 규칙 + 본 프로젝트)

- 기능/도메인 단위 구성. 파일 200~400줄(800 상한). 불변 패턴, 작은 함수, 깊은 중첩 회피.
- 네이밍: 컴포넌트 `PascalCase` · 훅 `useX` · 디렉토리/CSS `kebab-case` · 상수 `UPPER_SNAKE` · DB·Python 모듈 `snake_case`(PEP 8).
- 경계 입력 검증: 서버(Python)=Pydantic v2 · 웹 폼=Zod. 외부(ERP/LLM)는 어댑터 인터페이스 뒤로.
- UI는 디자인 토큰만 사용(하드코딩 금지), 접근성 WCAG 2.2 AA, 라이트 테마 1차.
- 시크릿 하드코딩 금지. env는 부팅 시 검증(웹=Zod, Python=Pydantic Settings).

## 작업 방식

- **작업 사이클(H2부터)**: 작업 단위(Hx-y)마다 브랜치 → ①설계 갱신 커밋(구현 전 필수) → ②구현 커밋(게이트 그린 단위) → ③현행화 커밋(CLAUDE.md·ARCHITECTURE.md·docs/09 §8 상태) → ④PR(CI 그린+사용자 확인 후 머지). 상세: [docs/09 §3.1](docs/09-implementation-harness.md).
- 새 구현 전 **재사용 검토**(라이브러리/기존 패턴). KISS·YAGNI·DRY.
- TDD: 실패 테스트 → 구현 → 리팩터. 보안(인가/RLS/마스킹) 테스트는 CRITICAL 게이트.
- 코드 게이트 순서: format → lint → typecheck → test → build ([docs/09](docs/09-implementation-harness.md)).
- "완료" 정의는 [docs/09 §9](docs/09-implementation-harness.md). 아키텍처 결정 변경은 ADR 로그에 기록.
- 한국어로 응답·문서화. 기술 식별자는 원문 유지.

## 문서 지도

요구사항 [00](docs/00-requirements.md) · 아키텍처 [01](docs/01-architecture.md) · 디렉토리 [02](docs/02-directory-structure.md) ·
DB [03](docs/03-database-design.md) · 메뉴 [04](docs/04-menu-structure.md) · UI/UX [05](docs/05-ui-ux-design.md) ·
보안 [06](docs/06-security-privacy.md) · 테스트 [07](docs/07-testing-strategy.md) · 토큰 [08](docs/08-llm-token-optimization.md) ·
구현 [09](docs/09-implementation-harness.md) · 데이터 [11](docs/11-data-architecture.md) · ADR [docs/adr/](docs/adr/README.md)
