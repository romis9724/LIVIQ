# LIVIQ

아파트 관리 **AI 플랫폼** — 기존 시스템·문서 위에 얹는 AI 검색·응대·요약 계층.
입주민 앱/관리 웹을 재구현하는 프로젝트가 아니다.

- 에이전트·기여자 가이드: [CLAUDE.md](CLAUDE.md) (절대 규칙 8개 포함, 먼저 읽을 것)
- 아키텍처·의존성: [ARCHITECTURE.md](ARCHITECTURE.md)
- 사업 계획서(전체): [docs/10-project-plan.md](docs/10-project-plan.md)
- 설계 문서 전체: [docs/README.md](docs/README.md)

## 빠른 시작

```bash
pnpm install     # Node >=20.11, pnpm >=9
pnpm dev         # 웹 앱 병렬 실행 (turbo)
pnpm build
pnpm lint
pnpm typecheck
```

컨텍스트 문서 경로 검증(선택, 권장):

```bash
pnpm check:paths                     # 문서 링크 경로 검증
git config core.hooksPath .githooks  # pre-push 훅 활성화(1회)
```

## 구조

```text
apps/
  web-resident   입주민 웹 (@liviq/web-resident) — AI 응대·조회
  web-admin      관리 웹  (@liviq/web-admin)     — 검색·요약·검수
packages/
  ui             공유 디자인 시스템 (@liviq/ui) — 토큰·컴포넌트
  config-ts      공유 tsconfig (@liviq/config-ts)
mcp/             Python MCP 서버·관리 에이전트 (Gmail·apt 연동)
docs/            설계·계획 문서    refs/  참조 자료
```

각 모듈 루트에 `CLAUDE.md`가 있으니 해당 영역 작업 전 참고.

## 핵심 파일

- [CLAUDE.md](CLAUDE.md) — 절대 규칙·스택·명령·컨벤션
- [packages/ui/src/styles/tokens.css](packages/ui/src/styles/tokens.css) — 디자인 토큰 단일 출처
- [docs/06-security-privacy.md](docs/06-security-privacy.md) — 개인정보·tenant 격리 규칙
- [docs/08-llm-token-optimization.md](docs/08-llm-token-optimization.md) — 토큰 비용 전략

## 규칙 (요약 · 상세는 CLAUDE.md)

> **출처 없는 AI 답변 금지** · **개인정보 외부 LLM 전송 전 마스킹(fail-closed)** ·
> **tenant 격리(tenant_id + RLS)** · **인가는 서버에서** · **관리비는 ERP 단일 출처** ·
> **위험 출력은 사람 검수(자동발송 금지)**.

## 스택

TypeScript · Turborepo + pnpm · Next.js · (계획) NestJS · Drizzle ORM ·
PostgreSQL 16 + pgvector · Redis + BullMQ · Zod · 외부 LLM API(Claude 우선).
