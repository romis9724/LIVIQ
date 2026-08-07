# MEMORY — LIVIQ 프로젝트 암묵지

에이전트·신규 기여자가 코드만 봐서는 알 수 없는 **결정 근거·비자명한 사실**을 모은다.
"왜 이렇게 되어 있나?"의 답. 결정이 바뀌면 여기와 [docs/adr/](docs/adr/README.md)를 함께 갱신.

> 규칙: 코드/커밋/문서로 이미 알 수 있는 것은 적지 않는다. 비자명한 것만.

## 아키텍처·경계

- **AI는 계층이지 앱이 아니다.** 기존 시스템 위에 검색·응대·요약을 얹는다. 입주민 앱/관리 웹을
  재구현하지 않는다. → 신규 기능은 "AI가 무엇을 돕는가"로 프레이밍. [ADR-0001](docs/adr/0001-monorepo-layered-ai.md)
- **DB 접속 롤이 프로세스마다 다른 것이 RLS 2층의 성립 조건이다.** 마이그레이션만 owner,
  api는 `liviq_app`, ai-worker는 `liviq_worker` — owner로 붙으면 RLS가 통째로 무력화된다(H10-2).
  운영 스크립트는 owner가 필요해 compose `migrate` 서비스로 돌린다.
- **라우터 아래 service/repository 계층은 일부러 두지 않았다.** 라우터가 `packages/db`를 직접 쓰고
  재사용 로직만 `app/` 루트 flat 헬퍼로 뽑는다(YAGNI). 계층을 새로 만들기 전에 이 결정을 먼저 뒤집을 것.
- **mcp/는 Python, TS 워크스페이스와 분리.** turbo/pnpm이 관리 안 함. 계약은 MCP 프로토콜로만.
  프로토타입 동결 상태([ADR-0008](docs/adr/0008-freeze-mcp-prototype.md)) — 현행 백엔드는 `apps/api`다.

## 보안·개인정보 (CRITICAL, 협상 불가)

- **개인정보 → LLM 전송 전 마스킹(전 프로바이더, self-hosted 포함), 실패 시 호출 중단(fail-closed).** "일단 보내고 나중에" 없음.
  [ADR-0002](docs/adr/0002-mask-before-external-llm.md)
- **tenant 격리는 이중 방어**: 앱 쿼리의 `tenant_id` + DB RLS. 하나만으로 신뢰하지 않는다.
- **시크릿 파일**: `mcp/service-credential.json`·`tokens.json`은 `.gitignore`로 차단, 로컬 전용.
  로그·에러 메시지에도 노출 금지. `mcp/apt_mng_agent.zip`도 이 시크릿들을 동봉하고 있어
  gitignore 차단 — 커밋 시도 금지, 불필요하면 로컬 삭제.

## 도메인 규칙 (놓치기 쉬움)

- **관리비는 확정 업로드 데이터(엑셀, 추후 ERP)가 단일 출처.** AI는 값을 설명만, 계산·부과 절대 금지. [ADR-0006](docs/adr/0006-fees-excel-upload-source.md)
- **공지에 AI는 손대지 않는다.** 초안 생성도 없다 — 일반 게시판이다([ADR-0015](docs/adr/0015-notice-board-replaces-ai-draft.md), H8-1).
  이전의 "초안까지만" 방침은 폐기됐다.
- **출처 없는 AI 답변 금지.** 근거(문서 조항 **또는** 확정 데이터·도구 결과) 없으면 지어내지 말고 담당자 연결 폴백.
- **신뢰도 낮은 답변은 담당자 연결 폴백으로 끝난다.** 사후 검수 큐는 H8-7에서 라우터·화면·DB 컬럼째
  제거됐고, 남은 `messages.review_status=needs_review`는 품질 집계용 **플래그**일 뿐 처리 흐름이 아니다.
- **AI는 민원을 만들지 않는다.** 유사 사례를 근거로 주고, 접수는 프리필 폼 CTA로 사람이
  한다([ADR-0024](docs/adr/0024-assistant-inquiry-triage.md)). 도구는 전부 읽기 전용이고 쓰기는 UI/폼이다.

