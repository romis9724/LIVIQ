# ADR-0018: 민원 개편 — AI 분류 제거·카테고리 코드화·답변/댓글·상태 권한 정형화

- 상태: Accepted
- 날짜: 2026-07-23
- 관련: [docs/01 §13](../01-architecture.md)(민원 API) · [docs/03 §4.4·§4.10](../03-database-design.md)(inquiries·inquiry_events·codes) · [docs/09 §8.10](../09-implementation-harness.md)(H8-9) · [ADR-0015](0015-notice-board-replaces-ai-draft.md)(공지 AI 제거) · [ADR-0017](0017-tenant-code-registry.md)(공통 코드) · 운영자 인터뷰 확정(2026-07-23)

## 맥락

민원 접수 시 백엔드 키워드 매칭(`classify_inquiry`)이 우선순위·카테고리를 자동 제안했으나(`ai_priority`·`ai_suggested_category_id`), 운영자는 이를 불요로 판단(2026-07-23 인터뷰). 공지·문서가 AI 초안·하드코딩 분류를 걷어낸 흐름(ADR-0015·0017)과 동일하게, 민원도 **사람이 분류·우선순위·처리를 직접 판단**하는 게시판형으로 정형화한다.

동시에 처리 워크플로가 비어 있었다 — 담당자 배정 UI는 "나에게 배정"뿐이고, 담당자↔입주민 소통 수단(답변/피드백)은 스키마(`inquiry_events.type="comment"`)만 정의되고 생성 경로가 없었다. 상태 전이는 아무 STAFF/MANAGER나 임의로 밀 수 있어 책임 주체가 불명확했다.

제약: 규칙 1(출처 있는 답변) 유지·규칙 6(위험 출력 사람 검수)·규칙 8(액션은 코드가 실행 — 상태·배정은 사람 액션 엔드포인트만). tenant 격리(규칙 3).

## 결정

민원에서 AI 개입을 제거하고, 분류를 공통 코드로 흡수하며, 담당자 중심의 처리 워크플로(배정·답변·피드백·상태 게이트)를 정형화한다.

### 확정 사항

| 항목 | 결정 |
|---|---|
| AI 분류 제거 | `inquiry_classify.py`·`ai_classified` 이벤트 생성 삭제. 과거 `ai_classified` 이벤트 리터럴은 읽기 호환 위해 유지(신규 생성 없음) |
| 카테고리 | `inquiry_categories` 테이블 폐기 → 공통 코드 그룹 **`INQUIRY_CATEGORY`**(ADR-0017). `inquiries.category_id`·`ai_suggested_category_id` → **`category_code_id`** composite FK(codes, RESTRICT, NULL 허용). 입주민이 접수 시 선택 |
| 우선순위 | `ai_priority` → **`priority`**(수동, urgent\|normal\|low, NULL 허용). 담당자·소장이 상세에서 지정 |
| 기본 시드 | `DEFAULT_CODE_GROUPS`에 `INQUIRY_CATEGORY` 추가(설비·하자·소음·주차·공용부·보안·기타) — 단지 생성 시드 + 기존 단지 마이그레이션 시드(단일 출처) |
| 배정 | 소장이 직원에게 배정 + 직원 self-assign + **직원 재배정**(휴가·이관). 배정 엔드포인트는 MANAGER·STAFF, 대상은 같은 tenant MANAGER·STAFF. 담당자 드롭다운용 `GET /admin/staff` 조회를 STAFF에도 개방(쓰기는 MANAGER 유지) |
| 답변(담당자→입주민) | `POST /admin/inquiries/{id}/comments` `type="comment"` `payload={kind:"reply"}` — **담당자만**(+소장 override). 작성자 알림 |
| 피드백(입주민→담당자) | `POST /inquiries/{id}/comments` `payload={kind:"feedback"}` — **작성자만, status=in_progress일 때만**. 담당자 알림 |
| 처리중 전환 | `in_progress`는 **배정된 담당자만**(+소장 override) |
| 완료 게이트 | `done`은 담당자만(+소장) **AND reply 이벤트 ≥1건**(없으면 422) — 답변 없는 완료 금지 |
| 소장 오버라이드 | MANAGER는 예외로 재배정·상태 역행·강제 전환 가능(운영 유연성) |

