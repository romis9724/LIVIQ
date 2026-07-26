# 06. 보안 / 개인정보 설계

> DB: [03-database-design.md](03-database-design.md) · 요구사항: [00 §5](00-requirements.md)
> 원칙: **개인정보는 경계에서 차단, 권한은 서버에서 강제, 단지는 격리.**

## 1. 위협 모델 (요약)

| 자산 | 위협 | 대응 |
|------|------|------|
| 입주민 개인정보(이름·연락처·동호수·생년월일) | LLM 전송 유출, 로그 노출, 타 입주민 열람 | 마스킹(전 프로바이더)·분리저장·RLS·로그 마스킹 |
| 세대 평면도(디지털트윈) | 타 세대 평면도 열람 | 본인 세대 한정 소유권 검증 + RLS |
| 단지 문서·민원 | 단지 간 혼입, 무권한 접근 | RLS + API 인가 + 공개범위 |
| 관리비 데이터 | 엑셀 오업로드·위변조, 무권한 조회 | 업로드 권한 MANAGER/STAFF 한정, 검증·미리보기·확정 2단계, `excel_uploads` 이력·감사 로그, 본인 세대 한정 조회 |
| 인증/세션 | 탈취, 권한상승 | 짧은 세션·재발급, 서버 인가, 감사 |
| AI 입력 | 프롬프트 인젝션, 무권한 액션 유도 | 액션=코드 실행, 입력 분리, 권한 재검증 |
| 파일 업로드 | 악성파일, 경로조작 | 타입·크기 검증, 격리 저장, 키 무작위 |

## 2. 인증 / 인가

- **인증**: **이메일+비밀번호 자체 인증**([ADR-0014](adr/0014-local-email-auth.md) — Google OAuth 대체). 비밀번호는 **Argon2id**(argon2-cffi)로 해시 저장(평문·복호가능 형태 금지). 정책: 최소 10자(초기값 — 파일럿 보정, 복잡도 규칙 대신 길이 기준 NIST 계열). **이메일은 PII로 평문 컬럼 금지** — `pii_vault.email_enc` 암호화 저장 + 로그인·중복체크는 **keyed HMAC 해시**(`users.login_id` ← email_hash, 기존 partial unique 인덱스 재사용, [03 §4.1](03-database-design.md)). 이메일 전역 유니크(파일럿 단일 단지 수용). 가입 시 **이메일 검증 메일** 필수(검증 전 로그인 차단), 비밀번호 재설정 흐름 포함. 주민 가입의 tenant 확정은 **단지별 가입 링크**(관리사무소 게시 QR/URL — 초대코드 대체). 세대정보 입력 → `pending`, 소장 승인 시 `active`. `pending`/`rejected`/`inactive`/`withdrawn` 계정은 API 접근 차단(대기·거절 안내 화면만).
- **인증 토큰(`auth_tokens`)**: purpose(`verify_email`|`invite`|`reset_password`) · `token_hash`(SHA-256, **원문은 URL로만 전달·DB 미저장**) · `expires_at` · `used_at` · `user_id` · `tenant_id`. TTL 초기값: verify 24h · invite 7d · reset 1h([03 §4.1](03-database-design.md)).
- **메일 발송**: 어댑터 인터페이스(Protocol) 뒤. `MAIL_BACKEND=console|smtp`(local 기본 console — 링크를 로그 출력), SMTP는 env(`SMTP_HOST/PORT/USER/PASSWORD/FROM`). 파일럿은 **Gmail SMTP**(STARTTLS·앱 비밀번호 — [ADR-0014](adr/0014-local-email-auth.md)). 앱 비밀번호는 시크릿(§7) — env로만 주입, 커밋 금지.
- **세션**: **Redis 서버 세션 + httpOnly·Secure·SameSite 쿠키**([ADR-0011](adr/0011-redis-server-session.md) — 인증 수단만 교체, 세션 모델 불변). 쿠키엔 세션 ID만, 상태는 서버 보관. 수명(초기값 — 파일럿 보정): access 세션 24h · idle 타임아웃 2h. `inactive`/`rejected`/`withdrawn` 전환 시 해당 사용자 세션을 서버 세션 스토어에서 **즉시 revoke**.
- **2FA**: 파일럿 **제외**(관리자 계정 탈취 영향 큼 — 재도입 신호로만 표기).
- **계정 생성 위계(초대 토큰)**: 최초 SYS_ADMIN은 설치 시드 스크립트가 생성(임시 비밀번호 출력, 첫 로그인 시 변경 강제) — **시스템 테넌트**(고정 UUID) 소속으로 RLS 정합, 권한은 **단지 생성 + 소장 초대만**(단지 콘텐츠 비열람). SYS_ADMIN→소장, 소장→직원(STAFF)은 **초대 링크 메일**(`auth_tokens` purpose=`invite`) → 수신자가 링크에서 비밀번호 설정. 소장 교체 = 신임 초대 + 구 계정 비활성화(escape hatch: SYS_ADMIN 재초대)([03 §8](03-database-design.md)).
- **인가(RBAC)**: FastAPI **의존성 주입 기반 가드**(역할·테넌트·소유권을 검증하는 dependency). **프론트 메뉴 숨김은 보조일 뿐**, 모든 엔드포인트가 서버에서 역할·테넌트·소유권을 검증.
- **소유권 검증**: 입주민은 본인/본인 세대 리소스만. (예: `inquiry.author_user_id === me` 또는 같은 household. 평면도는 `floor_plans`/`plan_devices`를 본인 `household_id`로만 조회 — 타 세대 접근 차단)
- **세대 승계 경계(결정 E)**: 세대 전출입으로 신규 입주민이 들어와도 — 민원 등 작성물은 **작성자 본인**(`author_user_id`)에게만 귀속(이전 거주자 민원 열람 불가), 관리비는 **입주 승인(`approved_at`) 이후 월(period)**만 조회 가능(승인 전·이전 거주자 기간 차단).
- **최소 권한**: ERP 연동은 읽기 전용 계정. 서비스 계정 분리.

