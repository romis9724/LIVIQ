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
- **실사 3D(VWorld) 뷰**(H9-3): `/twin`에 "기본 3D(deck.gl) ↔ 실사 3D(VWorld)" **뷰 토글**. 실사는 국토부 VWorld
  실사 건물 위에 세대 오버레이. 프로토타입은 풀스크린 다크지만 LIVIQ는 **관리 셀 임베딩**(사이드바·헤더 유지, 카드
  무대에 렌더) + UI 오버레이(범례·세대 상세)는 토큰 기반 밝은 패널로 통일. **키 미설정 빈 상태**(§9): `NEXT_PUBLIC_VWORLD_API_KEY`
  없으면 실사 뷰 대신 "VWorld 키 미설정 — 발급·등록 안내" 안내(기본 deck.gl 뷰는 정상 동작). Cesium은 무거우므로
  dynamic import(deck.gl과 동일 격리, [performance] 번들 예산 예외는 트윈 라우트 한정).
- **시설 그래프**(H13 · [ADR-0022](adr/0022-facility-graph-dashboard.md)): 시설관리 **메인이 3D force-directed
  그래프**(react-force-graph-3d — 노드 `Facility`·`Incident`·`Maintenance`, 엣지 `HAS_INCIDENT`·`HAS_MAINTENANCE`).
  - **렌즈 토글**: 계통별(기본 — `facilities.type`, 계통색) ↔ 위치별(동 단위, H13-2). 계통 클러스터는 포스
    그룹핑으로 만들고 가상 허브 노드는 두지 않는다. 색은 semantic·계통 토큰만(하드코딩 금지),
    **범례 상시 표시** + 색만으로 상태 전달 금지(노드 상태는 패널 텍스트로 병기 — §6).
  - **검색 → 카메라 fly-to**: 3D는 노드가 겹쳐 눈으로 찾기 어렵다. 검색 결과 선택 시 카메라가 해당 노드로
    이동·강조하는 경로가 **기본 탐색 수단**(선택 기능 아님). `prefers-reduced-motion`이면 이동 애니메이션 없이 즉시 이동.
  - **상세 패널**: 노드 클릭 → 현황(normal/check/fault/risk) · 정비 이력 · 고장 이력 · 관련 민원.
    데이터는 기존 `GET /admin/facilities/{id}` 재사용. 민원은 **정식 연결(담당자 지정·LLM 추천 승인)과
    위치 추정을 배지로 구분**하고, 추정은 "추정" 배지 + 근거(동 매칭) 문구를 함께 보인다 — 확정처럼 보이지 않게.
  - **접근성(WCAG 2.2 AA)**: WebGL canvas는 스크린리더·키보드로 탐색할 수 없다. 따라서 **목록 뷰가 그래프의
    동등 기능 대체 수단**이다 — 같은 화면의 토글로 항상 도달 가능하고(키보드 포커스 순서 앞쪽), 같은 설비·이력·
    민원을 표와 다이얼로그로 제공한다. 그래프는 **보조 표현**으로 취급하고 그래프에서만 가능한 조작을 만들지 않는다.
  - **빈/오류 상태**(§9): WebGL 미지원·시설 0건은 명시적 빈 상태로 목록 뷰를 권한다. **Neo4j 미가용**은 오류가
    아니라 PG 축약 그래프(노드만) + "관계 정보 일시 미표시" 안내 배너(`degraded` — [01 §10](01-architecture.md)).
  - **성능**: three.js는 무거우므로 `dynamic import` `ssr:false`로 시설 라우트에 격리(deck.gl·Cesium과 동일
    — §7 번들 예산 예외). 파일럿 규모(설비 수십)에서 상호작용 60fps 목표, **500+ 노드에서 저하되면 렌즈 필터
    기본 적용·2D/클러스터 축약 재검토**([ADR-0022](adr/0022-facility-graph-dashboard.md) 재검토 신호).
- **평면도**(H13-3~5 · [03 §4.8](03-database-design.md), FR-PLAN): 배경 이미지 위 좌표 마커 — CAD 벡터화 아님.
  - **스케일링**: 마커 좌표는 원본 이미지 **픽셀** 기준으로 저장·전달된다. 화면은 `x/width`·`y/height`로
    **%로 변환**해 배치하고, 배경 이미지는 SVG `viewBox`(또는 동등 CSS 비율 컨테이너)로 스케일링한다 —
    화면 크기·DPR과 무관하게 배치가 정확해야 한다.
  - **카테고리 오버레이 토글**: 전기/안전/통신/설비 4종 토글(다중 선택) — 끈 카테고리의 마커는 DOM에서
    제거하지 않고 `aria-hidden`+숨김 처리(목록 대체 표에서는 별도 필터로 동일 정보 제공, 아래 접근성 참고).
  - **마커 클릭 팝오버**: 라벨·메모·사진·연결된 `facilities` 상태(normal/check/fault/risk, `StatusPill`)를
    보여준다(FR-TWIN-04). 팝오버는 포커스 트랩 없는 비모달(`Dialog` 컴포넌트 재사용 아님 — 마커 클릭이 잦아
    모달 오버헤드 회피).
  - **입주민 뷰**: 홈 "우리집 평면도" 카드 → 세션 `household_id`로 즉시 해당 세대 평면도 직행(동·호 선택 UI
    없음 — [06] 본인 세대 한정 계약). 원본 도면이 없는 세대(unit_type_label 정규화 매칭 실패)는 빈 상태(§9).
  - **편집 모드**(H13-4, MANAGER): 시설관리 메뉴 안. 도면 이미지 업로드(드래그앤드롭, MinIO 서명 URL) →
    클릭으로 마커 추가, 드래그로 좌표 이동, 폼으로 방/방향/라벨/메모/사진/`facility_id` 편집. 저장은 명시적
    [저장] 액션(자동저장 아님 — 좌표 오조작 되돌리기 쉬워야 함).
  - **접근성**: WebGL·canvas가 아니라 배경 `<img>` + 절대 위치 오버레이라 스크린리더 대체가 상대적으로
    쉽다 — 각 마커는 `<button>`(라벨 `aria-label` = "{room} {device_type} — {label}")로 렌더링해 키보드
    포커스·클릭이 가능해야 한다. 시각 배치의 동등 대체 수단으로 **장치 목록 표**(방·유형·라벨 열, `DataTable`)를
    같은 화면에서 토글 가능하게 둔다(그래프 화면의 목록 뷰 대체 패턴과 동일).
  - **빈 상태**(§9): 평면도 자체가 없는 세대(unit_type 매칭 실패)·마커 0건(도면만 있고 미편집)을 구분해
    안내한다 — 후자는 관리자에게 "관리사무소에 문의" 대신 표시할 정보가 아직 없다는 취지로 문구를 다르게 한다.

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
  **예외(H13)**: 관리자 시설 라우트도 react-force-graph-3d(three.js) 탑재로 동일 예외 — 조건도 동일(`dynamic import` `ssr:false` 격리, [ADR-0022](adr/0022-facility-graph-dashboard.md)).
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
