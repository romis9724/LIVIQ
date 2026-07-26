# 13. GitLab CI → WSL Docker 배포 (개발·검증 호스트)

> 형상: [ADR-0020](adr/0020-container-deploy-3tier-vm.md) 이미지 4종 + `infra/compose.prod.yml` 3프로필 —
> **VM 3대 대신 WSL 1호스트**에 전부 올린다. 운영 배포는 [12 런북](12-deployment-runbook.md)이 단일 출처.
> 파일: [`.gitlab-ci.yml`](../.gitlab-ci.yml) · [`infra/deploy-wsl.sh`](../infra/deploy-wsl.sh) · [`infra/compose.wsl.yml`](../infra/compose.wsl.yml)

**범위를 먼저 못박는다.** 이 경로는 **개발·검증용**이다. GHCR 게시가 없고(이미지는 그 호스트의 로컬
Docker 저장소에만 있다), TLS 종단이 없고(`API_ENV=local`), 시크릿이 호스트 파일 하나에 있다.
운영 트래픽을 받는 배포는 12 런북의 3-tier VM 절차를 그대로 쓴다.
외부 브라우저 접속(도메인 없이 포트로)은 **§9** — 평문 HTTP라 **가상 데이터 파일럿 전용**이다.

---

## 1. 왜 CI가 배포까지 하는가

12 런북 전제 1은 "CI는 이미지만 만든다"이고 근거는 **배포 자격증명을 CI에 두지 않는다**다.
이 경로에는 그 자격증명이 **존재하지 않는다**:

| 보통 필요한 것 | 이 경로 | 이유 |
|---|---|---|
| SSH 키 | 없음 | Runner(shell executor)가 **배포 대상 호스트 안에서** 돈다 |
| 레지스트리 자격증명 | 없음 | 같은 호스트의 Docker 저장소에 빌드 → pull/push 자체가 없다 |
| 배포용 서비스 계정 | 없음 | `docker` 그룹 소속 로컬 유저(`gitlab-runner`)가 전부 |

즉 전제의 **취지를 위반하지 않는다**. 대신 그 대가로 이 호스트는 "빌드 머신 = 배포 대상"이라
격리가 없다 — 그래서 범위가 개발·검증으로 제한된다.

---

## 2. 호스트 1회 준비

### 2.1 Docker + Runner

```bash
# WSL(Ubuntu) 안에서. systemd 가 켜져 있어야 서비스로 돈다 → /etc/wsl.conf 에 [boot] systemd=true
sudo usermod -aG docker gitlab-runner        # ★ 이게 없으면 모든 잡이 permission denied 로 죽는다
sudo systemctl enable --now docker gitlab-runner
```

### 2.2 Runner 등록

GitLab 프로젝트 → **Settings → CI/CD → Runners → New project runner** 에서 태그 `wsl`,`docker` 로
만들고 나온 토큰(`glrt-…`)으로 등록한다:

```bash
sudo gitlab-runner register --non-interactive \
  --url "http://<gitlab-host>:<port>/" \
  --token "glrt-..." \
  --executor shell --shell bash --name wsl-docker
```

그 다음 `/etc/gitlab-runner/config.toml` 에 **`clone_url` 을 추가한다**(§5의 두 번째 함정):

```toml
[[runners]]
  name = "wsl-docker"
  url = "http://<gitlab-host>:<port>/"
  clone_url = "http://<gitlab-host>:<port>/"   # ← GitLab external_url 이 틀려도 클론이 되게
  executor = "shell"
  shell = "bash"
  environment = ["DOCKER_BUILDKIT=1", "COMPOSE_DOCKER_CLI_BUILD=1"]
```

```bash
sudo systemctl restart gitlab-runner
sudo journalctl -u gitlab-runner -f      # "Checking for jobs..." 에 404/403 이 없어야 한다
```

### 2.3 env 파일 (시크릿 단일 출처)

레포 밖에 두고 러너만 읽게 한다([06 §7](06-security-privacy.md) VCS 미추적):

```bash
sudo install -D -m 0640 -o root -g gitlab-runner infra/env.prod.example /etc/liviq/env.prod
sudo vi /etc/liviq/env.prod
```

1호스트에서 반드시 이 값이어야 하는 것들:

