# apps/web-resident

입주민용 웹 앱(`@liviq/web-resident`). Next.js App Router. AI 1차 응대·조회 중심.
루트 규칙([../../CLAUDE.md](../../CLAUDE.md)) 우선 — 특히 출처 인용·마스킹·tenant 격리.

## 구조

```text
src/app/(resident)/   home · assistant · fees · inquiries · notices · me   # 라우트
src/features/         assistant · fees · inquiries · notices · me          # 도메인 로직
src/components/resident-shell/   앱 셸(내비/레이아웃)
src/lib/              클라이언트 유틸
```

## 명령 (루트에서 turbo가 오케스트레이션)

```bash
pnpm --filter @liviq/web-resident dev        # 개발 서버
pnpm --filter @liviq/web-resident build      # 프로덕션 빌드
pnpm --filter @liviq/web-resident lint
pnpm --filter @liviq/web-resident typecheck
```

## 의존성 (상세 그래프: [../../ARCHITECTURE.md](../../ARCHITECTURE.md))

- 의존: `@liviq/ui`(토큰·컴포넌트) · `@liviq/config-ts`(tsconfig)
- 피의존: 없음 (앱은 leaf)
- 외부: (계획) `apps/api` HTTP · JWT 인증
- 변경 파급: `@liviq/ui` 토큰/컴포넌트 변경이 이 앱 화면에 직결

## 핵심 파일

- `src/app/(resident)/layout.tsx` — 입주민 셸 진입
- `src/features/assistant/` — AI 문의 응대 UI (출처 카드·신뢰도 배지 필수)
- `src/app/(resident)/fees/` — 관리비 조회 (ERP 값 표시만, 계산 금지)

## 규칙 (Why)

- UI는 `@liviq/ui` 토큰·컴포넌트만 사용. 색·간격 하드코딩 금지. Why: 디자인 일관성·테마.
- AI 답변 화면은 반드시 `CitationCard`+`ConfidenceBadge` 노출. Why: 루트 절대규칙 1(출처).
- 관리비는 표시 전용. Why: 절대규칙 5(ERP 단일 출처).
- 인가는 서버 검증에 의존. 프론트 숨김은 보조. Why: 절대규칙 4.
