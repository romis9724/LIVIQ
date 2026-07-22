# ADR-0017: 공통 코드 관리 — tenant 스코프 계층 코드로 하드코딩 분류 대체

- 상태: Accepted
- 날짜: 2026-07-22
- 관련: [docs/03 §4.10](../03-database-design.md) · [docs/01 §13](../01-architecture.md) · [docs/04](../04-menu-structure.md) · [docs/09 §8.10](../09-implementation-harness.md)(H8-4~6) · [ADR-0015](0015-notice-board-replaces-ai-draft.md)(공지 게시판) · [ADR-0016](0016-document-board-versioned-attachment.md)(문서 게시판) · 운영자 인터뷰 확정(2026-07-22)

## 맥락

실단지 공지 샘플을 등록하려니 게시글에 분류(말머리)·행사/작업 기간·대상 동·키워드 같은 부가 필드가 필요했다(2026-07-22 인터뷰). 그런데 공지 분류는 단지마다 다르고, 문서관리도 이미 `documents.source_type`을 하드코딩 5종(규약·회의록·공지·지침·매뉴얼)으로 고정해 두고 있었다 — 코드에 박힌 enum은 단지별로 다른 분류 체계를 담지 못하고, 항목 추가·정렬·비활성화가 배포를 요구한다.

제약: 절대 규칙 3(tenant 격리 + RLS), 규칙 8(분류 시드 같은 액션은 LLM이 아니라 코드가 실행), 파일럿은 단지 수가 적어 단지별 분류 편차를 초기부터 흡수해야 한다.

## 결정

분류를 하드코딩하지 않고 **tenant 스코프 계층 공통 코드**(그룹→코드, `parent_id` 자기참조)로 관리한다. 관리자 **설정** 메뉴(MANAGER 전용)를 신설하고 하위에 "코드 관리"(계층형 공통 코드)·"동/호수 관리"를 둔다. 공지 분류(NOTICE_CATEGORY)·문서 카테고리(DOC_CATEGORY)가 첫 소비처이며 H8-6에서 도메인 테이블이 `codes.id`를 FK로 참조 전환한다.

### 확정 사항

| 항목 | 결정 |
|---|---|
| 스키마 | `code_groups(tenant_id, group_key, name, is_system)` + `codes(tenant_id, group_id, parent_id NULL, code, label, sort_order, active)` — [docs/03 §4.10](../03-database-design.md) |
| 격리 | 표준 tenant RLS(§5 일반 규칙 — 예외 아님), composite FK로 cross-tenant 차단 |
| 계층 | `parent_id` 자기참조. UI 2단계 권장, DB 깊이 무제한 — 순환 방지는 앱 검증 |
| 시스템 그룹 | `is_system=true` 그룹은 삭제·`group_key` 변경 불가(코드 행은 추가·수정·정렬·비활성·삭제 가능) |
| 삭제 | soft delete 아님 — **하드 삭제 + CASCADE**(그룹→코드). 도메인 참조는 H8-6에서 FK **RESTRICT**(참조 중 코드 삭제 409, `active=false` 비활성으로 숨김 권장) |
| 기본 시드 | 단지 생성 시 시드 + 기존 단지는 마이그레이션 시드. NOTICE_CATEGORY(일반·시설점검·방역소독·회의결과·주민행사·시스템장애 — '일반' 기본), DOC_CATEGORY(규약·회의록·공지·지침·매뉴얼) |
| API | `/admin/code-groups`·`/admin/codes` CRUD — 쓰기 MANAGER, 조회는 MANAGER·STAFF(공지·문서 작성 폼 소비 겸용, STAFF 읽기 전용) |
| 분할 | H8-4 코드 관리 → H8-5 동/호수 관리 → H8-6 공지·문서 코드 적용 |

## 대안

- **고정 enum 유지**: 단지마다 다른 분류 체계에 경직 — 항목 추가·정렬·비활성이 배포를 요구하고 단지별 편차를 못 담는다. 기각.
- **자유 텍스트 분류**: 오타·표기 흔들림으로 일관성 없음 — 필터·집계·타게팅의 기준이 안 된다. 기각.
- **단일 평면 코드 테이블(계층 없음)**: 향후 대분류→소분류 요구(예: 시설 유형 트리)를 못 담아 곧 재설계. `parent_id` 하나로 흡수. 채택.

## 결과

- 이득: 단지별 분류를 배포 없이 관리, 공지·문서가 H8-6에서 하드코딩 분류를 코드 참조로 전환, 다른 메뉴 분류(민원 카테고리·시설 유형 등)도 그룹 추가만으로 흡수 가능.
- 비용: 도메인 테이블의 FK RESTRICT 전환·기존 `source_type` 라벨 매핑 마이그레이션(H8-6), 설정 메뉴 신설(H8-4).
- 후속: H8-5(동/호수 관리), H8-6(공지·문서 코드 참조 전환). notices 부가 필드(event_start/end·target_buildings·keywords)는 H8-6에서 동반 추가.
- 재검토 신호: 코드 계층이 실제로 3단계 이상 필요해지거나 단지 간 공용 코드(시스템 테넌트 상속) 요구가 생기면 그룹 상속 모델을 별도 ADR로 검토.
