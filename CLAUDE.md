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
6. **위험 출력은 사람 검수.** AI의 입주민 자동발송 금지(공지는 AI 미개입 일반 게시판 — H8-1, [ADR-0015](docs/adr/0015-notice-board-replaces-ai-draft.md)). 신뢰도 낮은 답변은 담당자 연결 폴백(사후 검수 큐는 H8-7에서 제거 — ADR-0015 개정 노트).
7. **토큰은 비용.** 캐싱·컨텍스트 예산·에이전트 스텝 상한 적용(단일 모델, 라우팅 보류)([docs/08](docs/08-llm-token-optimization.md)).
8. **액션은 코드가 실행.** LLM 출력으로 권한·발송 등 부수효과를 직접 트리거하지 않음. (에이전트 도구는 읽기 전용 — 쓰기는 UI/폼)

## 스택

**웹(TypeScript)** Next.js(web-resident·web-admin) · Turborepo + pnpm · 공유 `@liviq/ui`·`config-ts`.
**백엔드(Python 3.12+)** FastAPI + Pydantic v2(경계 검증) · SQLAlchemy 2.0(async) + Alembic(RLS SQL) · arq(Redis 큐) · uv workspace ([ADR-0013](docs/adr/0013-python-backend.md)).
데이터: PostgreSQL 16 + pgvector · Neo4j(시설 그래프, 파생) · Redis(세션·캐시·큐) · MinIO.
LLM: OpenAI-호환 단일 엔드포인트(Ollama·vLLM·OpenAI 등, env 교체) · **파일럿 확정 모델 llama3.1:8b**(H5-1 실측 — tool calling·인용 규율·지연 3단계 통과, [docs/09 §8.6](docs/09-implementation-harness.md)) · 임베딩 bge-m3(1024).
타입 공유: FastAPI OpenAPI → openapi-typescript 생성(`packages/api-types`).

## 구조 ([docs/02](docs/02-directory-structure.md) · 상세는 [ARCHITECTURE.md](ARCHITECTURE.md))

