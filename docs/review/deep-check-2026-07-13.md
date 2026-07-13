# 구현 착수 전 심층 점검 (2026-07-13)

5개 관점(기획·UX·아키텍처/데이터·보안/운영·구현 준비도) 병렬 감사 — 총 59건 발견.
같은 날 사용자 인터뷰로 12개 결정 확정 후 문서·코드 반영 완료. 이 파일은 발견·결정·처리의 기록이다.

> 표기: ✅ 반영 완료 · ⏭ 구현 단계(H0~) 과제로 문서에 기록됨 · ⏸ 의도적 보류

## 인터뷰 확정 결정 12건 (전부 반영)

| # | 결정 | 정본 위치 |
|---|------|-----------|
| 1 | pii_vault 키 = env 마스터 키 + 봉투 암호화, 확장 시 KMS 승격 | [ADR-0010](../adr/0010-envelope-encryption-env-master-key.md) · 06 §4.1 |
| 2 | tenant 식별 = 단지 초대코드 | 00 FR-ONB-02 · 11 §3.4 |
| 3 | 알림 = 인앱 알림함만, 웹푸시 Phase 2 | [ADR-0012](../adr/0012-in-app-notification-only.md) · 03 notifications |
| 4 | 만 14세 미만 가입 차단 | 00 FR-ONB-02 · 06 §4.4 |
| 5 | user↔household 1:1 유지, 이사=FK 변경, 다세대 소유 미지원 | 00 §6 가정 |
| 6 | 명부 재업로드 = diff 병합 (매칭 행 불변·전출 후보 표시) | 00 FR-ONB-07 |
| 7 | 승계 경계: 민원=본인 한정 · 관리비=입주 승인 이후 월만 | 00 FR-RES-02/FR-FEE-03 · 06 §2 |
| 8 | MANAGER = 테넌트 생성 시드 초대, 교체=신임 초대+구 비활성 | 00 FR-ONB-08 · 03 §8 |
| 9 | 세션 = Redis 서버 세션 + 즉시 revoke + PKCE | [ADR-0011](../adr/0011-redis-server-session.md) · 06 §2 |
| 10 | 검수 큐 = 사후 검수(품질 개선용, 재전달 없음) | 00 FR-AI-04 |
| 11 | COUNCIL 게시판 = MVP 컷 (문서 열람만) | 00 §2 · 04 |
| 12 | 탈퇴 = 즉시 비식별 + 30일 유예 파기 | 00 FR-ONB-09 · 06 §4.4 |

## 차단급 발견 5묶음 — 처리 결과

1. ✅ **동의 수집 플로우 부재** → FR-ONB-02에 동의 단계(목적별·policy_version)+14세 게이트, 11 §3.4 플로우 반영
2. ✅ **KMS·시크릿 도구 미선정** → ADR-0010 (env 마스터 키 확정)
3. ✅ **env 계약·compose 부재** → `.env.example`(전 변수+검증 소유 주석)·`infra/docker-compose.yml`(pg16/pgvector·redis·minio·neo4j 5-community) 신규, 02 §9 neo4j 정합
4. ✅ **ai-worker cross-tenant 폴링 ↔ RLS 모순** → 03 §5 워커 role 정책(outbox·jobs 한정 cross-tenant + SET LOCAL, BYPASSRLS 없이)
5. ⏭ **데이터 입구 화면 미설계** (온보딩 3·가입승인 1·관리비 업로드 1·평면도) → 플로우·FR은 확정 반영, **화면 설계는 다음 디자인 사이클 P0** — 평면도 에디터는 저충실 프로토타입 선행 권고

## 주요 발견 — 처리 결과

- ✅ 관리자 프로비저닝·명부 재업로드·승계 경계·탈퇴·household 모델 → 결정 5~8·11·12로 해소
- ✅ 전역 테이블 RLS 예외(`ai_eval_golden` NULL·`tenants`) → 03 §5 예외 표
- ✅ 알림 서브시스템 → ADR-0012 + 03 notifications + notices retracted/superseded·scheduled_at
- ✅ 인증 소유 문서 → 06 §2 확정(수명 초기값·revoke·2FA 권장·토큰 미저장)
- ✅ pii_vault 복호화 경로 모순(DB 뷰 복호화 vs 봉투) → 03 §6 재작성(복호화=앱 서비스만, 뷰=해시·배지)
- ✅ API 계약 부재 → 09 §1.1(DTO-first Zod@shared·SSE 이벤트 스키마), 상세 엔드포인트는 H1
- ✅ 공지→RAG 인제스트 경로 → 11 §3.1(발송=색인 트리거, 정정·철회=재색인/제거)
- ✅ 검수 전달 루프 모순 → 결정 10 + 목업 카피 수정
- ✅ 감사 추적 → 03 §4.7 append-only 강제(GRANT 제한) + 06 §3 break-glass
- ✅ 운영 축 → 06 §5 업로드 수치·매직바이트·서명 URL TTL / 09 §7.1 백업 표(PITR·키 백업) / §4.2 Testcontainers / §4.1 ci.yml 스펙 / §2.1 버전 핀 / 03 §8 시드·픽스처 분리
- ✅ 단계 번호 충돌·허공 참조 → 09 H0~H4 접두어 + §8.1 H0 체크리스트

## 보완·잔재 — 처리 결과

- ✅ 회의록 STT 목업 역류 → meetings 화면·라우트 삭제(관리자 7→6 화면), 11 §1 "음성" 제거
- ✅ ERP 잔재 → 04 "(추후)" 표기·FeesView 카피 수정
- ✅ 데드링크 `/reservations`·`/contacts` 제거, 푸시 카피 정정(알림함 기준)
- ✅ 관리비 "전체 교체" 표현 통일(03↔11)·citations FK ON DELETE SET NULL·DLQ 스냅샷 정책·컬럼 규약(KRW numeric(12,0)·timestamptz·partial unique·updated_at 트리거)
- ✅ CLAUDE.md `pnpm test` 추가·infra 실경로 반영
- ✅ 04 문서 검색 항목·관리자 모바일 방침·go/no-go 각주
- ⏭ 커버리지 thresholds 80(패키지별)은 ci.yml 작성 시(H0) 적용 — 09 §4.1에 명시
- ⏭ 인젝션 골든셋 케이스 → evals에 케이스 추가는 H1 (06 §5에 방어 설계는 반영됨)
- ⏸ 관리자 웹 모바일 상세 UX — 방침 1줄만 (파일럿 피드백 후)
- ⏸ 신뢰도 임계값·레이트 리밋 수치 — 파일럿 측정 후 (기존 보류 유지)

## 남은 열린 항목 (다음 사이클)

1. **화면 설계 P0**: 온보딩 3화면(초대코드·동의·대기/거절) · 관리자 가입 승인(명부 업로드 포함) · 관리비 엑셀 업로드 마법사 — design-handoff-prompt.md 갱신 필요
2. **평면도 좌표 에디터**: 스키마 검증용 저충실 프로토타입 선행
3. **@liviq/ui 선행 컴포넌트**: DataTable(URL state)·FileDropzone — 목록 화면 발산 방지
4. cursor-review ⏸ 4건 (기존 보류 유지)
