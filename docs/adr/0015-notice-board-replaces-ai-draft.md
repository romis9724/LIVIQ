# ADR-0015: 공지 AI 초안 제거·일반 게시판 전환

- 상태: Accepted
- 날짜: 2026-07-22
- 관련: [docs/00 §3.4](../00-requirements.md) FR-ADM-01, [docs/01 §13](../01-architecture.md)(공지 API), [docs/03 §4.4](../03-database-design.md)(notices·notice_attachments), [docs/04](../04-menu-structure.md)(공지사항 메뉴), [docs/09 §8.10](../09-implementation-harness.md), [ADR-0014](0014-local-email-auth.md)(H7-2 STAFF 인가 축소), [ADR-0012](0012-in-app-notification-only.md)(인앱 알림)

## 맥락

기존 공지는 **키워드 입력 → AI 초안 생성(ai-core) → 검수 → 발행**(MANAGER 전용) 흐름이었다(H2-4, `notice_drafts` 테이블·초안 API 2개·`notice_draft.py`). 운영자(프로젝트 오너) 요구사항 인터뷰(2026-07-22)에서 실무 흐름이 확정되며 이 구조가 맞지 않음이 드러났다.

- **AI 초안이 불요**: 공지는 관리사무소가 직접 작성하는 **정형 문서**다(단수·소독·공사 안내 등 반복 양식). 키워드로 문장을 생성받는 단계가 오히려 손이 더 가고, 출처 인용 강제·검수 게이트는 정형 공지에 과하다.
- **첨부파일이 실제 요구**: 안내문 원본(pdf·hwp·hwpx·docx·xlsx·이미지) 배포가 핵심 니즈인데 기존 초안 경로에는 첨부 개념이 없다.
- **발행 권한 병목**: H7-2에서 발행은 소장 전용이었으나, 실무상 직원(STAFF)도 공지를 올려야 한다.

인앱 알림([ADR-0012])은 그대로 쓰고, 게시판 자체에는 개인정보·LLM 경계가 없으므로 규칙 2·4는 영향 없다.

## 결정

공지를 **AI 초안 없는 일반 게시판**으로 전환한다(사용자 결정, 2026-07-22).

- **AI 초안 자산 완전 삭제**: ai-core `notice_draft.py`·초안 API 2개(`POST`·`GET /admin/notices/drafts`)·`notice_drafts` 테이블을 drop한다(파일럿 초안 데이터 폐기).
- **게시판 기능**: 작성·수정·삭제(soft delete)·상단 고정(`pinned`)·임시저장(`status=draft`)·예약 발행(`status=scheduled`). 상태는 `draft|scheduled|published`(기존 `retracted|superseded` 제거).
- **첨부파일**: pdf·hwp·hwpx·docx·xlsx·jpg·jpeg·png, **파일당 20MB·공지당 최대 5개**, MinIO 저장(`storage_key={tenant_id}/notices/{notice_id}/{attachment_id}`). 다운로드는 **API 경유**(세션 인가·tenant·published 검증, presigned URL 미사용). `notice_attachments`는 `tenant_id` 표준 RLS 대상.
- **권한**: **MANAGER·STAFF 모두** 작성·발행(H7-2의 "발행 소장 전용" 부분 개정 — 발행만 STAFF에 개방, 관리비·시설·검수·승인·명부·직원·설정은 소장 전용 유지).
- **예약 발행**: `ai-worker` arq cron이 1분 폴링으로 `scheduled_at` 도달 공지를 `published`로 전이 + 대상자 알림 생성. 즉시 발행·예약 도달 발행 모두 인앱 알림 생성([ADR-0012]).
- **RAG 미인제스트**: 공지 본문·첨부는 문서 RAG로 인제스트하지 않는다(현행 유지).
- **메뉴명**: "공지 초안" → "공지사항".
- **eval 케이스 제거**: 규칙 6 케이스 `broadcast-01-draft-only`·`review-02-notice-draft` 삭제(공지 경로 AI 미개입 → 자동발송 리스크 원천 제거). 규칙 6 자체(assistant 저신뢰 → 검수 큐)는 유지.

## 대안

- **AI 초안 유지 + 첨부만 추가**: 기존 초안·검수 자산을 살리면서 첨부를 얹는 안. 그러나 운영자가 AI 초안 자체를 불요로 판정했고, 쓰지 않는 경로·테이블·eval을 남기면 유지비만 든다(YAGNI). 기각.
- **발행 소장 전용 유지**: H7-2 인가를 보존하는 안. 실무상 직원이 공지를 못 올리는 병목이 확인되어 기각 — 발행만 개방하고 나머지 소장 전용 경계는 유지.

## 결과

- **공지 경로 AI 미개입**: 규칙 6(입주민 자동발송 금지)의 **공지 표면이 원천 제거**된다. CLAUDE.md 절대 규칙 6과 규칙 6 eval은 assistant 등 **다른 AI 표면**에 그대로 유지된다(공지 케이스 2개만 삭제).
- **`notice_drafts` 데이터 폐기**: 파일럿 초안 데이터는 마이그레이션에서 drop. 초안 인용은 message 전용이 아니었으므로 citations 스키마 영향 없음.
- **H7-2 인가 부분 개정**: STAFF 발행 허용은 [ADR-0014] H7-2 인가 축소의 부분 개정 — 발행 외 소장 전용 경계는 불변.
- **CRITICAL 게이트**: 첨부 다운로드 인가(교차 tenant 첨부 접근 거부·미발행 공지 첨부 입주민 접근 거부)가 CRITICAL. 확장자/크기/개수 화이트리스트 검증은 업로드 경계에서 fail-closed.
- **신규 의존**: `ai-worker` arq cron 폴링(예약 발행)·MinIO 첨부 버킷.
- 재검토 신호: 공지 작성에 초안 보조(요약·번역 등)가 다시 필요해지면 **읽기 전용 보조 도구**로 재도입 검토(현 결정은 초안→발행 자동 흐름 제거이지 공지 AI 영구 배제가 아님).