## 3. 멀티테넌시 격리 (이중 방어)

1. **애플리케이션**: 모든 쿼리에 `tenant_id` 필터 + 요청 컨텍스트 검증.
2. **DB(RLS)**: 트랜잭션마다 `SET LOCAL app.tenant_id` → 정책으로 강제([03 §5]).

**2번의 성립 조건은 접속 롤이다.** 정책이 `ENABLE`+`FORCE`로 걸려 있어도 접속 롤이 `BYPASSRLS`(또는
superuser)면 무조건 통과한다 — H10-1 스모크 실측(2026-07-26)에서 앱이 owner 롤(`liviq` = superuser)로
접속해 tenant 컨텍스트 없이 `households` 322행을 읽던 상태가 그것이다. 정책 자체는 정상이었고 1번(쿼리
`tenant_id` 필터)이 유지돼 알려진 유출은 없었으나, **코드가 필터를 빠뜨리면 막을 층이 없었다**.
**H10-2에서 전용 접속 롤로 전환했다** — api는 `liviq_app`, ai-worker는 `liviq_worker`, 마이그레이션만 owner
([03 §5.1](03-database-design.md) 접속 롤 계약). 비밀번호는 env가 단일 출처이며 배포 스텝이 롤 속성
(`rolsuper`·`rolbypassrls` 부재)과 컨텍스트 없는 조회 0행을 **검증하고 아니면 중단**한다(fail-closed).
앱도 기동 시 자기 커넥션을 같은 기준으로 검사해 비-local에서는 기동을 거부한다. 실측·실연 기록은
[09 §8.13](09-implementation-harness.md) H10-2. **로컬 개발(네이티브)은 owner 접속을 유지**하므로
개발 환경에서는 2층이 비활성이다(경고 로그로 남는다) — 1층(쿼리 필터)과 `packages/db` 테스트가 방어선이다.
- 벡터 검색도 tenant 선필터(문서 혼입 차단).
- **Neo4j(시설 그래프)**: row RLS 없음 → 모든 노드에 `tenant_id` 프로퍼티 + **typed query 레이어 강제**(tenant predicate를 구조적으로 주입, raw Cypher 금지 — 코드 리뷰가 아니라 구조로 차단). 관계 생성 시 **양 끝 노드 tenant 일치 검증**([11 §4](11-data-architecture.md)). PG가 SoR이므로 파기·정정은 PG 기준으로 먼저 반영 후 그래프 재동기화.
- **`SYS_ADMIN` 허용 목록**(단지 콘텐츠 비열람 원칙의 구체화):
  - **접근 가능**: `tenants`(단지 메타), `jobs`, `outbox_events` 상태, 집계 메트릭(토큰/품질 대시보드), 공용 골든셋(`ai_eval_golden` `tenant_id` NULL)만.
  - **접근 불가**: 문서·민원·대화·PII·관리비·평면도 등 단지 콘텐츠 일체.
  - **감사 메타 열람**: SYS_ADMIN은 상시로 **감사 메타데이터**(행위·대상 ID·시각 — **콘텐츠 본문 제외**)만 열람 가능.
  - **예외 절차(break-glass)**: 장애 대응 등 부득이한 콘텐츠 열람은 ① `audit_logs`에 **사전 승인 행 선기록** → ② **시간제한 임시 권한** 부여 → ③ **사후 리뷰** 순으로만.

