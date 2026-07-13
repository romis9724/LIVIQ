# ADR-0013: 백엔드 Python 전환 (FastAPI·SQLAlchemy·arq·uv)

- 상태: Accepted
- 날짜: 2026-07-13
- 관련: [ADR-0001](0001-monorepo-layered-ai.md), [ADR-0005](0005-single-llm-openai-compat.md), [ADR-0008](0008-freeze-mcp-prototype.md), [ADR-0011](0011-redis-server-session.md), [docs/09](../09-implementation-harness.md)

## 맥락

[ADR-0001]은 "TypeScript 풀스택 모노레포"를 전제로 api·ai-worker·ai-core·db를 목표 아키텍처에 두었으나(NestJS·Drizzle·BullMQ), 이 백엔드 계층은 **아직 한 줄도 착수되지 않았다** — 실존하는 코드는 웹 목업(web-resident·web-admin·ui·config-ts)과 동결된 Python 프로토타입(`mcp/`, [ADR-0008])뿐이다. 즉 지금 백엔드 언어를 바꿔도 **매몰 비용이 없다**(마이그레이션할 TS 백엔드 코드가 존재하지 않음). 이 시점이 언어 전제를 재검토할 마지막 저비용 구간이다.

전환하는 이유(rationale)는 세 가지다.

1. **AI/RAG 생태계**: 임베딩·PDF/문서 파싱·청킹·평가(eval) 도구가 Python에 압도적으로 성숙하다. 이 프로젝트의 핵심은 RAG 응대 계층이므로, 생태계가 얇은 TS에서 계속 우회 구현하는 비용이 크다.
2. **팀 숙련도**: 백엔드 담당 숙련도가 Python에 있다. 익숙한 언어에서 보안(마스킹·RLS)·정확도 게이트에 집중하는 편이 안전하다.
3. **채용·협업 대비**: 국내 AI/백엔드 인력 풀과 협업 관행이 Python 쪽이 두텁다 — 파일럿 이후 확장 시 인력 조달이 쉽다.

## 결정

백엔드 계층을 **전부 Python 3.12+**로 구현한다. TypeScript는 프런트엔드(apps/web-resident·web-admin·packages/ui·config-ts)에만 유지한다.

1. **범위**: `apps/api`(FastAPI) · `apps/ai-worker`(arq) · `packages/ai-core` · `packages/db`(SQLAlchemy 모델·Alembic·RLS SQL)를 Python으로 둔다.
2. **API·검증**: FastAPI + **Pydantic v2**로 경계 입력을 검증한다(서버측 Zod 대체). 스트리밍 응답은 `sse-starlette`(SSE).
3. **ORM·마이그레이션**: **SQLAlchemy 2.0(async) + Alembic**. tenant RLS 정책 SQL은 Alembic custom migration으로 관리한다(규칙 3의 이중 방어 중 DB 레이어).
4. **큐**: **arq**(Redis 기반·async·cron 내장)로 BullMQ를 대체한다. Redis는 세션·캐시·큐를 겸한다([ADR-0011]).
5. **패키징**: **uv workspace**(단일 lock)로 Python 의존성을 관리한다. 각 Python 패키지에 **얇은 `package.json`**을 두어 turbo 태스크(`lint`=ruff · `typecheck`=mypy · `test`=pytest)에 연결한다 — 루트 pnpm/turbo 명령 체계는 그대로 유지된다.
6. **웹↔api 타입 공유**: FastAPI가 내보내는 **OpenAPI 스키마 → openapi-typescript**로 웹용 타입을 생성한다(`packages/api-types`, 생성물). 기존 `packages/shared`(Zod DTO 공유) 계획은 **폐기**한다.
7. **도구 체인**: ruff(lint+format) · mypy(타입) · pytest(+pytest-asyncio·testcontainers·pytest-cov, 커버리지 80%).

## 대안

- **NestJS 유지(TS 풀스택 존치)**: 웹과 언어가 통일돼 컨텍스트 전환이 없으나, AI/RAG 생태계가 Python 대비 이질·빈약하고 팀 숙련도도 Python에 있다. 위 rationale 3종과 정면 충돌. 기각.
- **polyglot(api는 TS 유지, AI 계층만 Python)**: 웹-api 타입 공유는 편하나, 백엔드를 **2개 언어로 운영**하는 비용(툴체인·CI·디버깅·인력)이 파일럿 규모에 과다하다. 경계가 api↔ai-core로 자주 오가므로 분리 이득도 작다. 기각.
- **Django**: 배터리 포함이나 API-first·async 중심이 아니고 ORM·프로젝트 구조가 무겁다 — 우리는 게이트웨이 + async I/O가 핵심. 기각.
- **Litestar**: FastAPI와 유사하나 레퍼런스·채용 풀이 FastAPI가 두텁다. 기각.
- **Celery(큐)**: 성숙하나 브로커·워커 모델이 무겁고 async·cron 내장이 약하다 — arq가 Redis 단일 스토어([ADR-0011])·async에 더 맞다. 기각.
- **poetry(패키징)**: 검증됐으나 설치·해석 속도와 workspace 단일 lock 운용에서 uv가 앞선다. 기각.

## 결과

- **타입 공유 전략 교체**: `packages/shared`(Zod DTO 양방향 공유) → `packages/api-types`(OpenAPI에서 생성하는 단방향 산출물). 진실의 원천이 api의 Pydantic 스키마로 단일화된다.
- **H0(부트스트랩) 체크리스트 재정의**: docs/09 하네스의 백엔드 스캐폴딩 항목이 uv workspace·FastAPI·Alembic·arq 기준으로 바뀐다(코드 게이트 순서 format→lint→typecheck→test→build는 불변, 도구만 ruff·mypy·pytest로 매핑).
- **마이그레이션 비용 0**: 대체할 TS 백엔드 코드가 없어 재작성 부담이 없다. 전환은 목표 아키텍처 문서·부트스트랩 계획에만 반영된다.
- **경계 규칙 유지**: 규칙 2(마스킹 fail-closed)·3(tenant RLS)·8(읽기 전용 도구)은 언어와 무관하게 그대로 적용된다 — RLS는 Alembic SQL, 마스킹은 ai-core 어댑터 경계.
- **`mcp/`는 참고로 승격**([ADR-0008] 갱신): 동결·수정 금지는 유지하되, 신규 Python 백엔드가 검증된 코드(Sheets 파싱·Gmail 토큰 플로우 등)를 **복사·개작**하는 것은 허용한다(직접 import는 금지).
- 재검토 신호: 웹-백엔드 타입 드리프트가 OpenAPI 생성으로 감당 안 되거나, 백엔드 단일 언어가 성능·배포 경계에서 병목이 될 때.
