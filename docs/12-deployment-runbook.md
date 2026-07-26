# 12. 배포 런북 (3-tier VM · 컨테이너)

> 결정: [ADR-0020](adr/0020-container-deploy-3tier-vm.md) · 토폴로지: [01 §14](01-architecture.md) ·
> 릴리스 스펙: [09 §4.3](09-implementation-harness.md) · 보안 경계: [06 §6.1·§7](06-security-privacy.md)
> 성격: **운영자가 배포·롤백 중에 읽는 절차서**다. 설계 근거는 위 문서들이 소유하고, 여기엔 순서와 명령만 둔다.

**전제 3가지**

1. **CI는 이미지만 만든다.** `release.yml`이 main push마다 4종을 GHCR에 올린다. VM에 들어가는 건 **사람**이다 — 배포 자격증명을 CI에 두지 않는다([09 §4](09-implementation-harness.md)).
2. **배포·롤백은 `IMAGE_TAG`= 커밋 sha 핀으로만 한다.** `latest`는 편의 포인터일 뿐 배포에 쓰지 않는다(같은 태그의 실체가 push마다 바뀌어 "직전으로 되돌리기"가 성립하지 않는다).
3. **DB 접속 롤이 프로세스마다 다르다**(H10-2, [03 §5.1](03-database-design.md)). env에 URL 3개가 필요하고, 틀리면 `migrate` 스텝이 배포를 **중단**시킨다.

---

## 1. VM 3대 · 인바운드 규칙

| tier | 프로필 | 실행 | 인바운드 허용 | 비고 |
|---|---|---|---|---|
| **data** | `data` | postgres · redis · minio · neo4j | **app tier 프라이빗 IP에서만** 5432·6379·9000·7687 | 퍼블릭 노출 0. `DATA_BIND`=data VM 프라이빗 IP |
| **app** | `app` | migrate(one-shot) · api · ai-worker | **web tier 프라이빗 IP에서만** 8000 | `APP_BIND`=app VM 프라이빗 IP |
| **web** | `web` | caddy · web-resident · web-admin | **0.0.0.0** 80·443 (유일한 퍼블릭 면) | 웹 2종은 호스트 포트 미퍼블리시(Caddy만 접근) |

- **SSH(22)는 세 대 모두 운영자 IP·점프호스트로 제한**한다. 아래 절차는 전부 SSH 세션에서 수행한다.
- MinIO 콘솔(9001)은 **닫는다** — 필요하면 SSH 포트 포워딩으로만 접근하고, `compose.prod.yml`의 해당 포트 줄을 제거한다.
- **LLM 엔드포인트는 컨테이너 밖**이다([ADR-0005](adr/0005-single-llm-openai-compat.md)). app tier에서 그 호스트로 나가는 **아웃바운드**가 열려 있어야 한다.
- 배포 후 [06 §9](06-security-privacy.md) "네트워크 경계 검증"을 **외부에서** 실행한다 — data·app 포트가 퍼블릭에서 도달 불가임을 스캔으로 확인(허용 규칙을 믿지 말고 결과를 본다).

각 VM 준비물: Docker Engine + compose v2, 레포 체크아웃(compose 파일·Caddyfile 때문에 필요), `/etc/liviq/env.prod`.

---

## 2. env 파일 (tier별 최소 배치)

레포의 [`infra/env.prod.example`](../infra/env.prod.example)를 복사해 채운다. **레포 밖·`0600`**:

```bash
sudo install -m 0600 -o root -g root infra/env.prod.example /etc/liviq/env.prod
sudo vi /etc/liviq/env.prod          # 값 채우기. 파일 안 ENV_FILE 도 이 절대경로로
```

tier마다 **필요한 값만** 둔다([06 §7](06-security-privacy.md) tier 최소 배치):

| tier | 반드시 있어야 하는 것 | **두지 말아야 하는 것** |
|---|---|---|
| data | `POSTGRES_*` · `MINIO_ROOT_*` · `NEO4J_PASSWORD` · `NEO4J_HEAP`/`PAGECACHE` · `DATA_BIND` | `PII_MASTER_KEY` · DB 접속 URL · SMTP |
| app | DB URL 3개 · `PII_MASTER_KEY` · `REDIS_URL` · `S3_*` · SMTP · `LLM_*`/`EMBEDDING_*` · `NEO4J_*` · `API_ENV=production` · `*_BASE_URL` | — |
| web | `CADDY_HTTP`/`HTTPS` · `*_SITE` · `*_UPSTREAM` · `IMAGE_*` | 시크릿 일체(퍼블릭 노출 tier) |