## 4. 개인정보 보호 (핵심)

### 4.1 데이터 최소화·분리
- 식별정보는 `pii_vault`에 **암호화** 저장, 업무 테이블은 참조키만([03 §6](03-database-design.md)).
- **키 관리(결정 A)**: 앱 레벨 **봉투 암호화(envelope, AES-256-GCM)**. 부팅 시 **env 마스터 키(KEK)**를 **Pydantic Settings로 검증**(누락 시 기동 실패), 데이터 키(**DEK**)는 **per-tenant**로 KEK가 감싸 저장. 복호화·마스킹은 **전용 애플리케이션 서비스**만 수행 — DB 뷰·LLM 경로는 복호화 불가([03 §6](03-database-design.md)).
- **키 교체**: 마스터 키/DEK 교체는 **재암호화 배치**(구 키 복호화 → 신 키 재암호화), 키 버전 컬럼으로 무중단 롤오버.
- **KMS 승격**: 다단지 확장 시 KEK를 **KMS/HSM 관리로 승격**(env 마스터 키 → KMS). 키 버전·교체 절차 규약은 동일 유지.
- 검색 해시는 정규화 후 **keyed HMAC**(단순 salted hash는 값 공간 작은 전화번호·생년월일에 사전 대입 취약). 평문 인덱싱 금지 — 상세 [03 §6](03-database-design.md).
- **생년월일**은 PII: `pii_vault` 암호화 저장, 소장 승인 대조 목적에 한정. 화면 표시 최소화·마스킹(`19**-**-**`).
- **차량번호**(H9-5)는 PII: `parking_vehicles.plate_enc`에 **같은 봉투 암호화**(per-tenant DEK)로 저장 — 평문 컬럼 없음, 검색 해시 불요(세대 귀속 데이터라 번호판 조회 경로가 없다). 복호는 **관리자(MANAGER) 주차장 조회 API**만 수행하고, 주차 관리 목적상 **마스킹 없이 전량 표시**한다(관리자 화면 한정). **입주민 앱·LLM 경로 미노출**(규칙 2 — 주차 데이터는 AI 도구 레지스트리에 없다). 세대 삭제 시 CASCADE로 함께 파기([03 §4.11](03-database-design.md)).

### 4.2 LLM 전송 차단 — 전 프로바이더 동일 (FR-AI-05, NFR-SEC-01)
- LLM/임베딩 호출 **직전** 마스킹/가명화: 이름→`[이름]`, 동호수→`[세대]`, 연락처→`[연락처]`.
- 마스킹 실패 시 호출 **중단**(fail-closed).
- **self-hosted(Ollama·vLLM)도 마스킹 예외 없음** — 프로바이더 구분 없이 동일 규칙(모델 교체 시 정책 재검토 불필요).
- 외부 API(OpenAI 등) 사용 시: **학습 비사용·데이터 미보관(zero-retention)** 계약 확인.
- 전송 페이로드는 별도 검사 로그(개인정보 패턴 탐지)로 사후 감사.

### 4.3 표시·로그
- 입주민 노출 화면은 마스킹 뷰(`홍*동`, `010-****-1234`).
- 앱 로그·`audit_logs`·트레이스에 개인정보 비저장(마스킹·해시).

