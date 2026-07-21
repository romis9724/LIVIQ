# ADR-0011: Redis 서버 세션 + httpOnly 쿠키 (JWT stateless 대신)

- 상태: Accepted
- 날짜: 2026-07-13
- 갱신: 2026-07-13 — api는 FastAPI로 전환([ADR-0013](0013-python-backend.md)), 콜백 주체=api 결정은 불변. 본문의 NestJS·BullMQ 표기는 각각 FastAPI·arq로 읽을 것.
- 갱신: 2026-07-21 — 인증 수단이 자체 이메일 인증으로 교체([ADR-0014](0014-local-email-auth.md)). 세션 모델(본 ADR)은 **불변**, 본문의 OAuth 콜백 관련 서술(맥락·결정 §1)은 무효 — 세션 확립 주체·즉시 revoke·Redis 통합은 그대로.
- 관련: [docs/06 §2](../06-security-privacy.md), [docs/09 §2](../09-implementation-harness.md), [ADR-0007](0007-readonly-tool-agent.md)

## 맥락

인증은 Google OAuth(자체 비밀번호 미보관)이고, 최초 로그인 후 세대정보 입력 → `pending`, 소장 승인 시 `active`로 전환한다. `pending`/`rejected`/`inactive` 계정은 API 접근이 **즉시 차단**돼야 한다([docs/06 §2]). 세션을 어떤 방식으로 유지할지(무상태 JWT vs 서버 세션)와 OAuth 콜백 처리 위치가 미결이었다. 규칙 4(인가는 서버에서)상 계정 상태 변화가 접근권에 지연 없이 반영돼야 한다.

## 결정

세션은 **Redis 서버 세션 + httpOnly 쿠키(세션 ID만 전달)**로 구현한다.

- OAuth 콜백은 **NestJS가 PKCE로 처리**한다. 구글 access/refresh 토큰은 **저장하지 않는다** — 신원 확인 용도로만 사용하고 세션 확립 후 폐기.
- 세션 쿠키는 httpOnly·Secure·SameSite, 짧은 TTL + 슬라이딩 갱신([docs/06 §2]).
- 계정 **상태 전환(승인→활성, 비활성화, 거절) 시 해당 사용자 세션을 즉시 revoke**한다(서버가 세션 스토어를 소유하므로 만료를 기다리지 않음).

## 대안

- **JWT stateless**: 서버 상태가 없어 수평 확장이 단순하나, 만료 전 **즉시 revoke가 불가**하다 — 소장이 계정을 비활성화해도 토큰 만료까지 접근이 열린다. "상태 전환 즉시 차단" 요구·규칙 4와 정면 충돌. revoke를 위해 blocklist를 얹으면 결국 서버 상태가 필요해져 서버 세션과 같은 인프라가 되고, 그럴 바엔 세션 모델이 더 단순. 기각.
- **구글 토큰을 세션에 저장**: Gmail 등 위임 API 호출이 필요할 때 편하나, 현재 MVP에는 위임 호출이 없다(에이전트 도구는 읽기 전용, 외부 위임 없음 — [ADR-0007]). 토큰 보관은 유출 표면·저장 책임만 늘린다. YAGNI. 기각.

## 결과

- Redis(`REDIS_URL`)가 **세션 저장 + 캐시 + BullMQ 큐**를 겸한다 — 운영 스토어 1개로 통합([docs/09 §2]).
- 상태 전환 이벤트가 세션 스토어에서 대상 사용자 세션 키를 폐기 → 다음 요청부터 차단.
- Redis 장애 시 세션 검증 실패 = **fail-closed**(로그인 화면으로). 가용성은 Redis 운영(백업·모니터링)에 종속.
- 재검토 신호: 다지역·무상태 배포가 필요하거나 세션 조회가 병목이 될 때 토큰 + blocklist 하이브리드를 재논의.
