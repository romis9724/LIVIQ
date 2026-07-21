# ADR-0014: 자체 이메일+비밀번호 인증 (Google OAuth 대체)

- 상태: Accepted
- 날짜: 2026-07-21
- 관련: [docs/06 §2](../06-security-privacy.md), [docs/00 §3.7](../00-requirements.md) FR-ONB, [docs/03 §4.1](../03-database-design.md), [docs/09 §8.8](../09-implementation-harness.md), [ADR-0011](0011-redis-server-session.md)(세션), [ADR-0010](0010-envelope-encryption-env-master-key.md)(봉투 암호화)

## 맥락

기존 인증은 Google OAuth 2.0 + PKCE(자체 비밀번호 미보관)였고, E2E는 mock IdP로 실 플로우를 검증했다. 운영자(프로젝트 오너) 요구사항 인터뷰(2026-07-21)에서 원하는 온보딩 흐름이 확정되며 두 문제가 드러났다.

- **구글 계정 의존**: 전 연령 입주민이 대상인 서비스에서 구글 계정 보유·로그인 숙련을 전제할 수 없다 — 가입 진입 장벽. 운영자는 이메일 기반 가입을 요구.
- **운영 흐름 복잡**: OAuth 콜백·PKCE·mock IdP·단지 초대코드 배포가 얽혀 가입 경로가 길고, 초대코드 배포·회수라는 오프라인 운영 부담이 있다. 요구 흐름(시스템 관리자→소장 등록→직원 등록→명부 업로드→주민 가입·승인)과도 구조가 맞지 않는다.

세션 모델([ADR-0011])·PII 봉투 암호화([ADR-0010])는 안정적으로 동작 중이므로 **인증 수단만** 교체할 수 있어야 하고, 규칙 2(개인정보 경계 차단)·규칙 4(서버 인가)를 그대로 지켜야 한다.

## 결정

인증을 **자체 이메일+비밀번호**로 교체한다(사용자 결정, 2026-07-21).

- **비밀번호**: **Argon2id**(argon2-cffi)로 해시 저장(평문·복호가능 형태 금지). 정책은 복잡도 규칙 대신 **길이 기준**(최소 10자, 초기값 — 파일럿 보정, NIST 계열).
- **이메일은 PII**: 평문 컬럼 금지 — `pii_vault.email_enc` 암호화 저장 + 로그인·중복체크는 **keyed HMAC 해시**(`users.login_id` ← email_hash, 기존 partial unique 인덱스 재사용). 이메일 전역 유니크(파일럿 단일 단지 수용).
- **이메일 검증**: 가입 시 검증 메일 필수 — **검증 전 로그인 불가**. 비밀번호 재설정 흐름도 같은 메일 인프라 재사용.
- **tenant 확정(초대코드 대체)**: 주민 가입은 **단지별 가입 링크**(관리사무소 게시 QR/URL의 단지 식별자)로 진입 — 초대코드 배포·회수 운영 제거.
- **토큰(`auth_tokens`)**: purpose(`verify_email`|`invite`|`reset_password`)·`token_hash`(SHA-256, 원문은 URL로만 전달·DB 미저장)·`expires_at`·`used_at`·`user_id`·`tenant_id`. TTL 초기값: verify 24h · invite 7d · reset 1h.
- **계정 생성 위계**: 최초 SYS_ADMIN은 설치 시드 스크립트가 생성(임시 비밀번호 출력, 첫 로그인 시 변경 강제, 시스템 테넌트 소속). SYS_ADMIN→소장, 소장→직원은 **초대 링크 메일**(purpose=`invite`)로 등록 → 수신자가 링크에서 비밀번호 설정. 주민은 자가 가입 → 소장 수동 승인.
- **역할 축소**: `FACILITY`·`COUNCIL` 제거(Phase 2 재도입 여지). 남는 역할 `SYS_ADMIN`·`MANAGER`·`STAFF`·`RESIDENT`.
- **메일 발송**: 어댑터 인터페이스(Protocol) 뒤 — `MAIL_BACKEND=console|smtp`(local 기본 console — 링크 로그 출력), SMTP는 env(`SMTP_HOST/PORT/USER/PASSWORD/FROM`). 파일럿 프로바이더: **Gmail SMTP**(`smtp.gmail.com:587` STARTTLS, 발신 계정 sllm14628@gmail.com — 2단계 인증 + **앱 비밀번호** 필요, 일반 비밀번호 불가. 앱 비밀번호는 env로만 주입).
- **세션**: [ADR-0011] 그대로 유지 — 인증 수단만 교체, 상태 전환 시 즉시 revoke 불변. 2FA는 파일럿 제외.

## 대안

- **Google OAuth 유지**: 기 구현·mock IdP 검증 자산이 있으나, 구글 계정 의존이 파일럿 주민 요구와 정면 충돌. 진입 장벽·운영 부담을 해소하지 못함. 기각.
- **OAuth + 자체 인증 병행**: 두 경로를 모두 지원하면 사용자 선택폭은 넓으나, 로그인 상태·세션·계정 병합(같은 이메일 다른 수단) 처리 복잡도가 파일럿 단일 단지 규모에 비해 과함. YAGNI. 기각.

## 결과

- **메일 인프라 필요**: 검증·초대·재설정이 메일 발송에 의존 — local은 console 어댑터로 대체(링크 로그 출력), 파일럿은 Gmail SMTP. 무료 Gmail 일일 발송 한도(약 500통)는 파일럿 규모(90세대)에 충분 — 초과 수요가 생기면 전용 발송 서비스(SES 등)로 어댑터 뒤에서 교체.
- **비밀번호 책임 자체 보유**: 해시 저장·검증·재설정·레이트 리밋(로그인 무차별 방어)을 직접 소유 — Argon2id·검증 전 로그인 차단·토큰 1회용 소진이 CRITICAL 게이트.
- **[ADR-0011] 세션 모델 불변**: OAuth 콜백 관련 서술만 무효화되고 Redis 서버 세션·즉시 revoke는 그대로.
- **mock IdP 제거**: E2E는 실 이메일 인증 여정으로 재작성([09 §8.8](../09-implementation-harness.md) H7-4), seed_demo도 이메일 계정·초대 토큰으로 갱신.
- 재검토 신호: 다단지 확장으로 사용자 규모가 커지고 SSO(구글·기업 IdP) 수요가 생기면 OAuth를 **추가 경로**로 재도입 검토(현 결정은 대체이지 SSO 영구 배제가 아님).