### 4.4 동의·보관·파기
- 목적별 동의(`consents`), 철회 가능. 정책 버전(`policy_version`) 기록. **동의 수집 시점 = 가입 폼**(목적별 항목·`policy_version` 명시).
- **만 14세 미만 가입 차단**(법정대리인 동의 체계 미보유 — 파일럿 범위 제외).
- **탈퇴(결정 D)**: 요청 **즉시** `pii_vault` 비식별(개인정보 삭제) + `users.status=withdrawn`. 민원·대화 등 업무 기록은 **작성자 익명화 후 보존**(이력·통계 무결성), **30일 후 배치로 완전 파기**.
- **보관 기간(초기값 — 파일럿 보정)**:

| 항목 | 보관 | 파기 |
|------|------|------|
| 탈퇴 사용자 PII | 즉시 비식별 | 익명화 보존 → **30일 후 완전 파기** |
| 전출(비활성 `inactive`) | **1년**(재입주 대비) | 이후 파기 |
| 미가입 사전등록(`pre_registered`) | 명부 유효 기간 | **명부 삭제 시 즉시** |
| 감사 로그(`audit_logs`) | **3년** | 이후 파기 |

- **파기 전파 범위**: PII 삭제 시 파생 데이터도 함께 — pgvector 문서 청크(개인정보 포함 시)·S3 원본 파일·백업은 **백업 주기 도래 시** 순차 소거.
- 법정 보존 의무 항목은 별도 분리 보관. 처리방침 공개, 열람·정정·삭제 요청 처리 절차.

### 4.5 법규 준수
- 개인정보보호법(동의·목적제한·안전조치), 공동주택관리법(규약·회의록·관리비 공개는 **공식 채널**이 수행, AI는 보조).

### 4.6 명부 사전등록 (가입 전 개인정보)
- 소장이 명부 엑셀(성함·생년월일·동·호)을 업로드하면 `users`가 `pre_registered`로 사전 생성되고, PII는 `pii_vault`에 **암호화** 저장.
- 처리 근거: **공동주택 관리 목적**(위탁·이용 고지). 가입 시 입력값(성함·생일·동·호) 자동 대조("명부 일치")에만 사용 — **대조 목적 외 사용 금지**.
- 미가입 사전등록 데이터도 보관기간·파기 정책(§4.4)을 동일 적용.
- **파일럿 개시 체크리스트(사전등록 개인정보 고지)**:
  - [ ] 정보주체 고지 — 게시판 공고·안내문 등으로 명부 기반 사전등록·이용 목적 통지.
  - [ ] 위·수탁 계약 — 관리주체(입주자대표회의/위탁관리업체) ↔ LIVIQ 개인정보 처리 위탁 계약 체결.
  - [ ] 개인정보 처리방침 초안 게시(수집 항목·목적·보관기간·파기 절차).

## 5. 입력 검증 / 인젝션 방지

- 모든 경계 입력 검증(타입·길이·형식) — **서버 api는 Pydantic**, 웹 폼은 Zod. 신뢰하지 않는 외부 데이터(ERP·LLM 응답) 포함.
- SQL: ORM 파라미터 바인딩(문자열 결합 금지).
- XSS: React 기본 이스케이프, `dangerouslySetInnerHTML` 지양. 사용자 HTML 필요 시 검증된 새니타이저.
- **프롬프트 인젝션(입력)**: 검색 컨텍스트와 사용자 지시를 구분(역할 분리), 비신뢰 컨텍스트는 **delimiter로 감싸 "지시가 아닌 자료"임을 명시**. LLM 출력으로 권한·발송을 트리거하지 않음(액션은 코드가 실행, [01 §6](01-architecture.md)).
- **프롬프트 인젝션(출력)**: AI 응답의 링크·이미지는 **새니타이즈**(허용 도메인만 렌더, 그 외 차단), 마크다운/HTML 삽입 차단. **인젝션 골든셋 케이스**로 회귀 검증([07 §5](07-testing-strategy.md)).
- 파일 업로드: 화이트리스트 MIME·확장자 + **매직바이트 이중 검증**, 무작위 저장키, 실행권한 없는 버킷, 안티바이러스(가능 시).
  - **크기 상한(초기값 — 파일럿 보정)**: 엑셀 10MB · 문서 50MB · 사진 20MB.
  - **서명 URL**: 소유권 검증 API 경유 발급 + **TTL 10분**.
  - **엑셀 파싱은 워커에서 격리 실행**(API 프로세스와 분리 — 파싱 폭탄·메모리 방어).