**DB 접속 URL 3개**([03 §5.1](03-database-design.md)):

```
DATABASE_URL=postgresql+asyncpg://liviq:<owner-pw>@10.0.0.20:5432/liviq          # migrate 전용(owner)
APP_DATABASE_URL=postgresql+asyncpg://liviq_app:<app-pw>@10.0.0.20:5432/liviq    # api
WORKER_DATABASE_URL=postgresql+asyncpg://liviq_worker:<worker-pw>@10.0.0.20:5432/liviq  # ai-worker
```

- 런타임 롤 비밀번호의 **단일 출처가 이 파일**이다. `migrate` 스텝이 여기서 읽어 `ALTER ROLE … LOGIN PASSWORD`로 수렴시킨다 → **값을 바꾸고 재배포하면 그게 곧 비밀번호 회전**이다.
- 런타임 URL에 owner를 적으면 `migrate`가 비영점 종료하고 api·ai-worker가 뜨지 않는다(의도된 fail-closed).
- `PII_MASTER_KEY` **유실 = `pii_vault` 복호 불능**. 시크릿 매니저 + 오프라인 봉인 백업 이중화([06 §7](06-security-privacy.md)).

---

## 3. GHCR 로그인 (세 대 모두)

GHCR 패키지는 기본 **private**이다. 각 VM에서 `read:packages` 스코프만 가진 PAT로 로그인한다:

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u <github-user> --password-stdin
```

env에 이미지 좌표를 지정한다(`<owner>`는 소문자):

```
IMAGE_PREFIX=ghcr.io/<owner>/liviq
IMAGE_TAG=<배포할 커밋 sha>
```

배포할 sha 확인:

```bash
gh run list --workflow=Release --branch main --limit 5      # 성공한 실행의 커밋
gh api /user/packages/container/liviq-api/versions --jq '.[0].metadata.container.tags'
```

---

## 4. 최초 배포 (순서 고정)

**data → migrate → app → web.** tier 간 `depends_on`은 `required: false`라 compose가 순서를 강제해 주지 않는다 — 이 순서는 **사람이 지킨다**.

```bash
# ── data VM ──
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml --profile data up -d
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml ps   # 4종 healthy 확인

# ── app VM ── (migrate 가 먼저 완료돼야 api·ai-worker가 뜬다: service_completed_successfully)
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml --profile app up -d
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml logs migrate
#   기대: "Running upgrade … → <head>" 뒤에
#         "[runtime_roles] 접속 롤 수렴·검증 완료: liviq_app, liviq_worker"
curl -fsS http://<APP_BIND>:8000/health                     # {"status":"ok"}

# ── web VM ──
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml --profile web up -d
```

**최초 SYS_ADMIN 부트스트랩**(신규 배포에서 첫 관리자를 만드는 유일한 경로). `api`가 아니라 **`migrate` 서비스로** 실행한다 — api 서비스는 `DATABASE_URL`이 런타임 롤로 오버라이드돼 있어 시드가 권한 오류로 깨진다:

```bash
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml \
  run --rm --workdir /app migrate python scripts/bootstrap_sys_admin.py --email <운영자-이메일>
```

임시 비밀번호가 stdout에 출력되고 첫 로그인 시 변경이 강제된다. 그 뒤 단지 생성 → 소장 초대는 화면에서 진행한다([06 §2](06-security-privacy.md) 계정 생성 위계).

### 배포 후 스모크 (최소)

1. `https://<resident-도메인>` · `https://<admin-도메인>` 로드 (TLS·리다이렉트 정상)
2. 로그인 → `/api/me` 200 (세션 쿠키에 `Secure` — `API_ENV=production` 전제)
3. 문서 업로드 → 색인 완료(ai-worker 동작 + LLM 엔드포인트 도달)
4. AI 질의 → **토큰이 점진 도착**(SSE 버퍼링 없음) + 인용 표시
5. 브라우저 콘솔 에러 0 · 모든 `/api` 요청 same-origin
6. [06 §9](06-security-privacy.md) 배포 전 게이트 체크리스트 통과 확인

---

## 5. 업그레이드 (무중단 아님 — 짧은 중단 수용)

```bash
# 1) 새 sha 를 env에 반영
sudo sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=<새 sha>/" /etc/liviq/env.prod

# 2) app VM: 이미지 pull → migrate 재실행 → api·ai-worker 교체
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml --profile app pull
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml --profile app up -d
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml logs migrate   # 그린 확인

# 3) web VM: 동일하게 pull → up -d
```

