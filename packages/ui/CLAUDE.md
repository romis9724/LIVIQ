# packages/ui

공유 디자인 시스템(`@liviq/ui`). 토큰 + 프리미티브 컴포넌트. 웹 앱 2종이 소비.

## 구조

```text
src/styles/tokens.css     디자인 토큰(색·간격·타이포). 단일 진실 출처
src/styles/               global · components · index css
src/components/<name>/     컴포넌트별 폴더(PascalCase.tsx)
src/lib/cx.ts             className 병합 유틸
src/index.ts              공개 배럴 — 신규 컴포넌트는 여기 export
```

## 명령

```bash
pnpm --filter @liviq/ui test                      # 전체 테스트 (vitest run)
pnpm --filter @liviq/ui test src/lib/cx.test.ts   # 단일 파일만 (인자가 vitest로 전달)
pnpm --filter @liviq/ui test:watch                # watch 모드
pnpm --filter @liviq/ui typecheck
pnpm --filter @liviq/ui lint
# 자체 build 없음 — 앱이 소스를 직접 소비. 빌드 검증은 루트 `pnpm build`
# typecheck 실패 흔한 원인: 신규 컴포넌트 export 누락 → src/index.ts 확인
```

## 의존성 (상세 그래프: [../../ARCHITECTURE.md](../../ARCHITECTURE.md))

- 의존: `@liviq/config-ts` (tsconfig)
- 피의존: `@liviq/web-resident` · `@liviq/web-admin` — **이 패키지 변경은 두 앱 모두에 파급**
- 규칙: 앱을 import하지 않음(단방향). Why: 순환 의존 방지

## 핵심 파일

- `src/styles/tokens.css` — 모든 색·간격·타이포 토큰. 앱은 이 토큰만 사용
- `src/components/citation-card/CitationCard.tsx` — 출처 표시(절대규칙 1 UI)
- `src/components/confidence-badge/ConfidenceBadge.tsx` — AI 신뢰도 표시
- `src/index.ts` — export 누락 시 앱에서 import 불가

## 자주 하는 수정 패턴

- **새 공유 컴포넌트 추가** — `src/components/<kebab-case>/PascalCase.tsx` + `PascalCase.test.tsx` 생성 후 `src/index.ts`에 export. 예시: `src/components/status-pill/StatusPill.tsx`(+`StatusPill.test.tsx`). 검증: `pnpm --filter @liviq/ui test`
- **기존 컴포넌트 variant 추가** — 컴포넌트의 variant 타입·클래스 확장. 예시: `src/components/button/Button.tsx` (`ButtonVariant`). 검증: `pnpm --filter @liviq/ui typecheck`
- **토큰 추가·변경** — `src/styles/tokens.css`만 수정(값 하드코딩 금지). 두 앱 전체에 파급. 검증: 루트 `pnpm build`(앱 빌드가 토큰 소비)

## 규칙 (Why)

- 값 하드코딩 금지 — `tokens.css` 변수만. Why: 테마·일관성.
- 컴포넌트는 프레젠테이션 순수 유지. 데이터 페칭 넣지 말 것. Why: 재사용성.
- 신규 컴포넌트는 `src/index.ts`에 반드시 export. Note: 빼먹으면 앱 빌드는 통과해도 import 실패.
- 접근성(WCAG 2.2 AA)은 컴포넌트 레벨에서 보장. Why: 앱마다 재구현 방지.