| 키 | 값 | 이유 |
|---|---|---|
| `ENV_FILE` | `/etc/liviq/env.prod` | `env_file:` 주입 경로 — 파일 **안에서** 자기 절대경로를 가리켜야 한다 |
| `API_ENV` | `local` | TLS 미종단. 비-local 이면 Secure 쿠키가 붙어 HTTP 로그인이 안 된다 |
| `DATA_BIND`·`APP_BIND` | `127.0.0.1` | data·app tier 는 퍼블릭 노출 0([06 §6.1](06-security-privacy.md)) |
| `CADDY_HTTP` | `8080` | 80 은 호스트 선점이 잦다. 유일한 인바운드 면 |
| DB URL 3종 | 롤마다 다른 URL | owner=migrate 전용 · `liviq_app`=api · `liviq_worker`=ai-worker([03 §5.1](03-database-design.md)) |
| `PII_MASTER_KEY` | `openssl rand -base64 32` | **유실 = `pii_vault` 복호 불능** |
| `IMAGE_PREFIX` | `liviq-` | **끝의 대시 포함**(ADR-0021 결정 5 — 구분자가 값 안에 있다). 이 형상은 **로컬 빌드 이미지로 기동**하므로 레지스트리 경로가 아니다. 레지스트리 좌표는 게시에서만 쓰고 `$CI_REGISTRY_IMAGE`로 온다 |

`IMAGE_TAG` 는 파일에 뭘 적어도 CI가 커밋 sha 로 덮는다(compose 는 셸 env 를 `--env-file` 보다 우선).

---

## 3. 파이프라인

| 트리거 | 실행 | 비고 |
|---|---|---|
| `main` push | build → deploy → smoke → publish | 이미지 4종 빌드 후 3프로필 기동, Caddy 경유 검증, 레지스트리 게시 |
| MR | build 만 | Dockerfile·lock·compose 파손을 머지 전에 잡는다. **기동하지 않는다** |
| 수동(web·api) | 전체 + `rollback`·`prune` | 파이프라인 변수로 `ROLLBACK_TAG` 지정 |

`web`(UI 의 "Run pipeline" 버튼)과 `api`(REST 트리거)를 **둘 다** 허용한다 — 같은 의도인데 GitLab 이
진입점으로만 구분하기 때문이다. 실행 조건은 `.gitlab-ci.yml` 상단 앵커(`.on_deploy`·`.on_build`)
한 곳에서만 관리한다(잡마다 복붙하면 드리프트가 난다).

API 로 특정 브랜치를 돌리는 예 — main 을 건드리지 않고 파이프라인 전체를 검증할 때 쓴다:

```bash
curl -X POST -H "PRIVATE-TOKEN: <PAT>" \
  "http://192.168.10.153:5050/api/v4/projects/8/pipeline?ref=<branch>"
```

**이미지가 가는 곳이 두 군데이고 목적이 다르다** — 이걸 섞으면 설계가 안 읽힌다:

| | 배포 경로 | 게시 경로 |
|---|---|---|
| 무엇 | `build` 가 만든 **로컬 이미지**를 그대로 기동 | 스모크 통과 후 레지스트리로 push |
| 왜 | Runner 가 배포 대상 호스트 안에 있어 push→pull 왕복(4종 ≈1.3GB)이 순수 낭비 | 이력·백업·타 호스트 배포 경로 확보 |
| 의존 | 게시를 **기다리지 않는다** | `needs: [smoke]` — 검증된 것만 올린다 |

즉 "레지스트리에 올려야 배포가 된다"가 아니다. 배포는 로컬 이미지로 이미 끝나고, 게시는 그 뒤에
붙는 별도 목적의 단계다. 그래서 게시가 실패해도 기동 중인 배포는 영향이 없다.

- `deploy`·`rollback` 은 `resource_group: liviq-prod` 로 **동시 실행을 막는다** — 같은 compose
  프로젝트를 두 잡이 동시에 만지면 컨테이너가 반만 교체된 상태로 남는다.
- 빌드는 4종을 **한 잡에서 순차로** 한다. 4코어 호스트에서 Next 2종 병렬 빌드는 서로 자원을
  다투어 더 느리고, 같은 daemon 이라 레이어 캐시는 순차에서도 그대로 공유된다.
- 스모크 실패 시 **자동 롤백하지 않는다**. 되돌릴지는 판단이고, `rollback` 잡이 수동으로 있다.

수동으로 같은 일을 하려면(러너 없이도 동작):

