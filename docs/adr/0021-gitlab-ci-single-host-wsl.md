# ADR-0021: 사내 단일 호스트 배포 — GitLab CI + WSL Docker (ADR-0020 형상에 추가)

- 상태: Accepted
- 날짜: 2026-07-26
- 관련: [ADR-0020](0020-container-deploy-3tier-vm.md)(3-tier VM 형상 — 유지) · [docs/09 §4.4](../09-implementation-harness.md) · [docs/12 §9](../12-deployment-runbook.md) · [docs/03 §5.1](../03-database-design.md)

## 맥락

[ADR-0020](0020-container-deploy-3tier-vm.md)은 배포 대상을 **3-tier VM + GHCR + GitHub Actions** 하나로 정했다. 그런데 실제 파일럿을 올릴 곳이 하나 더 생겼다 — **사내 Windows Server(192.168.10.140)의 WSL2 안 Docker**이고, 코드는 사내 **GitLab**(`dhkim/liviq`)에서 파이프라인을 돈다.

제약이 3-tier VM 형상과 다르다.

- **네트워크 방향**: GitLab은 사내망(`192.168.10.153`), 대상 호스트도 사내 사설 IP다. CI에서 대상 호스트로 **밀어넣으려면** 인바운드(SSH·방화벽)를 열어야 하고, WSL2는 NAT 뒤라 포트포워딩까지 얹힌다.
- **호스트가 1대**: tier를 나눌 물리 경계가 없다. 3-tier의 "web만 퍼블릭" 방어선은 이 형상에서 성립하지 않는다.
- **레지스트리 이름 규칙이 다르다**: GHCR은 `ghcr.io/<owner>/liviq-api`(대시)로 임의 이름을 쓸 수 있지만, GitLab Container Registry는 `<registry>/<namespace>/<project>[/<repo>]` — 하위 저장소를 **슬래시**로만 표현한다. `dhkim/liviq-api`는 그런 프로젝트가 없어 push가 거부된다.
- **소유 관계**: GitHub이 정본이고 GitLab은 배포용 복제다(사용자 결정 2026-07-26). 개발·PR·리뷰·Actions 게이트는 GitHub에 남는다.

## 결정

**ADR-0020의 형상을 유지하면서, 두 번째 배포 형상을 추가한다: 사내 단일 호스트(Windows Server + WSL2 Docker)에 GitLab CI가 배포하고, 이미지는 GitLab Container Registry에 커밋 sha로 핀한다. 러너를 대상 호스트의 WSL 안에 두어 인바운드 개방을 0으로 만든다.**

1. **러너는 대상 호스트 WSL 안에 있다.** `shell` executor. 러너가 GitLab으로 **아웃바운드 폴링**만 하므로 대상 호스트에 인바운드를 열지 않는다. SSH 배포·포트포워딩·방화벽 예외가 전부 사라진다. 배포 잡의 명령은 그 호스트의 **로컬 명령**이다.
   - 부수 결론: **자격증명이 CI로 나가지 않는다.** ADR-0020이 "VM에 들어가는 건 사람"이라고 정한 이유(배포 키를 CI에 두지 않기)가 여기서는 다른 방식으로 충족된다 — 러너가 이미 안에 있으므로 내보낼 키가 없다.
2. **compose 파일·env 계약을 재사용한다.** 단일 호스트 = `--profile data --profile app --profile web` **동시 기동**이고, 이는 [H10-1](../09-implementation-harness.md)에서 이미 검증한 "1호스트 3프로필" 스모크 형상과 **같은 것**이다. 새 compose 파일을 만들지 않는다.
   - 대신 3-tier의 네트워크 방어선(§ADR-0020 결정 2)은 **이 형상에서 성립하지 않는다** — 같은 호스트이므로 `DATA_BIND`·`APP_BIND`는 `127.0.0.1`이고, 퍼블릭 노출면은 Caddy 하나로 유지한다. 절대 규칙 3의 방어는 앱 필터 + DB RLS 2층([03 §5.1](../03-database-design.md))에 의존한다.
3. **빌드·배포를 같은 러너가 한다.** 호스트에 docker가 있으므로 dind(privileged)가 불필요하다. 대가는 빌드가 배포 호스트 자원을 먹는 것 — 파일럿 1호스트에서는 수용한다. 분리 신호는 "빌드 중 서비스 지연 관측".
4. **레지스트리는 GitLab Container Registry, 태그는 `$CI_COMMIT_SHA` 핀.** `latest`는 편의 포인터로만 두고 배포·롤백에 쓰지 않는다 — ADR-0020과 같은 원칙(같은 태그의 실체가 push마다 바뀌면 "직전으로 되돌리기"가 성립하지 않는다).
5. **이미지 좌표 규약 변경: `IMAGE_PREFIX`가 구분자까지 포함한다.** compose를 `${IMAGE_PREFIX:-liviq-}api` 형태로 바꾼다.
   | 대상 | `IMAGE_PREFIX` | 결과 |
   |---|---|---|
   | 로컬 빌드 | (기본값) | `liviq-api` |
   | GHCR(3-tier VM) | `ghcr.io/<owner>/liviq-` | `ghcr.io/<owner>/liviq-api` |
   | GitLab(사내 호스트) | `<registry>/dhkim/liviq/` | `<registry>/dhkim/liviq/api` |
   대시를 compose에 하드코딩하면 GitLab 경로를 표현할 수 없다. 구분자를 env로 밀어내면 두 레지스트리를 한 파일이 지원한다.
