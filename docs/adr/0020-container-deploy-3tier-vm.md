# ADR-0020: 컨테이너 배포 — 이미지 4개 · 3-tier VM · compose profiles 단일 파일

- 상태: Accepted
- 날짜: 2026-07-26
- 관련: [01 §14](../01-architecture.md) · [02](../02-directory-structure.md) · [06](../06-security-privacy.md) · [09 §4](../09-implementation-harness.md) · [ADR-0005](0005-single-llm-openai-compat.md)(LLM 엔드포인트) · [ADR-0013](0013-python-backend.md)(uv workspace) · [ADR-0011](0011-redis-server-session.md)(세션 쿠키)

## 맥락

배포 정의가 레포에 없다 — Dockerfile 0개, 배포 compose 0개. [09 §4](../09-implementation-harness.md)의
"스테이징 배포 → 스모크 → 운영"은 글만 있고 실체가 없다. 현재 컨테이너화된 것은 로컬 인프라 4종
(`infra/docker-compose.yml` — postgres·redis·minio·neo4j)뿐이고 앱 4종(`api`·`ai-worker`·`web-resident`·`web-admin`)은
네이티브 실행이다.

그 결과:

- **런타임 드리프트가 배포 시점에 드러난다.** Node·Python 런타임 버전과 의존 해상도가 개발 머신 상태에
  묶여 있고, 배포 대상에서 재현된다는 보장이 없다(고정 산출물이 없으므로 배포 = 대상 호스트에서 재빌드).
- **롤백 수단이 없다.** 되돌릴 불변 산출물(이미지 태그)이 없으므로 "직전 상태 복구"가 곧 재빌드다.
- **개인정보(절대 규칙 2)·tenant 격리(절대 규칙 3) 방어가 앱 층에만 있다.** 데이터 서비스가 퍼블릭
  인터페이스에 바인드되면 앱 인가·RLS를 네트워크에서 우회할 수 있다. 네트워크 층 경계가 필요하다.

제약:

- **모노레포**: uv workspace(루트 `pyproject.toml`, 단일 `uv.lock`) + pnpm workspace라 이미지 빌드에
  **루트 빌드 컨텍스트**가 필요하다. 앱 디렉토리만으로는 빌드 불가([ADR-0013](0013-python-backend.md)).
- **규모**: 파일럿은 단지 1~4개(첫마을 4단지 322세대), 운영 인력은 사실상 1인.

## 결정

**앱 4종을 컨테이너 이미지로 빌드해 GHCR에 게시하고, 3-tier VM(web/app/data)에
`infra/compose.prod.yml` 단일 파일 + compose profiles로 배포한다. 브라우저→api 호출은 web tier
리버스 프록시(Caddy)의 same-origin `/api` 프록시를 경유한다.** 로컬 개발 루프는 네이티브 실행을
유지하고, 배포 전 스모크만 같은 compose 파일로 1호스트에 전체 기동한다.

1. **이미지 4개, multi-stage, 런타임 non-root.**
   Python(`api`·`ai-worker`)은 uv 베이스 이미지에서 `uv sync --frozen --no-dev --package liviq-api`
   (워커는 `--package liviq-ai-worker`)로 해당 멤버+의존만 설치하고, 런타임 스테이지는 `.venv`만 복사.
   웹 2종은 Next `output: 'standalone'` 산출물만 런타임(node:20-alpine)에 복사.
2. **3-tier VM.** 퍼블릭 노출은 web tier 443 하나. app tier 인바운드는 web tier에서만, data tier
   인바운드는 app tier에서만 허용. data 서비스 포트는 **프라이빗 IP에 바인드**한다 — 로컬 dev compose의
   `"15432:5432"`(전 인터페이스 바인드)와 다르다.
3. **compose 파일 1개 + profiles(`data`/`app`/`web`).** VM마다 자기 프로필만 골라 기동한다. tier별로
   파일을 쪼개지 않는다 — 공통 env·이미지 태그가 여러 파일로 흩어져 드리프트하기 때문. 부수 이득:
   2-tier(web+app 합침)나 1호스트로 되돌리는 일이 **프로필 선택 변경**으로 끝난다.