```bash
sudo -u gitlab-runner -H bash -c 'cd /path/to/liviq && infra/deploy-wsl.sh all'   # build+deploy+smoke
infra/deploy-wsl.sh status      # 기동 상태 · 실제 돌고 있는 이미지 태그
infra/deploy-wsl.sh tags        # 되돌릴 수 있는 태그(4종 모두 로컬에 있는 것만)
infra/deploy-wsl.sh down        # 정지 (볼륨 보존)
```

---

## 3.1 외부에서 main 에 push 하는 시나리오

**push 하는 위치는 상관없다.** Runner 는 **폴링(pull) 방식**이라 GitLab 이 이 호스트로 들어오지
않는다 — Runner 가 GitLab 에 "일 있나요"를 주기적으로 묻는다(`check_interval = 3`). 그래서
이 PC 에 인바운드 포트를 열 필요도, 고정 IP 도, 방화벽 예외도 필요 없다. 외부 기기에서 main 에
push 하면 이 호스트의 Runner 가 그 잡을 집어 **여기 WSL Docker 에** 배포한다.

성립 조건은 딱 두 가지다:

1. **`.gitlab-ci.yml` 이 main 에 있어야 한다.** 없으면 push 해도 파이프라인이 생기지 않는다.
2. **push 시점에 WSL 이 떠 있어야 한다.** Runner 는 WSL 안의 systemd 서비스다 → WSL 이 죽어
   있으면 잡을 집을 사람이 없다. 잡은 `pending` 으로 남고, 오래 방치되면 GitLab 이 stuck 으로
   판정해 실패시킨다. (WSL 이 나중에 뜨면 그 사이의 pending 잡은 그때 집어간다.)

### WSL 이 죽는 경우와 대응

| 상황 | 결과 | 대응 |
|---|---|---|
| Windows 재부팅 | WSL 자동 시작 안 됨 → Runner 없음 | 부팅 시 WSL 을 띄우는 예약 작업 (아래) |
| `wsl --shutdown` 수동 실행 | 같음 | 다시 띄운다 |
| WSL 유휴 | **문제 없음** — systemd 로 docker·gitlab-runner 프로세스가 상주해 VM 이 유지된다 | — |

Docker·Runner 자체는 부팅 시 자동 기동으로 이미 설정돼 있다(`systemctl enable docker gitlab-runner`) —
**WSL 이 뜨기만 하면** 그 안에서 둘은 알아서 올라온다. 즉 남은 문제는 "WSL 을 누가 띄우나" 하나다.

### 이 호스트의 현재 상태 (2026-07-26 실측)

`wsl_start` 예약 작업이 **부팅 트리거로 존재하지만 비활성**이고, 활성화해도 이 시나리오에는 부족하다:

```
State      : Disabled                    ← 꺼져 있음
LogonType  : Interactive                 ← abworks 가 로그인해야만 실행됨(무인 부팅 시 안 돎)
Arguments  : -Command "start-process wsl.exe" -WindowStyle Hidden"   ← 따옴표 깨짐
```

무인 상태에서도 동작하게 하려면 **로그온 여부와 무관하게 실행**되도록 바꿔야 한다. 관리자
PowerShell 에서:

```powershell
# 로그온 없이도 부팅 시 WSL distro 를 띄운다. -e /bin/true = 부팅만 하고 셸을 남기지 않는다.
$a = New-ScheduledTaskAction -Execute 'C:\Windows\System32\wsl.exe' -Argument '-d Ubuntu -e /bin/true'
$t = New-ScheduledTaskTrigger -AtStartup
$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName 'wsl_autostart_liviq' -Action $a -Trigger $t -Principal $p -Settings $s -Force
```

> SYSTEM 계정으로 WSL 을 띄우는 방식은 Windows 빌드에 따라 동작이 다르다. 등록 후 **실제로
> 재부팅해서 확인**할 것 — `wsl -l --running` 에 Ubuntu 가 보이고
> `wsl -d Ubuntu -u root systemctl is-active gitlab-runner` 가 `active` 여야 한다.
> SYSTEM 으로 안 되면 `-UserId '<사용자>' -LogonType Password`(자격증명 저장) 로 바꾼다.

검증이 끝날 때까지는 **push 전에 이 PC 에서 WSL 이 떠 있는지 확인**하는 편이 안전하다:

```powershell
wsl -l --running
wsl -d Ubuntu -u root systemctl is-active docker gitlab-runner
```

---

## 4. 첫 배포 이후 — 로그인 계정 만들기

