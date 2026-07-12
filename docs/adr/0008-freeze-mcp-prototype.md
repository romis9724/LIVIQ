# ADR-0008: mcp/ 프로토타입 동결 — 신규 AI는 ai-core

- 상태: Accepted
- 날짜: 2026-07-13
- 관련: [ADR-0001](0001-monorepo-layered-ai.md), [ADR-0004](0004-mcp-module-split-shared-store.md), [docs/02 §2](../02-directory-structure.md), [리뷰 M4](../review/cursor-review.md)

## 맥락

레포에 Python `mcp/` 트리가 실존한다(Gmail·apt MCP 서버, 관리비 메일 에이전트 `fee_agent`, Ollama 연동). 목표 아키텍처는 TypeScript `ai-core`([02](../02-directory-structure.md))다. 두 AI 런타임이 공존해 신규 기능을 어디에 두어야 할지 불명했다(리뷰 M4).

## 결정

`mcp/`는 프로토타입으로 **동결**한다 — 참고용으로 보관하되 유지보수·신규 개발은 하지 않는다. 모든 신규 AI 기능은 `packages/ai-core`(TS)에 구현한다. `mcp/`가 제공하던 기능(관리비 안내 메일 등)이 필요해지면 `ai-core`에 재구현한다.

## 대안

- **병행 운영**: 두 런타임을 함께 유지 — 유지보수·경계 관리 비용 이중화. 기각.
- **즉시 폐기(삭제)**: 동작하는 코드 삭제 부담 + 참고 가치 상실. 기각.
- **ai-core로 즉시 포팅**: MVP 우선순위가 아님(메일 발송은 In Scope 아님). 기각.

## 결과

- 신규 기능의 위치가 `ai-core` 하나로 단일화된다.
- `mcp/`의 시크릿(`service-credential.json`·`tokens.json`)은 gitignore 유지, 커밋 금지.
- 재검토 신호: 메일 발송 기능이 MVP 요구로 승격될 때 → `ai-core` 포팅 ADR 신규 발행.
