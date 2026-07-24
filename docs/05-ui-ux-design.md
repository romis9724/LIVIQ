# 05. UI/UX 설계서

> IA: [04-menu-structure.md](04-menu-structure.md) · 인덱스: [README.md](README.md)
> 사용자 web 규칙(coding-style/design-quality/performance/testing) 준수.

## 1. 디자인 방향

대상은 **전 연령 입주민 + 실무 관리자**. 화려함보다 **명료함·신뢰**가 우선이다.

- 방향: **Trustworthy Utility** — 차분한 라이트 테마, 또렷한 위계, 충분한 터치 타깃.
- AI는 "마법"이 아니라 **근거를 보여주는 도구**로 표현(출처 카드 항상 노출).
- 다크모드는 기본값이 아님(전 연령 가독성). 시스템 설정 존중하되 라이트가 1차.
- 안티 템플릿: 균일 카드 그리드 남발 금지. 위계는 scale contrast·여백 리듬으로.

## 2. 디자인 토큰 (CSS custom properties)

`packages/ui`의 `tokens.css`에 단일 정의, 두 앱 공유.

```css
:root {
  /* color (oklch) */
  --color-surface: oklch(99% 0 0);
  --color-surface-sunken: oklch(97% 0.005 250);
  --color-text: oklch(22% 0.02 250);
  --color-text-muted: oklch(50% 0.02 250);
  --color-accent: oklch(58% 0.16 250);      /* 신뢰감 있는 블루 */
  --color-success: oklch(62% 0.15 150);
  --color-warning: oklch(75% 0.15 80);
  --color-danger:  oklch(58% 0.20 25);
  --color-citation: oklch(96% 0.03 250);    /* 출처 카드 배경 */

  /* type (모바일 가독성 우선, 본문 최소 16px) */
  --text-sm: 0.875rem;
  --text-base: clamp(1rem, 0.96rem + 0.2vw, 1.0625rem);
  --text-lg: clamp(1.125rem, 1rem + 0.5vw, 1.375rem);
  --text-title: clamp(1.5rem, 1.1rem + 1.6vw, 2.25rem);

  /* spacing rhythm */
  --space-1:.25rem; --space-2:.5rem; --space-3:.75rem; --space-4:1rem;
  --space-6:1.5rem; --space-8:2rem; --space-12:3rem;

  /* radius / elevation */
  --radius-sm:.5rem; --radius-md:.75rem; --radius-lg:1rem;
  --shadow-card: 0 1px 2px oklch(0% 0 0 / .06), 0 4px 12px oklch(0% 0 0 / .06);

  /* motion */
  --duration-fast:150ms; --duration-normal:280ms;
  --ease-out: cubic-bezier(.16,1,.3,1);

  /* touch */
  --tap-min: 44px;   /* 최소 터치 타깃 */
}
```

규칙: 팔레트·타이포·간격을 화면에 하드코딩하지 않고 토큰만 사용.

## 3. 컴포넌트 시스템 (`packages/ui`)

| 컴포넌트 | 용도 | 비고 |
|----------|------|------|
| `Button` | 액션 | size/variant, 로딩·비활성 상태 |
| `SurfaceCard` | 정보 카드 | elevation 토큰 |
| `ChatPanel` | AI 대화 | 스트리밍, 자동 스크롤, 입력 |
| `CitationCard` | 출처 표시 | 문서명·조항·페이지·원문링크 (AI 답변 신뢰의 핵심) |
| `ConfidenceBadge` | 신뢰도/상태 | answered/검토필요/담당자연결 |
| `FeedbackButtons` | 👍/👎 + 사유 | 품질 수집 |
| `StatusPill` | 처리상태/설비상태 | 색=semantic |
| `EmptyState` | 빈 목록 | 안내+행동 유도 |
| `DataTable` | 관리자 목록 | 정렬·필터(URL state)·페이지네이션 |
| `FormField` | 폼 | 라벨·에러·도움말, RHF+Zod |
| `Toast`/`Dialog` | 피드백·확인 | 발송 등 위험 액션 확인 |

## 4. AI 대화 UX (가장 중요)

원칙: **답변은 항상 근거와 함께, 모를 때는 모른다고.**

```text
┌─────────────────────────────────────────┐
│ 사용자: 인테리어 공사 가능한 시간 알려줘        │
├─────────────────────────────────────────┤
│ 🤖 평일 09:00~18:00에 가능합니다. 주말·공휴일은 │
│    제한됩니다.                               │
│  ┌── 📄 출처 ───────────────────────────┐  │
│  │ 관리규약 제32조(공사시간) · p.12  [원문]│  │
│  └────────────────────────────────────┘  │
│  [✅ 답변됨]            👍  👎             │
└─────────────────────────────────────────┘
```