현재 구현된 것(현실): **H18 완료(측정 일부 미충족)** — 에이전트 심화([ADR-0025](docs/adr/0025-agent-depth-plan-clarify-structured.md), LangChain 미도입): 멀티턴 컨텍스트(직전 3턴·마스킹 통과·히스토리 있으면 캐시 우회) · **되묻기**(`ask_clarification` 도구가 실행 대신 `status=clarify`로 즉시 종료, 연속 금지) · **계획 turn**(무-도구 turn 1회 재해석, 스텝 상한 4) · **구조화 응답**(`ToolCard.data` — 관리비 표·주차 목록·시설 상태·민원 사례·공지 목록, **LLM 프롬프트에는 미포함** = 화면 숫자는 도구 확정값) · **최근 공지 도구**(`get_recent_notices` — "공지사항" 같은 메타 질의는 유사도 검색이 못 잡는다, dev 라우팅 4/4) · 후속 질문 칩은 **질문형만**(이동·행동 문구를 담았다가 "원문 문서 열어보기"가 질문으로 전송돼 폴백 난 실측 — 이동은 CTA, 행동은 폼) · SSE는 4종 유지하고 필드만 additive(`status.tool`·`citation.data`·`done.suggestions`) · Perplexity형 UI(진행 단계 접이식·출처 선배치·맥락 칩, 칩↔CTA 중복은 CTA 우선). 측정 R30·R30b: 되묻기 오남용 2.3~5.7%(기준 충족)·hardfail 0이나 **인용 중위 87.3→82.3%**, 원인 가설(목록 인용 누락) 기각 — 실체는 회차 분산 증가(2.5→6.4pp)이고 인용 상한 돌파는 상위 모델 몫(기존 잔여). **인용률 비교는 3회 이상 중위로만 할 것.** 그 이전 **H17 완료** — AI 비서 에이전트 확충(도구 10종): ①민원 트리아지 — 증상·고장 신고성 질의면 `search_similar_inquiries`(pg_trgm `word_similarity` 임계 0.4·RESIDENT)가 같은 단지의 유사 사례를 **제목·분류·처리결과 요약만** 근거로 주고, 답변 하단 CTA가 `/inquiries?compose=1&title=&body=` 프리필 폼으로 넘긴다 — **AI는 민원을 만들지 않는다**(규칙 8, [ADR-0024](docs/adr/0024-assistant-inquiry-triage.md)). ②입주민 주차맵 `/parking` — `GET /parking/map`은 점유 면 번호와 **본인 세대** 차량 위치만 내보내고(타 세대 번호판·동호수는 스키마에 필드 없음), `ParkingMap` 2D는 `@liviq/ui` 공용으로 승격(admin은 어댑터). 어시스턴트의 빈자리 답변에서 "주차위치 보기" → `?spot=` 강조. 라우팅 실측으로 도구 설명·임계를 되돌린 기록은 ADR-0024 §실측 — 8B는 신고형 질의 일부를 여전히 평면도로 흘리지만, 접수 CTA는 유사 민원 도구가 라우팅된 답변에만 뜬다(폴백 경로 CTA는 사용자 지시로 제거). 골든셋 트리아지 케이스 9건은 draft·리졸버까지 완료(dev `gen` 재생성·반복 측정은 후속). 그 이전 **H16 완료** — 주차 점유 실데이터화: 프론트 시뮬 폐기, `parking_vehicles.spot_no`·`entry_at`이 단일 출처(시드 결정적 배정 — 입주민 248대+외부 8대, 동/호수-차량번호-주차면 연결, [docs/03 §4.11](docs/03-database-design.md)). 병렬 H15-4의 저장 설계(`parking_occupancy` 별도 테이블)는 H16 컬럼 방식으로 **대체**(ADR-0023 개정) — H15-4의 최근접 빈자리 도구·채점·측정 자산은 spot_no 기반으로 재배선해 유지. 그 이전 **H15-1·H15-3 완료** — 관리자 AI 설정(`/system/ai`, SYS_ADMIN): LLM·임베딩 백엔드와 튜닝 노브(top_k·출력 상한·timeout·confidence·캐시 TTL·청크 상한)를 UI로 저장하면 재시작 없이 반영(`ai_backend_config` DB 우선·env 폴백, 해석 단일 지점 `ai_core.backend_config` — api 요청·worker 잡 공유). 임베딩 변경은 차원 1024 실측 가드 + 명시적 재색인 버튼(전 문서·공지 재인제스트). **H15-2 로컬 축 측정 완료**(OpenAI 축만 대기 — 키 필요): 파일럿 구성은 **llama3.1-8B-AWQ(vLLM) · top_k 16 · 컨텍스트 예산 2,400**이고, 검색·튜닝 축은 소진됐다 — 정답 청크가 유사도 1위로 올라오는데 모델이 `[n]`을 붙이지 않아 폐기되는 건이 17~21%로, **8B 급의 상한은 검색이 아니라 인용 규율**이다(프롬프트 강화·사후 재요청 둘 다 기각). 청커는 PDF 추출문 대응 필수 — 제목이 줄 끝까지 삼켜 청크가 상한 5배가 됐고, 조항 경계를 줄머리만 보면 라벨이 틀린 조를 가리킨다(둘 다 수정, `clause` 배선 연결로 조항 단위 인용 가능). 판정 근거·기각 사유 전량은 [MEASUREMENT-LOG.md](evals/results/rag500/MEASUREMENT-LOG.md) R1~R21이 단일 출처. **GraphRAG 비교(H15-2 확장 G1~G4, 개발서버 실측 R24~R26)**: pgvector vs Neo4j를 병렬 표현+클래스 분담으로 측정 — 검색 품질은 백엔드 중립(R26 forced-backend hit@k=1.0), 그래프 자산 활용은 모델 티어 의존(R25 8B 과소선택→14B 인용 81→96%), Neo4j 고유 가치는 관계·다단계 인과 표현(CAUSED_BY 연쇄)이며 8B 파일럿에선 도구 라우팅에 막혀 회수율 낮음. 인과 self-FK·세대 추적 도구 `trace_home_device_issue`·비교 케이스 40 신설(hard_fail 0). **H15-4 완료** — RESIDENT 최근접 빈자리 도구(공간거리·읽기전용, [ADR-0023](docs/adr/0023-parking-occupancy-persisted.md) — 저장 형태는 H16이 `parking_vehicles` 컬럼으로 대체) · 복합(그래프+벡터+PG) 케이스·`required_tools`(AND) 채점 · **3자 측정(R28, 로컬 스택)**: 8B 파일럿(pass 59·라우팅 91.5%·인용 90%·2s)이 14B(51·83%·4s)보다 우위 — 대형이 상한 못 뚫음. Qwen3.5-9B는 라우팅 100%(qwen3_coder 파서)이나 멀티모달-단일변형·thinking-off 불가(전건 폴백)·15~20배 지연으로 **비적합** → **8B 유지 확정**. 그 이전 H14 완료 — 시설관리 전체화면 그래프+플로팅 패널(도면→방·종류→마커 계층, [ADR-0022](docs/adr/0022-facility-graph-dashboard.md)) · 시설 코드 체계(`EL-401-01` 서버 자동 부여·공통코드·민원 코드 연결) · 트윈 세대 평면도 자동 표시(@liviq/ui FloorPlanViewer 공용) · 주차장 3D(주행 차량) · 관리자 전 메뉴 UI 일관화([docs/05 §5A](docs/05-ui-ux-design.md) 패턴 가이드). 그 이전 H13: 3D 시설 그래프 첫 구축·민원-시설 연결 3단·세대 평면도 기동(입주민 뷰·편집·어시스턴트 파서 도구). 그 이전: H12 사내 GitLab 배포 **실호스트 운영 중**(main push → WSL 자동 배포·Nexus 게시·롤백 실연, 남은 항목 WSL 부팅 자동 시작). 단계별 범위·상태는 [docs/09 §8](docs/09-implementation-harness.md)이 단일 출처.
워크스페이스 구성은 `ls`·[docs/02](docs/02-directory-structure.md)·[ARCHITECTURE.md](ARCHITECTURE.md) 참조.