## 하네스·검증 (2026-07-13 AI-readiness 감사에서 확정)

- **AI-readiness 자동 채점기(score.py)는 한국어를 못 읽는다.** 한국어 섹션 헤더(`## 의존성` 등)·
  상대경로(`.github`, `../..`)·자리표시자(`<name>`)를 오탐 — 자동 71점 vs 실측 98점.
  재감사 시 자동 점수만 믿지 말고 [docs/ai-readiness-score.json](docs/ai-readiness-score.json)의
  `manual_adjustments` 보정 원칙을 따를 것.
- **pre-push 경로 검증은 클론별 1회 활성화 필요**: `git config core.hooksPath .githooks`.
  hook 파일이 있어도 이 설정 없이는 돌지 않는다 (CI는 별개로 항상 검증).
- **evals(`run.mjs`) 14 케이스가 전부 pending인 것은 정상** — `LIVIQ_EVAL_API_URL` env가 없으면
  [adapter.mjs](evals/adapter.mjs)가 `not-wired`를 반환한다(fail 아님). CI는 이 env 없이 돌아 LLM 호출 0.
  실측은 로컬·dev에서 env를 주고 돌린다. 품질 측정(rag500)은 이것과 별개 트랙이다.
- **품질 수치의 단일 출처는 [MEASUREMENT-LOG.md](evals/results/rag500/MEASUREMENT-LOG.md)(R1~)뿐이다.**
  8B는 같은 설정에서도 회차별 ±8%p 흔들린다 — **인용률·pass 비교는 3회 이상 중위로만**, 범위가
  겹치면 무판정. 측정은 답변 캐시 오프 필수(R1에서 히트가 수치를 오염시킨 전례).
- **8B 라우팅은 문구에 민감하다.** 도구 description·프롬프트·프론트 고정 질의를 한 글자 바꾸면
  라우팅이 달라진다(브리핑 문구 변형 2종이 실측에서 기각됐다) — 문구 변경은 재실측 동반.
- **골든셋 케이스는 화면 문구의 사본이다.** 프론트 문구를 고치면 CSV(cases-draft·quality-cases-v2)도
  같이 갱신해야 한다. 안 하면 게이트는 초록인 채 유령 결함이 보고된다(R38 → R39에서 확인).
- **모델이 지켜주지 않는 판정은 코드로 내린다.** 관리자 채널의 도구 가시성·되묻기 여부는 프롬프트가
  아니라 라우터 `_admin_overrides`가 정한다(8B가 프롬프트 조건문을 못 지킨 실측 — H20-16·17·17b).

## Five-Question (모듈별 요약 · 상세는 각 CLAUDE.md)

| 모듈 | 소유(무엇) | 비자명 |
|------|-----------|--------|
| web-resident | 입주민 AI 응대·조회 UI | AI 화면은 출처 카드 필수. 후속 질문 칩은 **질문형만**(이동은 CTA, 행동은 폼) |
| web-admin | 관리소 운영 UI | 첫 진입이 AI 비서(`/assistant`). 구 대시보드는 `/inquiry-status`. 공지에 AI 초안 UI 없음 |
| api | HTTP 경계·인가·세션 | 인가는 **여기서** 끝난다(프론트 메뉴 숨김은 보조). 답변 캐시는 resident 채널만 |
| ai-core | 오케스트레이터·도구 17종 | 도구는 전부 읽기 전용. tenant·소유권·대상 세대는 LLM 인자가 아니라 코드가 주입 |
| ai-worker | 인제스트·색인 잡(arq) | `liviq_worker` 롤로 붙는다(RLS 적용 대상) |
| db | 모델·마이그레이션·RLS SQL | 마이그레이션만 owner. 헤드는 항상 선형으로 유지(병렬 브랜치 주의) |
| ui | 디자인 토큰·프리미티브·어시스턴트 코어 | 신규 컴포넌트는 `src/index.ts` export 필수. 두 앱이 소비하므로 씬·파서 수정은 양쪽에 반영된다 |
| mcp | 외부 연동 프로토타입(동결) | 크레덴셜 커밋 금지, fail-closed 마스킹 |
