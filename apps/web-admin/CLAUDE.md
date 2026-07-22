# apps/web-admin

관리사무소용 웹(`@liviq/web-admin`). Next.js App Router. 검색·요약·관리 중심.
루트 규칙([../../CLAUDE.md](../../CLAUDE.md)) 우선 — 특히 위험 출력 사람 검수·출처 인용.

## 구조

```text
src/app/    dashboard · inquiries · notices(+new) · documents · facilities
src/features/   위 라우트별 도메인 로직 (inquiry-admin · notice-composer · dashboard …)
src/components/admin-shell/   관리 셸(내비/레이아웃)
```

## 명령

```bash
pnpm --filter @liviq/web-admin dev
pnpm --filter @liviq/web-admin build
pnpm --filter @liviq/web-admin lint
pnpm --filter @liviq/web-admin typecheck
pnpm --filter @liviq/web-admin test                          # 전체 테스트 (vitest run)
pnpm --filter @liviq/web-admin test src/lib/codes.test.ts    # 단일 파일만 (인자가 vitest로 전달)
# typecheck 실패 흔한 원인: @liviq/ui 미export 심볼 import → packages/ui/src/index.ts 확인
```

## 의존성 (상세 그래프: [../../ARCHITECTURE.md](../../ARCHITECTURE.md))

- 의존: `@liviq/ui` · `@liviq/config-ts`
- 피의존: 없음 (앱은 leaf)
- 외부: (계획) `apps/api` HTTP · JWT 인증
- 변경 파급: `@liviq/ui` 변경이 공지사항·문서 게시판 UI에 직결

## 핵심 파일

- `src/features/notice-composer/NoticeComposer.tsx` — 공지 **초안**만 생성, 자동발송 금지
- `src/app/documents/page.tsx` — 문서 검색/요약 (출처 인용 · 회의록은 문서 유형으로 통합)

## 자주 하는 수정 패턴

- **새 관리 라우트 추가** — `src/app/<name>/page.tsx` + `src/features/<name>/` 도메인 로직 생성. 예시: `src/app/notices/page.tsx` · `src/features/notice-composer/`. 검증: `pnpm --filter @liviq/web-admin typecheck`
- **features/ 도메인 로직 수정** — `src/features/<name>/`에서 데이터·컴포넌트 수정. 예시: `src/features/notice-composer/`. 검증: `pnpm --filter @liviq/web-admin typecheck`
- **테스트 추가** — 컴포넌트는 `<Name>.test.tsx`, 순수 로직은 `data.test.ts` 규칙. 예시: `src/features/dashboard/Dashboard.test.tsx` · `src/lib/codes.test.ts`. 검증: `pnpm --filter @liviq/web-admin test`

## 규칙 (Why)

- 공지·알림은 초안까지만. 입주민 자동발송 금지. Why: 절대규칙 6.
- AI 요약·검색 결과에 근거 문서·조항 표기. Why: 절대규칙 1.
- UI는 `@liviq/ui`만. 하드코딩 금지. WCAG 2.2 AA. Why: 접근성·일관성.
- 모든 데이터 조회는 서버에서 tenant·역할 검증 전제. Why: 절대규칙 3·4.