상태별 표현:
- **answered**: 출처 카드 1개 이상 필수.
- **검토 필요(신뢰도 낮음)**: "정확한 확인이 필요해요" + [담당자 연결] 버튼.
- **handoff**: "담당자에게 전달했어요. 영업일 기준 N일 내 답변" + 민원 자동 생성 옵션.
- **스트리밍**: 첫 토큰 빠르게(<1.5s), 출처는 생성 완료 후 검증되어 표시.
- **위험 표현 금지**: 법적 해석·단정. 규약 해석이 갈리면 사람 연결.

## 5. 관리자 UX 핵심

- **공지 초안**: 키워드 폼 → AI 초안 → **편집기에서 검수** → [발송] 시 확인 다이얼로그. 자동발송 없음.
- **AI 검수 큐**: 카드별 (질문·AI답변·근거·신뢰도) → [승인]/[수정 후 승인]/[반려]. 승인 이력 감사.
- **문서 색인 상태**: pending/indexing/indexed/failed 가시화 + 실패 사유·재시도.
- **시설 도우미**: "원인 후보"임을 명시(단정 X), 근거 이력 링크.
- **단지 트윈**(H9): 3D 뷰도 라이트 테마·토큰 색 유지 — 오버레이 색은 semantic 토큰(success/warning/danger)만,
  범례 상시 표시(색만으로 상태 전달 금지 — 세대 클릭 상세로 텍스트 병기). 세대원 성함은 **마스킹 표시**(명부 규칙과 동일).
  WebGL 미지원·geometry 미설정은 명시적 빈 상태(§9)로 안내.

## 6. 접근성 (WCAG 2.2 AA)

- 시맨틱 HTML 우선(`header/nav/main/section`), 의미 없는 div 중첩 지양.
- 키보드 전체 조작, 가시적 focus ring, 논리적 tab 순서, skip-link.
- 명도 대비 본문 ≥ 4.5:1, 큰 텍스트 ≥ 3:1. 색만으로 상태 전달 금지(아이콘/텍스트 병기).
- 폼: label 연결, 에러 텍스트 + `aria-describedby`, 입력 자동확대 방지(16px+).
- 동적 영역(스트리밍 답변·토스트): `aria-live`.
- `prefers-reduced-motion` 존중: 모션 축소.
- 터치 타깃 ≥ 44px, 간격 충분.

## 7. 반응형 / 성능

- 브레이크포인트 테스트: 320·375·768·1024·1440·1920. 가로 스크롤 0. (시각 회귀 게이트 스크린샷은 **320·768·1024·1440** 4종 — [07 §4](07-testing-strategy.md).)
- 넓은 콘텐츠(표·그래프)는 자체 `overflow-x:auto` 컨테이너로.
- 애니메이션은 `transform/opacity`만. 레이아웃 속성 애니 금지.
- 이미지: 명시적 width/height, 본문 외 lazy, AVIF/WebP.
- 번들 예산(랜딩<150KB/앱<300KB gz), 무거운 라이브러리 동적 import.
  **예외(H9)**: 관리자 `/twin` 라우트는 deck.gl(WebGL) 탑재로 예산 초과 허용 — 라우트 단위 dynamic import로 격리해 타 페이지 번들 무영향이 조건.
- PWA: manifest·설치 가능. 오프라인 셸은 **공지 등 `tenant-public`만** 캐시. **관리비·민원·개인 대화는 service worker 캐시 금지**(`Cache-Control: no-store`). 오프라인 화면엔 데이터 기준 시점·stale 표시. 로그아웃·계정 전환 시 캐시 purge([06 §6](06-security-privacy.md)).

## 8. 콘텐츠/표현 가이드 (한국어)

- 존댓말, 간결. 전문용어 풀어쓰기.
- AI 답변 말미에 단정 회피("규정상 ~로 보입니다, 정확한 적용은 관리사무소 확인").
- 오류 메시지는 원인+다음 행동 제시("일시적 오류예요. 잠시 후 다시 시도하거나 담당자에게 연결할게요").

## 9. 상태 설계 (모든 화면 필수)

각 화면은 **로딩 / 빈 상태 / 오류 / 권한 없음 / 정상**을 모두 정의한다.
권한 없음은 빈 화면이 아니라 명확한 안내. 오류는 재시도 경로 제공.

## 10. 디자인 검증

- 주요 화면(비서·공지·민원·관리비·검수큐) 4 브레이크포인트 Playwright 스크린샷.
- 자동 접근성 검사(axe) CI 게이트.
- 자세한 케이스: [07-testing-strategy.md](07-testing-strategy.md) §시각/접근성.