## 6. 전송/저장 보안 · HTTP 헤더

```text
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=()
Content-Security-Policy: 기본 self, nonce 기반 script, 외부 origin 최소화
```
- TLS 1.2+. 저장 시 민감정보 암호화(at-rest), 키는 시크릿 매니저.
- **VWorld 실사 3D 예외(H9-3, [ADR-0019](adr/0019-complex-twin-3d.md) 개정)**: 관리자 트윈 실사 뷰는 국토부 VWorld 지도(Cesium)를 쓴다 — CSP 도입 시 `script-src`·`connect-src`·`img-src`에 `https://*.vworld.kr` 허용(외부 스크립트 로드는 이 뷰 한정). 프로토타입의 `document.write` 스크립트 주입은 nonce CSP와 충돌하므로 **동적 `<script>` append**로 로드. VWorld로 나가는 것은 **좌표·타일 요청뿐**(개인정보 전송 없음 — 규칙 2). VWorld 프론트 키(`NEXT_PUBLIC_VWORLD_API_KEY`)는 **서비스 URL 도메인 잠금**이라 번들 노출이 시크릿 유출이 아님(§7 예외) — 단 `.env.example`엔 placeholder만, 실제 키는 `.env`/`.env.local`.
- CSRF: 상태변경 요청 토큰/SameSite. 폼·발송 엔드포인트 레이트 리밋.
- **클라이언트/PWA 캐시**: 민감 화면(관리비·민원·개인 대화) 응답은 `Cache-Control: no-store`, service worker 캐시는 `tenant-public`(공지 등)만. 로그아웃·계정 전환 시 캐시 purge([05 §7](05-ui-ux-design.md)).

### 6.1 네트워크 경계 (배포 형상, H10)

> **왜 보안 문서에 있는가**: 절대 규칙 3(단지 격리)의 `tenant_id` 필터·RLS는 **앱·DB 층** 방어다. 데이터 서비스 포트가 퍼블릭에 열려 있으면 그 두 층을 **네트워크에서 우회**할 수 있으므로, tier 분리와 인바운드 제한이 **세 번째 방어선**이다.

배포 형상은 컨테이너 이미지 + [`infra/compose.prod.yml`](../infra/compose.prod.yml) profiles로 구성된 **3-tier VM**([ADR-0020](adr/0020-container-deploy-3tier-vm.md), [02 §9](02-directory-structure.md)).

| tier | 퍼블릭 노출 | 인바운드 허용 출처 | 담당 서비스 |
|------|------------|------------------|------------|
| web | **443만** | 인터넷 | 리버스 프록시(TLS 종단·[`infra/Caddyfile`](../infra/Caddyfile)), `web-resident`·`web-admin` |
| app | 없음 | **web tier에서만** | `api`, `ai-worker`, one-shot `migrate` |
| data | 없음 | **app tier에서만** | postgres+pgvector, redis, minio, neo4j |