- **스키마 변경이 파괴적일 때**는 코드와 마이그레이션을 같은 배포에 태우지 않는다 — [03 §8](03-database-design.md) **2단계 규칙**(먼저 앞뒤 호환 변경 배포 → 다음 배포에서 제거)으로 롤백 가능성을 유지한다.
- 배포 전 **DB 백업**을 반드시 선행한다([09 §7.1](09-implementation-harness.md)).

---

## 6. VWorld 실사 3D 키 (선택 — 트윈 토글)

`NEXT_PUBLIC_VWORLD_API_KEY`는 **빌드타임 인라인 + 서비스 URL 도메인 잠금** 키다. 그래서:

1. 운영 admin 도메인을 VWorld 콘솔에 서비스 URL로 등록한다.
2. 그 키로 **web-admin 이미지만** 재빌드해 push한다(로컬 buildx 또는 `workflow_dispatch` 후 별도 빌드).
3. web VM에서 해당 이미지로 교체한다.

키를 넣지 않으면 트윈의 '실사 3D' 토글만 비활성이고 나머지 화면은 정상이다. 이 키는 도메인 잠금이라 번들 노출이 유출은 아니다([06 §7](06-security-privacy.md) 예외).

---

## 7. 롤백

**코드만 되돌린다.** 데이터·스키마는 되돌리지 않는다(마이그레이션 downgrade는 운영에서 쓰지 않는다 — 데이터 손실 위험).

```bash
# 1) 직전 성공 sha 확인
gh run list --workflow=Release --branch main --limit 10

# 2) app·web VM 각각: IMAGE_TAG 를 이전 sha 로 되돌리고 재기동
sudo sed -i "s/^IMAGE_TAG=.*/IMAGE_TAG=<이전 sha>/" /etc/liviq/env.prod
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml --profile app pull
docker compose --env-file /etc/liviq/env.prod -f infra/compose.prod.yml --profile app up -d
# web VM 동일
```

- 롤백 후에도 `migrate`는 **최신 head**를 적용한 상태로 남는다. 이전 코드가 최신 스키마에서 동작하는지가 롤백 성립 조건이고, 그것을 보장하는 장치가 §5의 **2단계 규칙**이다.
- 롤백이 실패하면(이전 코드가 새 스키마에서 못 뜨면) **앞으로 고쳐 나가는 것**이 유일한 경로다 — 백업 복구는 마지막 수단이고 그 절차는 [09 §7.1](09-implementation-harness.md).

---

## 8. 트러블슈팅 (실제로 밟은 것들)

| 증상 | 원인 | 대응 |
|---|---|---|
| `migrate`가 `exit 1`, `[runtime_roles] 실패: … 사용자가 'liviq'이다` | 런타임 URL에 owner를 적었다 | `APP_DATABASE_URL`·`WORKER_DATABASE_URL`을 `liviq_app`·`liviq_worker`로 수정 |
| api 기동 직후 `RuntimeRoleError … RLS를 우회한다` → `Application startup failed` | api가 owner로 접속 중 | 위와 동일. 의도된 fail-closed다([03 §5.1](03-database-design.md)) |
| 시드·부트스트랩 스크립트가 `permission denied` | `api` 서비스로 실행했다(런타임 롤) | `migrate` 서비스로 실행(§4) |
| `--profile app up`이 postgres를 로컬에 띄우려 한다 | tier 간 `depends_on`에 `required: false`가 빠졌다 | compose 파일 확인(H10-1에서 설정됨) |
| 데이터 서비스가 포트를 못 잡는다 | 호스트에 다른 postgres/redis가 있다 | `POSTGRES_PORT` 등 호스트 포트 env로 조정 |
| 브라우저에서 `/api` 요청이 CORS로 막힌다 | Caddy를 우회해 api를 직접 부르고 있다 | `NEXT_PUBLIC_API_BASE_URL=/api`로 빌드된 이미지인지 확인 |
| AI 응답이 한 번에 몰려 온다 | 프록시 버퍼링 | Caddy `reverse_proxy … { flush_interval -1 }` 확인([`infra/Caddyfile`](../infra/Caddyfile)) |
| 이메일 검증·초대 링크가 내부 주소로 간다 | `API_BASE_URL`·`WEB_*_BASE_URL`이 내부 값 | 퍼블릭 도메인으로 수정 후 api 재기동 |
