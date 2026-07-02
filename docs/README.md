# LIVIQ 설계 문서

아파트 관리 AI 플랫폼 **LIVIQ**의 설계 문서 모음. 개발 시작점은 루트 [README.md](../README.md), 프로젝트 가이드는 [CLAUDE.md](../CLAUDE.md), 전체 사업 계획서는 [10-project-plan.md](10-project-plan.md) 참고.

## 한눈에

- **정체성**: 기존 아파트 시스템·문서 위에 얹는 **AI 검색·응대·요약 계층** (앱 재구현 아님)
- **스택**: TypeScript 풀스택 — Turborepo + Next.js + NestJS + PostgreSQL/pgvector + Drizzle + Redis
- **MVP**: 입주민 반응형 웹/PWA + 관리자 웹 + AI 코어 (동시 구축)
- **불변 원칙**: 출처 인용 · 환각 시 사람연결 폴백 · 개인정보 외부 LLM 미전송 · 단지 격리(RLS) · 위험 출력 사람 검수 · 토큰 절약

## 문서 목록 (읽는 순서)

| # | 문서 | 내용 |
|---|------|------|
| 00 | [요구사항 정의서](00-requirements.md) | 역할, FR/NFR, 제약(법규), KPI, 추적성 |
| 01 | [아키텍처 설계서](01-architecture.md) | C4, 멀티테넌시, RAG 파이프라인, 오케스트레이션, 스택, ADR |
| 02 | [디렉토리 구조](02-directory-structure.md) | 모노레포 apps/packages, 기능 단위 구성, 네이밍 |
| 03 | [DB 설계서](03-database-design.md) | ERD, 테이블, pgvector, RLS, 개인정보 분리 |
| 04 | [메뉴구조/IA](04-menu-structure.md) | 입주민/관리자 메뉴, 역할별 가시성, 사용자 여정 |
| 05 | [UI/UX 설계서](05-ui-ux-design.md) | 디자인 토큰, 컴포넌트, AI 대화 UX, 접근성, 반응형 |
| 06 | [보안/개인정보](06-security-privacy.md) | 위협모델, 인증/인가, 마스킹·분리·동의, 체크리스트 |
| 07 | [테스트 전략](07-testing-strategy.md) | 단위/통합/E2E + AI 평가, CI 게이트 |
| 08 | [LLM 토큰 절약](08-llm-token-optimization.md) | 캐싱·라우팅·컨텍스트 예산·비용 모니터링 |
| 09 | [구현/하네스](09-implementation-harness.md) | 빌드 순서, CI/CD, 훅, 단계별 플랜, Done 정의 |
| 10 | [사업 계획서](10-project-plan.md) | 범위·제약·일정·리스크 (구축 전제 실행 계획) |

## 참고 자료

- [refs/README.md](../refs/README.md) — 경쟁 솔루션(아파트너·아파트데스크) 분석 및 추출 화면

## 문서 규칙

- 수치는 별도 표기 없으면 **검증 전 가정값** — 파일럿으로 보정.
- 결정 변경 시 [09 §10 ADR 로그](09-implementation-harness.md)에 기록.
- 문서 간 중복 정의 금지 — 한 주제는 한 문서가 소유하고 나머지는 링크.