- **data 서비스 포트는 프라이빗 IP에 바인드**한다(예: `10.0.0.x:5432:5432`) — 전 인터페이스(`0.0.0.0`) 바인드 금지. 로컬 dev compose([`infra/docker-compose.yml`](../infra/docker-compose.yml))의 `"15432:5432"` 형태는 전 인터페이스 바인드이므로 **운영 형상과 다르다**(로컬 편의용 — 운영에 복사 금지).
- **api는 퍼블릭 미노출**. 브라우저→api는 web tier 프록시의 **same-origin `/api` 프록시**(prefix strip) 경유. 부수 효과: ① 교차 출처 credentials 요청이 사라져 **CORS 허용 오리진(`WEB_ORIGINS`) 관리 표면이 줄고**, ② 세션 쿠키(`SameSite=lax` — `apps/api/app/deps.py`)가 same-site 조건을 자연히 만족한다.
- **보안 헤더·TLS 종단 소유권은 web tier 프록시**: 위 §6 상단 헤더 세트는 프록시가 **일괄 적용**한다(앱별 중복 설정 금지 — 헤더 드리프트·중복 헤더 방지). VWorld CSP 예외(§6)는 그대로 유효하며 프록시 CSP에 반영한다.
- **SSE 주의**: `text/event-stream` 응답(AI 스트리밍)은 프록시 **버퍼링을 끈다** — 안 끄면 응답이 고여 스트리밍이 죽는다(가용성 문제이나 보안 헤더와 **같은 지점**에서 설정하므로 함께 관리).
- **H10-1 실측 확인(노출면 1개)**: 1호스트 3프로필 스모크에서 api(`127.0.0.1:18000`)·postgres·redis·minio·neo4j는 전부 **`127.0.0.1` 바인드**, 웹 2종은 **호스트 퍼블리시 0**, `0.0.0.0`은 caddy(8080/8443)만 — 브라우저→api는 same-origin `/api` 프록시로만 도달했다([09 §8.13](09-implementation-harness.md)). 운영에서는 `DATA_BIND`·`APP_BIND`를 tier 프라이빗 IP로 지정한다.
- **CSP는 H10-1 시점 의도적 미적용**([`infra/Caddyfile`](../infra/Caddyfile) 주석에 근거) — VWorld Cesium 예외(§6) 정리 후 별도 작업. 현재 프록시가 일괄 적용하는 것은 HSTS·`X-Content-Type-Options: nosniff`·`X-Frame-Options: DENY`·`Referrer-Policy`·`Permissions-Policy` + `Server` 헤더 제거다.

## 7. 시크릿 관리

- 코드·레포에 시크릿 금지. `.env`(로컬)·시크릿 매니저(운영).
- 부팅 시 필수 시크릿 존재 검증(**Python=Pydantic Settings, 웹=Zod**), 누락 시 기동 실패.
- 노출 의심 시 즉시 회수·교체. CI에 시크릿 스캐너.
- **마스터 키 백업·이중화**: 봉투 암호화 마스터 키(KEK)는 **안전한 이중 백업** 필수 — **키 유실 = `pii_vault` 전량 복구 불능**. 시크릿 매니저 + 오프라인 봉인 백업으로 이중화.
- **백업·복구**: PostgreSQL **PITR** + S3 **버저닝**으로 원문·파생 복구, **분기별 복구 리허설**(개인정보 포함 → 접근통제·암호화 백업). 리허설 운영은 [09 §7](09-implementation-harness.md).
- **컨테이너 배포 시 시크릿(H10, [ADR-0020](adr/0020-container-deploy-3tier-vm.md))**:
  - **이미지에 굽지 않는다** — 런타임 주입만. compose `env_file`은 **레포 밖 경로**에 두고 퍼미션 `0600`, VCS 미추적.
  - 레포에는 placeholder만 있는 [`infra/env.prod.example`](../infra/env.prod.example)를 두고, 로컬 스모크용 실값 파일 `infra/env.prod`는 **`.gitignore`가 차단**한다(H10-1 — 점 없는 이름이라 기존 `.env.*` 패턴에 걸리지 않던 갭을 메움).
  - **tier 최소 배치**: `PII_MASTER_KEY`·DB 접속 URL·SMTP 자격증명은 **app tier에만** 존재한다(web tier에 두지 않음 — 퍼블릭 노출 tier의 유출 반경 축소).
  - **DB 접속 URL은 3개로 분리**(H10-2, [03 §5.1](03-database-design.md)): `DATABASE_URL`=owner(마이그레이션 전용) · `APP_DATABASE_URL`=`liviq_app`(api) · `WORKER_DATABASE_URL`=`liviq_worker`(ai-worker). 런타임 URL이 owner를 가리키면 RLS 이중 방어 2층이 죽으므로, 배포 스텝이 롤 속성을 **검증하고 아니면 중단**한다.
  - `NEXT_PUBLIC_*`은 **브라우저 번들에 노출**되므로 시크릿을 담을 수 없다(빌드타임 인라인 — [02 §9](02-directory-structure.md)). VWorld 프론트 키(§6)는 **도메인 잠금 키**라 예외.
  - CI 시크릿 스캐너는 **이미지 레이어도 대상**(빌드 산출물에 `.env`·키 파일이 섞여 들어가는 경로 차단 — 배선은 H10-3).

## 8. 감사 / 모니터링

`audit_logs`는 **append-only**다(권한으로 강제 — [03 §4.7](03-database-design.md)). 기록 대상은 아래가 단일 출처다.
행위명은 `app/audit.py`의 상수로만 쓴다(문자열 직접 타이핑 금지 — 오타가 감사 누락이 된다).