6. **DB 접속 롤·마이그레이션·프록시는 불변.** H10-2의 3-URL 접속 롤 계약, `migrate` 2단계(`alembic upgrade head` → `python -m liviq_db.runtime_roles`), Caddy same-origin `/api`·SSE `flush_interval -1`이 그대로 적용된다. 형상이 달라도 이 계약들은 compose·이미지에 들어 있다.
7. **GitHub Actions(`release.yml`)는 유지한다.** 두 파이프라인이 각자의 레지스트리에 게시한다 — GitHub=GHCR(3-tier VM용), GitLab=GitLab 레지스트리(사내 호스트용). 같은 커밋에서 나온 이미지이므로 내용은 동일하고, 좌표만 다르다.

## 대안

- **CI에서 SSH로 배포(러너는 GitLab 쪽)**: 대상 호스트 인바운드 22 개방 + WSL 안 sshd 상주 + Windows `netsh portproxy` + 방화벽 예외가 필요하고, WSL2 IP가 재시작마다 바뀌어 포워딩이 깨진다. 배포 키를 CI 변수로 내보내야 한다. **러너를 안에 두면 이 전부가 사라진다** — 채택하지 않았다.
- **레지스트리 없이 대상 호스트에서 직접 빌드·기동**: 부품이 가장 적지만 **롤백 대상 이미지가 남지 않는다**(git 재빌드로만 복구). H10-3에서 롤백을 "IMAGE_TAG를 이전 sha로" 1회 실연해 그 값을 확인했으므로 포기하지 않는다.
- **컨테이너별 레포 분리**: 빌드 컨텍스트가 레포 루트(단일 `uv.lock`·pnpm workspace)라 성립하지 않고, `packages/api-types` 드리프트 게이트와 "같은 sha의 이미지 4개" 배포 단위가 깨진다.
- **브랜치별 컴포넌트 분할**: 브랜치는 시간축을 표현하는 도구다. 전체 시스템을 한 시점에 볼 수 없게 된다.
- **GitLab으로 완전 이전**: ADR·PR 히스토리·Actions 게이트 이전 비용에 비해 지금 얻는 것이 없다(사용자 결정 — GitHub 정본 유지).
- **`docker-windows` executor / Windows 컨테이너**: 러너가 WSL 안이라 `os=linux`이고, 이미지도 리눅스다. 실제로 등록 중 이 executor를 골랐다가 `servercore:1809` 프롬프트에서 형상 불일치가 드러났다.
- **멀티아치 이미지**: 러너·대상 모두 amd64다. QEMU 크로스 빌드로 CI 시간만 늘어난다 — arm64 호스트가 실제로 생기면 재검토([docs/12 §1](../12-deployment-runbook.md)).

## 결과

- **이득**: 사내망 배포가 **인바운드 개방 0**으로 성립한다. 파일럿을 실호스트에서 돌려 볼 수 있고, 롤백은 3-tier와 같은 조작(`IMAGE_TAG` 교체)이다. compose·env·이미지가 공용이라 두 형상의 동작 차이가 최소화된다.
- **비용**:
  - 배포 형상이 **둘**이 되어 문서·env 파일이 두 벌이다(런북에 형상별 절 분리).
  - **3-tier의 네트워크 방어선이 없다** — 단일 호스트라 tier 격리가 성립하지 않는다. 이 형상은 사내망 파일럿·스테이징 용도로만 쓰고, 외부 공개 운영은 ADR-0020 형상으로 간다.
  - **WSL 운영 부담**: 부팅 시 자동 시작이 기본이 아니고, WSL2 IP가 재시작마다 바뀌며, DB 볼륨을 `/mnt/c`에 두면 성능이 무너진다([docs/12 §9](../12-deployment-runbook.md)).
  - 빌드가 배포 호스트 자원을 점유한다.
  - `IMAGE_PREFIX` 의미 변경은 **기존 env 파일을 깨는 변경**이다(`liviq` → `liviq-`). `env.prod.example`·런북·H10-3 기록을 함께 고친다.
- **재검토 신호**:
  - 사내 호스트가 2대 이상이 되거나 외부 공개가 필요해지면 → ADR-0020의 3-tier로 승격(프로필 선택 변경으로 끝난다).
  - 빌드 중 서비스 지연이 관측되면 → 빌드 러너를 별 호스트로 분리.
  - GitLab을 정본으로 옮기기로 하면 → `release.yml` 폐기 + 게이트 이식(별도 ADR).
  - arm64 호스트가 생기면 → 멀티아치 빌드 도입.
