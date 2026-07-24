# ADR — 아키텍처 결정 기록

중요한 아키텍처·정책 결정과 그 **근거·대안·결과**를 기록한다. 코드는 "무엇"을 말하지만
ADR은 "왜"를 말한다. 결정이 바뀌면 새 ADR로 이전 것을 `Superseded` 처리(삭제 아님).

- 형식: [_template.md](_template.md) 복사 → 다음 번호 부여.
- 요약 암묵지는 루트 [MEMORY.md](../../MEMORY.md), 구현 하네스 ADR 로그는 [09 §10](../09-implementation-harness.md).

## 목록

| # | 제목 | 상태 |
|---|------|------|
| [0001](0001-monorepo-layered-ai.md) | 모노레포 + AI 계층 아키텍처 | Accepted |
| [0002](0002-mask-before-external-llm.md) | 외부 LLM 호출 전 마스킹 (fail-closed) | Accepted |
| [0003](0003-erp-single-source-fees.md) | 관리비는 ERP 단일 출처, AI는 설명만 | Superseded by 0006 |
| [0004](0004-mcp-module-split-shared-store.md) | mcp 에이전트 모듈 분할 + 공유 store | Accepted |
| [0005](0005-single-llm-openai-compat.md) | 단일 LLM + OpenAI-호환 엔드포인트 추상화 · 임베딩 bge-m3 고정 | Accepted |
| [0006](0006-fees-excel-upload-source.md) | 관리비 원천 = 엑셀 업로드(ERP 어댑터는 추후) | Accepted |
| [0007](0007-readonly-tool-agent.md) | 읽기 전용 도구호출 에이전트 (정적 라우터 대체) | Accepted |
| [0008](0008-freeze-mcp-prototype.md) | mcp/ 프로토타입 동결 — 신규 AI는 ai-core | Accepted |
| [0009](0009-neo4j-in-mvp.md) | Neo4j를 MVP부터 포함 (FR-FAC-02 Must 승격) | Accepted |
| [0010](0010-envelope-encryption-env-master-key.md) | pii_vault 봉투 암호화 — env 마스터 키, KMS는 확장 시 승격 | Accepted |
| [0011](0011-redis-server-session.md) | Redis 서버 세션 + httpOnly 쿠키 (JWT stateless 대신) | Accepted |
| [0012](0012-in-app-notification-only.md) | MVP 알림은 인앱 알림함만, 웹푸시는 Phase 2 | Accepted |
| [0013](0013-python-backend.md) | 백엔드 Python 전환 (FastAPI·SQLAlchemy·arq·uv) | Accepted |
| [0014](0014-local-email-auth.md) | 자체 이메일+비밀번호 인증 (Google OAuth 대체) | Accepted |
| [0015](0015-notice-board-replaces-ai-draft.md) | 공지 AI 초안 제거·일반 게시판 전환 | Accepted |
| [0016](0016-document-board-versioned-attachment.md) | 문서관리 게시판 전환 — 첨부 1개·버전 이력·청크 소스 일반화 | Accepted |
| [0017](0017-tenant-code-registry.md) | 공통 코드 관리 — tenant 스코프 계층 코드로 하드코딩 분류 대체 | Accepted |
| [0018](0018-inquiry-manual-handling.md) | 민원 개편 — AI 분류 제거·카테고리 코드화·답변/댓글·상태 권한 | Accepted |
| [0019](0019-complex-twin-3d.md) | 단지 3D 트윈 — deck.gl + JSONB geometry, 기존 세대·명부 재사용 | Accepted |
