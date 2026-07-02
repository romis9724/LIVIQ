# MEMORY — LIVIQ 프로젝트 암묵지

에이전트·신규 기여자가 코드만 봐서는 알 수 없는 **결정 근거·비자명한 사실**을 모은다.
"왜 이렇게 되어 있나?"의 답. 결정이 바뀌면 여기와 [docs/adr/](docs/adr/README.md)를 함께 갱신.

> 규칙: 코드/커밋/문서로 이미 알 수 있는 것은 적지 않는다. 비자명한 것만.

## 아키텍처·경계

- **AI는 계층이지 앱이 아니다.** 기존 시스템 위에 검색·응대·요약을 얹는다. 입주민 앱/관리 웹을
  재구현하지 않는다. → 신규 기능은 "AI가 무엇을 돕는가"로 프레이밍. [ADR-0001](docs/adr/0001-monorepo-layered-ai.md)
- **api·ai-worker·db·ai-core는 아직 없다.** CLAUDE.md 스택은 목표 아키텍처. 현재는 웹 2종 + ui/config-ts + mcp(Python).
  → 없는 모듈을 참조하는 코드/문서 작성 금지. 도입 시 [ARCHITECTURE.md](ARCHITECTURE.md) 승격.
- **mcp/는 Python, TS 워크스페이스와 분리.** turbo/pnpm이 관리 안 함. 계약은 MCP 프로토콜로만.

## 보안·개인정보 (CRITICAL, 협상 불가)

- **개인정보 → 외부 LLM 전송 전 마스킹, 실패 시 호출 중단(fail-closed).** "일단 보내고 나중에" 없음.
  [ADR-0002](docs/adr/0002-mask-before-external-llm.md)
- **tenant 격리는 이중 방어**: 앱 쿼리의 `tenant_id` + DB RLS. 하나만으로 신뢰하지 않는다.
- **시크릿 파일**: `mcp/service-credential.json`·`tokens.json`은 `.gitignore`로 차단, 로컬 전용.
  로그·에러 메시지에도 노출 금지.

## 도메인 규칙 (놓치기 쉬움)

- **관리비는 ERP가 단일 출처.** AI는 값을 설명만, 계산·부과 절대 금지. [ADR-0003](docs/adr/0003-erp-single-source-fees.md)
- **입주민 대상 공지·알림은 초안까지만.** 자동발송 금지 — 사람이 검수 후 발송(관리 웹 review-queue).
- **출처 없는 AI 답변 금지.** 근거 문서·조항 인용 못 하면 지어내지 말고 담당자 연결 폴백.
- **신뢰도 낮은 답변은 검수 큐로.** `apps/web-admin/src/app/review-queue/`.

## Five-Question (모듈별 요약 · 상세는 각 CLAUDE.md)

| 모듈 | 소유(무엇) | 비자명 |
|------|-----------|--------|
| web-resident | 입주민 AI 응대·조회 UI | AI 화면은 CitationCard+ConfidenceBadge 필수 |
| web-admin | 검색·요약·검수·공지 초안 | 공지 자동발송 금지, review-queue 경유 |
| ui | 디자인 토큰·프리미티브 | 신규 컴포넌트는 `src/index.ts` export 필수 |
| mcp | 외부 연동·에이전트 | 크레덴셜 커밋 금지, fail-closed 마스킹 |
