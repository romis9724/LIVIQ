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
| [0003](0003-erp-single-source-fees.md) | 관리비는 ERP 단일 출처, AI는 설명만 | Accepted |
| [0004](0004-mcp-module-split-shared-store.md) | mcp 에이전트 모듈 분할 + 공유 store | Accepted |