Python은 uv workspace(루트 `pyproject.toml`) + 얇은 package.json으로 turbo 태스크 연결([ADR-0013](docs/adr/0013-python-backend.md)).
인증: Redis 세션+**자체 이메일+비밀번호**(Argon2id·검증 메일·auth_tokens — H7-1, [ADR-0014](docs/adr/0014-local-email-auth.md))+역할 가드 — 웹은 세션 쿠키 1차(credentials CORS), dev 헤더(`X-Dev-*`)는 api의 local 보조(evals용). E2E는 시드 계정 API 로그인 + 전 여정(설치→단지→초대→명부→가입→승인→AI, H7-4). 다음 단계·백로그: [docs/09 §8.8·§8.3](docs/09-implementation-harness.md).
DB 접속 롤은 프로세스마다 다르다 — 마이그레이션만 owner, api는 `liviq_app`, ai-worker는 `liviq_worker`(RLS 이중 방어 2층의 성립 조건 — H10-2, [docs/03 §5.1](docs/03-database-design.md)). 운영 스크립트는 owner 접속이 필요해 compose에서 `migrate` 서비스로 실행한다.
로컬 인프라는 `infra/docker-compose.yml`(pg16+pgvector·redis·minio·neo4j — 호스트 포트는 파일 상단 주석), env 계약은 `.env.example`.
배포 형상은 **둘** — 컨테이너 이미지 4종(api·ai-worker·web 2종) + `infra/compose.prod.yml` profiles 공용. ①3-tier VM + GHCR + GitHub Actions([ADR-0020](docs/adr/0020-container-deploy-3tier-vm.md)) ②사내 단일 호스트(Windows Server WSL2 Docker) + GitLab CI([ADR-0021](docs/adr/0021-gitlab-ci-single-host-wsl.md) — 러너가 대상 호스트 **안**이라 인바운드 개방 0·배포 키 없음. 기동은 로컬 빌드 이미지, 게시는 스모크 뒤 **사내 Nexus**로 — GitLab 컨테이너 레지스트리는 포트 미노출로 사용 불가). env 계약은 `infra/env.prod.example`, 절차는 ①[docs/12](docs/12-deployment-runbook.md) ②[docs/13](docs/13-gitlab-wsl-deploy.md)(공용 진입점 `infra/deploy-wsl.sh`).

## 자주 쓰는 명령

```bash
# 표준 turbo 태스크(install·dev·build·lint·typecheck·start)는 package.json scripts 참조
pnpm test        # turbo run test — vitest(web 2종+ui) + pytest(Python 4종, cov 80 게이트)
uv sync --all-packages    # Python 전 멤버 설치 (plain `uv sync`는 dev 도구만 — 부족)
pnpm db:migrate           # Alembic upgrade head (DATABASE_URL 필요)
# 로컬 문서 벡터화·재색인은 arq worker가 있어야 처리됨 (apps/ai-worker에서, env 필요)
uv run --no-sync arq ai_worker.worker.WorkerSettings
pnpm generate:api-types   # FastAPI OpenAPI → packages/api-types 재생성 (CI 드리프트 게이트)
pnpm e2e                  # Playwright 여정 (infra 기동 필요 — CI는 @llm 자동 제외)
# 배포 이미지 스모크(1호스트 3프로필 = 배포 형상, 절차 전체는 docs/09 §2)
docker compose --env-file infra/env.prod -f infra/compose.prod.yml --profile data --profile app --profile web up -d --build
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
구현 [09](docs/09-implementation-harness.md) · 데이터 [11](docs/11-data-architecture.md) · 배포 런북 [12](docs/12-deployment-runbook.md) ·
GitLab→WSL 배포 [13](docs/13-gitlab-wsl-deploy.md) · ADR [docs/adr/](docs/adr/README.md)