## 대안

- **AI 분류 유지·우선순위 자동**: 운영자가 불요 판단, 공지·문서 흐름과 불일치. 기각.
- **inquiry_categories 테이블 존치 + 별도 관리 UI 신설**: 코드 레지스트리(ADR-0017)가 이미 설정>코드 관리·시드·조회 API를 제공 — 그룹 추가만으로 흡수되고 별도 CRUD를 안 만들어도 됨. 테이블 존치는 관리 UI 중복. 기각.
- **답변/댓글 전용 테이블 신설**: `inquiry_events`가 이미 append-only 타임라인(GRANT SELECT·INSERT). `comment` 리터럴도 기정의 — payload `kind`로 reply/feedback 구분이면 충분. 신규 테이블은 YAGNI. 기각.

## 결과

- 이득: 민원 전 표면에서 AI 제거(규칙 1·6·8 표면 축소) · 분류를 배포 없이 관리 · 담당자 책임 명확(처리중·완료는 담당자, 답변 없는 완료 불가) · 담당자↔입주민 소통 성립.
- 비용: `inquiry_categories` 폐기 + FK 재배선 마이그레이션(문서 source_type 전환과 동일 패턴, label 매핑) · `ai_priority`→`priority` rename · 관리자 상세 뷰 신설.
- `default_assignee_role`·`sla_hours`(구 inquiry_categories 컬럼)는 소비처 없어 폐기 — 자동 배정·SLA 요구 생기면 코드 필드 확장 또는 별도 매핑으로 별도 ADR.
- 재검토 신호: 답변 승인 검수(규칙 6 강화)나 카테고리별 자동 배정 요구가 생기면 재검토.

## 개정 노트 (2026-07-24, 운영자 2차 피드백 — 상태 머신 액션화)

수동 상태 변경(`POST /admin/inquiries/{id}/status`)이 오조작·책임 불명을 낳아, 상태를 **액션의 부산물로만** 전이하도록 재설계했다. `change_inquiry_status`·`StatusChangeIn`·`STATUS_ORDER`·역행 로직을 완전 제거.

- **신규 상태 `reopened`** — `inquiries.status`는 plain String 컬럼이라 마이그레이션 불필요(값만 추가). `received`는 UI에서 "미배정"으로 표기(백엔드 값 유지, 프론트 담당).
- **전이(전부 액션 부산물)**:
  - 배정(`assign`, 기존): 미배정이면 assigned 자동, assigned/in_progress/reopened면 담당자만 교체(상태 유지), done이면 422 잠금.
  - `POST /admin/inquiries/{id}/ack`(신규): 담당자가 상세 열람 시 프론트가 호출. caller가 담당자이고 status=assigned일 때만 in_progress 전환(status_changed 이벤트), 그 외(비담당·소장·다른 상태·done)는 no-op(에러 아님).
  - `POST /admin/inquiries/{id}/complete`(신규): 담당자·소장, in_progress/reopened + reply ≥1(아니면 422) → done, 작성자 알림.
  - `POST /inquiries/{id}/reopen`(신규, RESIDENT): 작성자 본인이 done 민원을 재개 → reopened(status_changed {done→reopened}), 담당자 알림.
- **완료 잠금(done)**: 관리자 변경(assign·priority·category·reply·complete)은 done이면 422. 재개는 입주민 reopen뿐.
- **분류 수정 `POST /admin/inquiries/{id}/category`**(신규, 담당자·소장): `INQUIRY_CATEGORY` 코드 검증(null=미분류), done이면 422.
- **피드백**은 in_progress에 더해 **reopened**에서도 허용.
- **직원 목록 `GET /admin/staff`에 성명 추가** — `pii_vault.name_enc` 복호(관리 인가 뒤에서만, 복호 실패·부재 시 None). 배정 드롭다운에서 이메일 대신 실명 식별.