4. **브라우저→api는 same-origin `/api` 프록시.** Caddy가 `/api/*`를 app tier의 api로 `strip_prefix`
   프록시하고, 웹 빌드는 `NEXT_PUBLIC_API_BASE_URL=/api`(상대경로). 근거 3개를 동시에 해소한다:
   ① `NEXT_PUBLIC_*`은 빌드타임 인라인이라 환경별 절대 URL을 박으면 환경마다 재빌드가 필요하다
   ② api를 프라이빗 tier에 두면 브라우저가 절대 URL로 닿을 수 없다
   ③ 환경별 CORS 허용 오리진(`WEB_ORIGINS`) 관리가 사라진다.
   전제(실측): 웹의 api 호출은 전부 클라이언트 사이드다 — 서버 컴포넌트 fetch 0건, `app/api/`
   route handler 0개라 `/api` 경로 충돌도 없다.
   - **SSE 주의**: AI 질의 응답은 `text/event-stream`이므로 프록시가 버퍼링하면 스트리밍이 깨진다.
     프록시 설정에서 버퍼링을 끈다(H10-1에서 `flush_interval -1`).
5. **마이그레이션은 api 이미지 재사용.** compose의 one-shot `migrate` 서비스가 `alembic upgrade head`를
   실행한다. Alembic 자산은 wheel 밖(`packages/db/alembic`, `packages/db/alembic.ini`)에 있으므로
   이미지에 **명시 복사**해야 한다(hatch wheel은 `src/liviq_db`만 포함). 순서는
   data tier 기동 → `migrate` → `api`·`ai-worker`.
6. **LLM은 컨테이너 밖 외부 엔드포인트.** compose에 넣지 않고 env(OpenAI-호환 base URL)로만 가리킨다
   — [ADR-0005](0005-single-llm-openai-compat.md) 유지. GPU 호스트·로컬 Ollama·vLLM 무엇이든 env 교체로 대응.

## 대안

- **로컬 개발 루프도 컨테이너 안에서(bind mount + watch)** — 환경 일치가 최대. 기각: macOS bind mount에서
  Next HMR·uvicorn `--reload` 지연, pnpm/uv 캐시 이중화, 디버거 부착 악화. 개발 속도 손실이 패리티 이득보다
  크고, 패리티는 "배포 전 prod 이미지 스모크"로 충분히 확보된다.
- **Kubernetes** — 기각: 파일럿 1~4단지 규모에 Helm·인그레스·PVC·시크릿 운영 부담이 기능 진도를 잡아먹는다.
  이미지는 그대로 재사용 가능하므로 부하가 실증되면 재검토.
- **PaaS(Cloud Run·Fly·Railway)** — 기각: Neo4j·MinIO·GPU LLM을 별도 관리형/외부로 흩어야 해서 붙일 곳이
  늘고, 프라이빗 네트워크 설계가 오히려 복잡해진다.
- **2-tier(web+app 한 VM, data만 분리)** — 보안 이득 대부분을 VM 1대 덜 쓰고 얻는다. 기각이 아니라
  **폴백**: profiles 구성이라 운영 부담이 과하면 즉시 전환.
- **compose 파일을 tier별 3개로 분할** — 기각: 결정 3의 드리프트 이유.
- **api를 별도 서브도메인(`api.도메인`)으로 직접 노출** — 기각: api 퍼블릭 노출, 환경별 재빌드, 환경별 CORS
  관리가 남는다. 세션 쿠키는 `SameSite=lax`(`apps/api/app/deps.py:138`)라 eTLD+1을 공유하면 전송되긴 하지만,
  나머지 3개 비용이 해소되지 않는다.

## 결과

- **이득**: 롤백 = 이전 이미지 sha 태그로 재기동. 런타임 드리프트 제거. 절대 규칙 3(단지 격리)의 앱·DB 층
  방어에 **네트워크 층이 세 번째 방어선**으로 붙고, 개인정보 저장소(`pii_vault`·`plate_enc`)로 가는 경로가
  app tier 경유로 좁아진다([06 §6.1](../06-security-privacy.md)). CORS·환경별 재빌드 제거.
  - 규칙 2(LLM 전송 마스킹)는 **여기서 방어되지 않는다** — 호출 직전 마스킹(fail-closed)이 여전히 유일한 방어다.
- **비용**: VM 3대의 패치·모니터링·백업. 이미지 빌드 시간(CI buildx 레이어 캐시로 완화). 로컬 인프라
  compose의 `latest` 태그 3개(`minio/minio`·`minio/mc`·`neo4j:5-community`)를 운영에서는 고정 태그로 핀해야 한다.
- **후속**: H10-1(이미지 4개 · `infra/compose.prod.yml` · `infra/Caddyfile` · 로컬 전체 스택 스모크),
  H10-2(CI 릴리스 GHCR 푸시 · VM 프로비저닝 · 배포·롤백 절차).
- **재검토 신호**: 단지 수·동시 사용자가 VM 수직 확장 한계에 닿거나 무중단 배포가 요구되면 Kubernetes 재검토.
  반대로 3대 운영 부담이 과하면 2-tier·1호스트로 축소.