빈 DB 에는 로그인할 계정이 없다. 최초 SYS_ADMIN 은 이미지에 포함된 부트스트랩으로 만든다
(유일한 경로 — H7-2, [ADR-0014](adr/0014-local-email-auth.md)):

```bash
docker compose --env-file /etc/liviq/env.prod \
  -f infra/compose.prod.yml -f infra/compose.wsl.yml --profile app \
  run --rm --workdir /app api python scripts/bootstrap_sys_admin.py --email admin@example.com
```

`MAIL_BACKEND=console` 이므로 검증·초대 링크는 api 로그로 나온다:

```bash
docker compose --env-file /etc/liviq/env.prod \
  -f infra/compose.prod.yml -f infra/compose.wsl.yml --profile app logs -f api
```

### 접속

Windows 브라우저에서:

- 입주민 — <http://resident.localhost:8080>
- 관리자 — <http://admin.localhost:8080>

`*.localhost` 는 **브라우저가 내부적으로** 127.0.0.1 로 푸는 이름이라 hosts 파일 수정이 필요 없고,
WSL2 의 localhost 포워딩으로 Windows → WSL 컨테이너까지 닿는다. 반면 `curl` 은 그 이름을 모를 수
있어, 스크립트 스모크는 `-H "Host: resident.localhost"` 로 확인한다(`deploy-wsl.sh smoke`).

---

## 5. 실제로 밟은 함정 4개

이 항목들은 추측이 아니라 이 호스트를 세팅하며 로그로 확인한 것이다.

**① Runner URL 에 프로젝트 경로를 넣으면 전 잡이 404.**
`url = "http://host:port/dhkim/liviq.git"` 처럼 클론 URL 을 넣으면 runner 는 거기에
`/api/v4/jobs/request` 를 붙여 호출한다 → `Checking for jobs... failed  status=404 Not Found`.
GitLab UI 에는 러너가 **online 으로 보이는데** 잡을 하나도 집지 않는다. `url` 은 **인스턴스 루트**여야 한다.

**② config.toml 의 토큰이 UI 의 러너와 다르면 403.**
UI 에서 러너를 만들 때마다 새 토큰이 나온다. 이전 등록 시도의 토큰이 파일에 남아 있으면
`Checking for jobs... forbidden  status=403` 이 뜨고, 3회 실패 후
`Runner … is unhealthy and will be disabled for 1h0m0s` 로 **1시간 잠긴다**(재등록 후 `systemctl restart` 필요).

**③ GitLab `external_url` 에 포트가 없으면 CI 클론이 깨진다.**
API 가 `http_url_to_repo` 를 포트 없는 주소로 돌려주면(예: `http://192.168.10.153/…` 인데 실제 서비스는
`:5050`) 러너가 그 주소로 클론을 시도해 닿지 못한다. 근본 해결은 GitLab 쪽 `external_url` 수정이고,
러너 쪽에서 덮는 방법이 `clone_url`(§2.2)이다.

**④ WSL Docker CE 에는 `host.docker.internal` 이 없다.**
Docker Desktop 은 자동 주입하지만 apt 로 넣은 Docker Engine 은 하지 않는다 → LLM·임베딩 기본값
(`http://host.docker.internal:11434/v1`)이 DNS 해석에 실패한다. [`infra/compose.wsl.yml`](../infra/compose.wsl.yml)이
app tier 3종에 `host.docker.internal:host-gateway` 를 주입해 메운다. Ollama 를 **WSL 안에서** 돌린다면
그 주소가 아니므로 env 의 `LLM_BASE_URL`·`EMBEDDING_BASE_URL` 을 바꾼다.
(LLM 미가동이어도 기동·스모크는 통과한다 — 호출 시점에야 필요하다.)

---

## 6. 롤백

배포 핀은 커밋 sha 하나다([12 런북](12-deployment-runbook.md) 전제 2 — `latest` 로 배포 금지).
되돌리기 = **다른 `IMAGE_TAG` 로 다시 기동**하는 것이 전부다.

```bash
infra/deploy-wsl.sh tags                       # 이 호스트에 남은 태그 확인
IMAGE_TAG=<이전-sha> infra/deploy-wsl.sh rollback
```

GitLab 에서 할 때는 파이프라인 변수 `ROLLBACK_TAG=<이전-sha>` 를 주고 `rollback` 잡을 실행한다.

