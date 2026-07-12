# apps/web-admin

관리사무소용 웹(`@liviq/web-admin`). Next.js App Router. 검색·요약·검수 중심.
루트 규칙([../../CLAUDE.md](../../CLAUDE.md)) 우선 — 특히 위험 출력 사람 검수·출처 인용.

## 구조

```text
src/app/    dashboard · inquiries · notices(+new) · review-queue · meetings · documents · facilities
src/features/   위 라우트별 도메인 로직 (inquiry-admin · notice-composer · dashboard · review-queue …)
src/components/admin-shell/   관리 셸(내비/레이아웃)
```

## 명령

```bash
pnpm --filter @liviq/web-admin dev
pnpm --filter @liviq/web-admin build
pnpm --filter @liviq/web-admin lint
pnpm --filter @liviq/web-admin typecheck
```

## 의존성 (상세 그래프: [../../ARCHITECTURE.md](../../ARCHITECTURE.md))

- 의존: `@liviq/ui` · `@liviq/config-ts`
- 피의존: 없음 (앱은 leaf)
- 외부: (계획) `apps/api` HTTP · JWT 인증
- 변경 파급: `@liviq/ui` 변경이 검수 큐·공지 초안 UI에 직결

## 핵심 파일

- `src/app/review-queue/` — 신뢰도 낮은 AI 출력 사람 검수 큐 (절대규칙 6)
- `src/features/notice-composer/` — 공지 **초안**만 생성, 자동발송 금지
- `src/app/documents/` · `src/app/meetings/` — 문서·회의록 검색/요약 (출처 인용)

## 자주 하는 수정 패턴

- **새 관리 라우트 추가** — `src/app/<name>/page.tsx` + `src/features/<name>/` 도메인 로직 생성. 예시: `src/app/review-queue/page.tsx` · `src/features/review-queue/`. 검증: `pnpm --filter @liviq/web-admin typecheck`
- **features/ 도메인 로직 수정** — `src/features/<name>/`에서 데이터·컴포넌트 수정. 예시: `src/features/notice-composer/`. 검증: `pnpm --filter @liviq/web-admin typecheck`
- **테스트 추가** — 컴포넌트는 `<Name>.test.tsx`, 순수 로직은 `data.test.ts` 규칙. 예시: `src/features/review-queue/ReviewQueue.test.tsx` · `src/features/review-queue/data.test.ts`. 검증: `pnpm --filter @liviq/web-admin test`

## 규칙 (Why)

- 공지·알림은 초안까지만. 입주민 자동발송 금지. Why: 절대규칙 6.
- AI 요약·검색 결과에 근거 문서·조항 표기. Why: 절대규칙 1.
- UI는 `@liviq/ui`만. 하드코딩 금지. WCAG 2.2 AA. Why: 접근성·일관성.
- 모든 데이터 조회는 서버에서 tenant·역할 검증 전제. Why: 절대규칙 3·4.