| 행위 | `action` | 상태 |
|---|---|---|
| 로그인 성공 | `auth.login` | ✅ H11-1 |
| 로그인 실패(비밀번호 불일치) | `auth.login_failed` | ✅ H11-1 |
| 가입 승인 | `user.approved` | ✅ H11-1 |
| 가입 거절 | `user.rejected` | ✅ H11-1 |
| 계정 비활성화 | `user.deactivated` | ✅ H11-1 |
| 권한변경 — 직원 초대 | `staff.invited` | ✅ H11-1 |
| 권한변경 — 소장 초대 | `manager.invited` | ✅ H11-1 |
| 명부 업로드 | `roster.uploaded` | ✅ H11-1 |
| 관리비 확정 적재 | `fees.confirmed` | ✅ H11-1 |
| 개인정보 열람 — 차량번호 복호 | `pii.plates_viewed` | ✅ H11-1 |
| 개인정보 열람 — 명부 조회 | `pii.roster_viewed` | ✅ H11-1 |
| 문서 공개범위 변경 | — | 백로그([09 §8.3](09-implementation-harness.md)) |
| 공지 발행 | — | 백로그 |
| ERP 동기화 | — | 백로그(ERP 연동 자체가 미구현) |

- **개인정보 비저장(§4.3)**: `meta`에는 **식별정보를 넣지 않는다** — 이메일·이름·연락처·차량번호·거절 사유 원문 금지. 대상은 `target_type`+`target_id`(UUID)로, 규모는 건수로만 기록한다.
- **트랜잭션 규율**: 성공 기록은 업무 변경과 **같은 트랜잭션**(업무가 롤백되면 감사도 롤백 — 거짓 기록 방지). **로그인 실패만 별도 트랜잭션**이다 — 401이 트랜잭션을 롤백시키므로 같은 트랜잭션에 쓰면 기록이 사라진다.
- **알려진 공백**: 존재하지 않는 이메일로의 로그인 실패는 기록하지 않는다 — tenant를 특정할 수 없어 RLS가 INSERT를 거부한다(fail-closed). 이 표면은 **레이트 리밋**(§2·로그인 분당 상한)이 방어한다.
- 이상 징후 알림(대량 조회·비정상 시간대·마스킹 우회 시도)은 **미구현** — 감사 행이 쌓인 뒤 룰을 정한다([09 §8.3](09-implementation-harness.md) 백로그).

## 9. 보안 점검 체크리스트 (배포 전 게이트)

- [ ] 모든 엔드포인트 역할·테넌트·소유권 인가
- [ ] RLS 정책 전 업무 테이블 적용·테스트 + **런타임 접속 롤이 owner·BYPASSRLS가 아님**(배포 스텝 검증 — [03 §5.1](03-database-design.md))
- [ ] LLM 전송 페이로드 개인정보 0건(자동 검사)
- [ ] 개인정보 저장 암호화 + 마스킹 뷰 사용
- [ ] 입력 검증(api=Pydantic · 웹=Zod) + 파라미터 쿼리
- [ ] 보안 헤더·HSTS 적용 (프록시 일괄 — §6.1). **CSP는 아직 미적용**(VWorld Cesium 예외 정리 후 도입 — §6.1) 이므로 이 항목의 통과 기준에서 제외한다
- [ ] 시크릿 하드코딩 0, 스캐너 통과
- [ ] 파일 업로드 검증·격리
- [ ] 감사 로그 누락 없음, 개인정보 비저장
- [ ] 레이트 리밋(로그인·발송·AI 질의)
- [ ] 네트워크 경계 검증(§6.1) — data·app tier 포트가 퍼블릭에서 도달 불가(외부 스캔으로 확인)
- [ ] 이미지에 시크릿 미포함(레이어 스캔) · `env_file` 퍼미션 `0600` · 레포 밖 경로
- [ ] 보안 헤더·TLS가 web tier 프록시에서 일괄 적용(앱 직접 노출 경로 0건)

> 보안 민감 변경(인증/인가/개인정보/결제연동)은 머지 전 보안 리뷰 필수. 테스트: [07 §보안](07-testing-strategy.md).