**전제: 그 태그의 이미지 4종이 이 호스트에 남아 있어야 한다.** GHCR 이 없으므로 지운 태그는
되돌릴 수 없다 — `prune` 잡을 자동으로 돌리지 않는 이유가 이것이고, `KEEP_TAGS`(기본 5)개만 보존한다.

---

## 7. 막혔을 때 보는 순서

```bash
sudo journalctl -u gitlab-runner -n 50 --no-pager     # 잡을 못 집는다 → §5 ①②
infra/deploy-wsl.sh status                            # 무엇이 안 떴나
docker compose --env-file /etc/liviq/env.prod \
  -f infra/compose.prod.yml -f infra/compose.wsl.yml --profile app logs migrate
```

- **api 가 안 뜨고 `migrate` 가 비영점 종료** → DB URL 3종을 확인한다. 런타임 URL 에 owner 를 적으면
  `migrate` 가 **의도적으로** 거부한다(RLS 이중 방어 2층의 성립 조건 — [03 §5.1](03-database-design.md)).
- **로그인이 되지 않고 쿠키가 안 붙는다** → `API_ENV` 가 `local` 인지 본다(HTTP 에 Secure 쿠키).
- **감사 로그 `ip` 가 전부 같은 IP** → `FORWARDED_ALLOW_IPS` 미설정(H11-1, [06 §8](06-security-privacy.md)).
- **`liviq-api:<tag>` pull 시도 후 실패** → 그 태그를 빌드하지 않았다. `tags` 로 확인하고 `build` 한다
  (`IMAGE_PREFIX=liviq` 는 레지스트리에 없는 로컬 이름이라 pull 이 성립할 수 없다).

---

## 8. 레지스트리 게시 — 현재 서버 설정으로는 실패한다 (미해결)

`publish` 잡은 배선이 끝나 있고 `allow_failure: true` 다. **지금 이 GitLab 에서는 push 가 안 된다.**
이유는 레포가 아니라 **GitLab 서버 설정**이다(2026-07-26 실측).

### 증상

```
Get "http://192.168.10.153:5050/v2/":
  Get "http://192.168.10.153/jwt/auth?...": dial tcp 192.168.10.153:80: connect: no route to host
```

레지스트리는 `:5050` 으로 서비스되는데, 인증 토큰 realm 은 포트 없는 주소를 알려준다:

```
Www-Authenticate: Bearer realm="http://192.168.10.153/jwt/auth"
```

그 호스트의 80·443 은 닿지 않는다(실측: `:80`·`:443` 무응답, `:5050` 만 302). §5 ③ 과 **같은 뿌리**다 —
`external_url` 에 포트가 빠져 있어 GitLab 이 자기 주소를 포트 없이 알려준다.

### 고치는 곳 (GitLab 호스트, 이 레포 아님)

```ruby
# /etc/gitlab/gitlab.rb
external_url          'http://192.168.10.153:5050'
registry_external_url 'http://192.168.10.153:5050'
```

```bash
sudo gitlab-ctl reconfigure
```

이 한 번의 수정이 **세 가지를 같이 해결한다**: ① 레지스트리 push ② CI 클론 URL(§5 ③ — 러너의
`clone_url` 오버라이드가 불필요해진다) ③ API 가 돌려주는 `web_url`·`http_url_to_repo` 정합.

서버를 못 고친다면 대안은 GitLab 호스트에서 80 → 5050 을 포워딩하는 것이다.

### 클라이언트 쪽 준비 (이미 완료)

레지스트리가 평문 HTTP 라 daemon 이 거부한다. 이 호스트에는 이미 넣었다:

```json
// /etc/docker/daemon.json
{ "insecure-registries": ["192.168.10.153:5050"] }
```

```bash
sudo systemctl restart docker   # 컨테이너는 restart: unless-stopped 로 자동 복구된다
```

### 서버가 고쳐진 뒤 할 일

1. `.gitlab-ci.yml` 의 `publish` 잡에서 **`allow_failure: true` 를 지운다** — 게시 실패는 "롤백 대상
   백업이 없다"는 뜻이므로 그때는 파이프라인이 빨개져서 눈에 보여야 한다.
2. 러너 `clone_url` 오버라이드는 남겨도 무해하지만, 정합을 위해 지워도 된다.

게시되는 이름은 GHCR 과 규약이 다르다(GitLab 은 프로젝트 경로 하위에 담는다):

| | 형태 |
|---|---|
| GHCR(`release.yml`) | `ghcr.io/<owner>/liviq-api:<sha>` — 하이픈 |
| GitLab 프로젝트 | `192.168.10.153:5050/dhkim/liviq/api:<sha>` — 서브경로 |

