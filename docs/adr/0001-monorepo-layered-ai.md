# ADR-0001: 모노레포 + AI 계층 아키텍처

- 상태: Accepted
- 날짜: 2026-06-20
- 갱신: 2026-07-13 — 백엔드 언어는 [ADR-0013](0013-python-backend.md)으로 Python 전환. 모노레포·계층 구조 결정 자체는 유지.
- 관련: [docs/01-architecture.md](../01-architecture.md), [ARCHITECTURE.md](../../ARCHITECTURE.md)

## 맥락

아파트 관리 업무의 비효율을 LLM·RAG로 줄이려 한다. 기존 관리 시스템·ERP·문서가 이미 존재한다.
그 위에 무엇을 만들 것인가, 어떻게 구성할 것인가가 문제였다.

## 결정

기존 시스템을 재구현하지 않고, 그 위에 얹는 **AI 검색·응대·요약 계층**으로 정의한다.
코드는 TypeScript 풀스택 **Turborepo + pnpm 모노레포**로 구성(apps/packages 분리),
외부 연동 에이전트는 별도 Python 트리(`mcp/`)로 둔다.

## 대안

- **독립 앱 재구현**: 범위 폭발·기존 ERP와 중복. 기각.
- **단일 패키지(모놀리스 레포)**: 웹·API·워커·공유 UI 경계가 흐려짐. 모노레포로 병렬 개발·경계 확보.
- **에이전트도 TS로**: Gmail/관리 시스템 연동 생태계가 Python에 성숙 → mcp만 Python 분리.

## 결과

- 웹 2종(web-resident·web-admin)이 `@liviq/ui`·`config-ts`를 공유 → 일관성·재사용.
- api·ai-worker·ai-core·db는 **목표 아키텍처**로 명시하되 아직 미구현. 도입 시 ARCHITECTURE.md 승격.
- 재검토 신호: 팀 규모·배포 경계가 모노레포 오버헤드를 넘어설 때.