---

## 9. 외부에서 브라우저로 접속 (도메인 없는 파일럿)

> **★ TLS 가 없다.** 로그인 비밀번호·세션 쿠키가 평문으로 흐른다. **가상 데이터 파일럿 전용**이다
> (사용자 결정 2026-07-26). 실제 입주민 개인정보가 들어가는 시점에 도메인 + Caddy 자동 HTTPS 로
> 올린다([ADR-0021](adr/0021-gitlab-ci-single-host-wsl.md) 재검토 신호).

### 9.1 경로 (실측 2026-07-26)

```
브라우저 → 공유기 59.29.231.14:17000 → Windows 0.0.0.0:17000 (portproxy)
        → Windows 127.0.0.1:17000 (WSL 자동 중계) → WSL Caddy :17000 → web-resident:3000
```

| 사이트 | 외부 | 내부(변경 없음) |
|---|---|---|
| 입주민 | `http://59.29.231.14:17000` | Caddy `:17000` |
| 관리자 | `http://59.29.231.14:17001` | Caddy `:17001` |
| 파이프라인 스모크 | — | Caddy `:8080` + Host `*.localhost` (그대로 유지) |

### 9.2 왜 포워딩만으로는 안 됐나

Caddy 는 사이트를 **Host 헤더**로 가른다(`resident.localhost` / `admin.localhost`). IP:포트로 들어오면
Host 가 `59.29.231.14:17000` 이라 매칭되는 사이트가 없어 **응답하지 않는다** — 공유기가 TCP 핸드셰이크를
완료하므로 포트는 열린 것처럼 보이고 HTTP 만 0바이트로 끊긴다(이 증상으로 진단했다).

해법은 **포트 기반 사이트 주소**를 하나 더 붙이는 것이다. `:17000` 은 포트만 맞으면 Host 와 무관하게
매칭된다. [`infra/Caddyfile`](../infra/Caddyfile) 의 `{$RESIDENT_ALT_SITE:}`(기본 빈 값)가 그 자리이고,
값은 [`infra/compose.wsl.yml`](../infra/compose.wsl.yml) 오버레이가 넣는다 — 3-tier 운영은 이 오버레이를
쓰지 않으므로 주소가 하나로 남는다(형상 오염 없음).

### 9.3 Windows portproxy (관리자 PowerShell, 1회)

`networkingMode=mirrored` 는 Windows 11 22H2 / Server 2025 이상만 지원한다. 이 호스트는
**Windows 10 22H2**(10.0.19045)라 쓸 수 없어 portproxy 로 간다.

```powershell
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=17000 connectaddress=127.0.0.1 connectport=17000
netsh interface portproxy add v4tov4 listenaddress=0.0.0.0 listenport=17001 connectaddress=127.0.0.1 connectport=17001
New-NetFirewallRule -DisplayName "LIVIQ resident 17000" -Direction Inbound -Protocol TCP -LocalPort 17000 -Action Allow
New-NetFirewallRule -DisplayName "LIVIQ admin 17001"    -Direction Inbound -Protocol TCP -LocalPort 17001 -Action Allow
netsh interface portproxy show all
```

**`connectaddress` 가 `127.0.0.1` 인 것이 요점이다.** WSL 이 publish 한 포트는 Windows 루프백으로
자동 중계되므로, 재부팅마다 바뀌는 WSL eth0 IP(예: `172.17.40.17`)를 쫓아다닐 필요가 없다 —
부팅마다 portproxy 를 다시 만드는 스크립트가 불필요해진다. WSL IP 를 직접 적으면 그 스크립트가 필요하다.

제거는 `netsh interface portproxy delete v4tov4 listenaddress=0.0.0.0 listenport=17000`.

### 9.4 확인

```bash
# WSL 안 (Caddy 가 실제로 그 포트를 듣는지)
ss -tlnp | grep -E ':17000|:17001'
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:17000/       # 200
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:17000/api/health   # 200

# 외부에서
curl -sS -o /dev/null -w '%{http_code}\n' http://59.29.231.14:17000/
```

`ss` 에 포트가 보이는데 외부에서 안 되면 portproxy·방화벽(§9.3), 포트가 안 보이면 배포·오버레이
(`-f infra/compose.wsl.yml` 를 빠뜨렸는지) 쪽이다.
