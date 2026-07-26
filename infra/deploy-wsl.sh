#!/usr/bin/env bash
# LIVIQ WSL 1호스트 배포 스크립트 — GitLab CI(.gitlab-ci.yml)와 수동 운영의 **공용 진입점**.
#
#   infra/deploy-wsl.sh build     # 이미지 4종 빌드 (IMAGE_TAG 로 태깅)
#   infra/deploy-wsl.sh deploy    # 3프로필 기동 + 헬시 대기
#   infra/deploy-wsl.sh smoke     # Caddy 경유 실제 응답 확인
#   infra/deploy-wsl.sh publish   # 검증된 이미지를 GitLab Container Registry 로 push
#   infra/deploy-wsl.sh status    # 현재 기동 상태 · 배포된 태그
#   infra/deploy-wsl.sh tags      # 로컬에 남은 배포 가능(=롤백 가능) 태그
#   infra/deploy-wsl.sh rollback  # IMAGE_TAG=<이전 sha> 로 재기동
#   infra/deploy-wsl.sh down      # 정지(볼륨 보존)
#   infra/deploy-wsl.sh prune     # 오래된 이미지 정리(최근 KEEP_TAGS 개 보존)
#
# 왜 CI가 배포까지 하는가 — docs/12 런북 전제 1("CI는 이미지만 만든다")의 **범위 예외**다.
# 그 전제의 근거는 "배포 자격증명을 CI에 두지 않는다"인데, 이 경로에는 **자격증명이 아예 없다**:
# GitLab Runner(shell executor)가 배포 대상 호스트 그 자체에서 돌기 때문에 SSH 키도,
# 레지스트리 자격증명도 필요하지 않다. 이미지는 로컬 Docker 이미지 저장소에 그대로 남는다
# (GHCR push 없음 — 그래서 이 경로는 개발·검증 호스트 전용이고, 운영 VM 은 docs/12 를 따른다).
#
# 시크릿은 이 레포에 없다. 값은 전부 $ENV_FILE(기본 /etc/liviq/env.prod, 0640 root:gitlab-runner)에서
# 온다 — docs/06 §7 VCS 미추적 규약. 이 스크립트는 그 파일을 **읽기만** 한다.

set -euo pipefail

# ── 경로·기본값 ──────────────────────────────────────────────────
# 레포 루트로 이동한다. compose 의 build context 가 레포 루트이고(uv/pnpm workspace 단일 lock),
# Caddyfile 볼륨 경로(./Caddyfile)는 compose 파일 기준 상대경로라 infra/ 로 해석된다.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ENV_FILE="${ENV_FILE:-/etc/liviq/env.prod}"
KEEP_TAGS="${KEEP_TAGS:-5}"
# 헬시 대기 상한. 첫 배포는 이미지 pull(data tier 5종) + alembic 마이그레이션이 겹쳐 오래 걸린다.
WAIT_TIMEOUT="${WAIT_TIMEOUT:-300}"

log()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ -r "$ENV_FILE" ] || die "env 파일을 읽을 수 없다: $ENV_FILE
  준비: sudo install -m 0640 -o root -g gitlab-runner infra/env.prod.example $ENV_FILE
        sudo vi $ENV_FILE   # 값 채우기 + 파일 안 ENV_FILE 도 이 절대경로로"

# env 파일에서 한 키만 읽는다(주석·빈 줄 무시, 값에 '=' 포함 허용).
# 이 스크립트는 env 파일을 source 하지 않는다 — 시크릿 전량을 셸 환경에 올려
# 자식 프로세스·CI 로그로 새게 하지 않으려는 것이다. 필요한 비민감 키만 집어 온다.
envget() {
  local key="$1" default="${2:-}" val
  val="$(sed -n "s/^[[:space:]]*${key}=//p" "$ENV_FILE" | head -1 | tr -d '\r' | sed 's/[[:space:]]*$//')"
  printf '%s' "${val:-$default}"
}

# IMAGE_TAG 는 배포·롤백의 유일한 핀이다(docs/12 전제 2 — `latest` 금지).
# CI 는 커밋 sha 를 넘긴다. 수동 실행이면 현재 체크아웃의 sha 로 떨어진다.
IMAGE_TAG="${IMAGE_TAG:-$(git rev-parse --short=8 HEAD 2>/dev/null || echo local)}"
# IMAGE_PREFIX 는 **구분자까지 포함**한다(ADR-0021 결정 5) — `liviq-` 의 대시가 값 안에 있다.
# compose.prod.yml 이 `${IMAGE_PREFIX:-liviq-}api` 로 참조하므로 이 스크립트도 같은 규약을 써야
# 한다(대시를 여기서 붙이면 compose 는 `liviqapi` 를 찾아 pull 실패로 떨어진다 — 정합 시 실제로
# 어긋났던 지점이다). GitLab 레지스트리 좌표는 슬래시로 끝난다: `<registry>/dhkim/liviq/`.
#
# 이 호스트에서는 **로컬 이미지 이름**(`liviq-`)을 쓴다 — 기동이 로컬 빌드 산출물로 이뤄지기
# 때문이다. 레지스트리 좌표는 게시(publish)에서만 필요하고 CI_REGISTRY_IMAGE 로 따로 온다.
IMAGE_PREFIX="${IMAGE_PREFIX:-$(envget IMAGE_PREFIX liviq-)}"
CADDY_HTTP="$(envget CADDY_HTTP 8080)"
RESIDENT_HOST="$(envget RESIDENT_SITE http://resident.localhost | sed -E 's#^https?://##')"
ADMIN_HOST="$(envget ADMIN_SITE http://admin.localhost | sed -E 's#^https?://##')"

# compose 는 셸 환경변수를 --env-file 보다 **우선**한다 → IMAGE_TAG 오버라이드가 이렇게 성립한다.
export IMAGE_TAG IMAGE_PREFIX

COMPOSE_ARGS=(
  --env-file "$ENV_FILE"
  -f infra/compose.prod.yml
  -f infra/compose.wsl.yml
  --profile data --profile app --profile web
)
dc() { docker compose "${COMPOSE_ARGS[@]}" "$@"; }

# ── 이미지 4종 ───────────────────────────────────────────────────
# 이름·컨텍스트 규약은 .github/workflows/release.yml 과 동일하게 유지한다(형상 드리프트 방지).
# NEXT_PUBLIC_* 는 **빌드타임 인라인**이라 런타임 env 로 못 바꾼다 → build arg 로만 주입.
# Python 이미지에는 그 ARG 가 없어 넘기면 "unused build arg" 경고만 쌓이므로 넘기지 않는다.
build_images() {
  local vworld
  vworld="$(envget NEXT_PUBLIC_VWORLD_API_KEY '')"
  # 예시 파일의 placeholder 가 그대로면 빈 값으로 굽는다 — 트윈 '실사 3D' 토글만 비활성된다.
  [ "$vworld" = "REPLACE_WITH_VWORLD_KEY" ] && vworld=""
  local api_base
  api_base="$(envget NEXT_PUBLIC_API_BASE_URL /api)"

  log "이미지 빌드 — ${IMAGE_PREFIX}*:${IMAGE_TAG}"
  local name df
  for name in api ai-worker web-resident web-admin; do
    df="apps/${name}/Dockerfile"
    [ -f "$df" ] || die "Dockerfile 없음: $df"
    local args=()
    case "$name" in
      web-resident) args=(--build-arg "NEXT_PUBLIC_API_BASE_URL=${api_base}") ;;
      web-admin)    args=(--build-arg "NEXT_PUBLIC_API_BASE_URL=${api_base}"
                          --build-arg "NEXT_PUBLIC_VWORLD_API_KEY=${vworld}") ;;
    esac
    log "  build ${name}"
    # 컨텍스트는 레포 루트(.) — 앱 디렉토리 컨텍스트로는 workspace lock 해석이 안 된다.
    DOCKER_BUILDKIT=1 docker build \
      -f "$df" \
      -t "${IMAGE_PREFIX}${name}:${IMAGE_TAG}" \
      "${args[@]}" \
      .
  done
  ok "이미지 4종 빌드 완료 (:${IMAGE_TAG})"
}

# ── 기동 ─────────────────────────────────────────────────────────
deploy() {
  # 배포할 태그의 이미지가 로컬에 다 있는지 먼저 확인한다. 없으면 compose 가 레지스트리 pull 을
  # 시도하고( `liviq-api` 는 Docker Hub 의 저장소로 해석된다) 엉뚱한 실패가 난다.
  local name missing=()
  for name in api ai-worker web-resident web-admin; do
    docker image inspect "${IMAGE_PREFIX}${name}:${IMAGE_TAG}" >/dev/null 2>&1 \
      || missing+=("${IMAGE_PREFIX}${name}:${IMAGE_TAG}")
  done
  if [ ${#missing[@]} -gt 0 ]; then
    die "로컬에 없는 이미지: ${missing[*]}
  먼저 build 하거나(infra/deploy-wsl.sh build), tags 로 배포 가능한 태그를 확인할 것."
  fi

  log "기동 — 3프로필(data·app·web) / IMAGE_TAG=${IMAGE_TAG}"
  # --remove-orphans: 이전 배포에서 사라진 서비스 컨테이너를 남기지 않는다.
  # --wait 는 쓰지 않는다 — migrate·minio-init 은 정상 종료하는 one-shot 인데
  #   compose 가 이를 '중단됨'으로 보고 실패로 만드는 경우가 있어, 아래에서 직접 기다린다.
  dc up -d --remove-orphans

  log "헬시 대기 (최대 ${WAIT_TIMEOUT}s)"
  local deadline=$(( SECONDS + WAIT_TIMEOUT )) state
  while :; do
    # api 가 healthy 면 그 앞의 게이트(postgres healthy → migrate 성공 종료)가 전부 통과했다는 뜻이다.
    state="$(docker inspect -f '{{.State.Health.Status}}' liviq-prod-api-1 2>/dev/null || echo missing)"
    [ "$state" = "healthy" ] && break
    if [ $SECONDS -ge $deadline ]; then
      printf '\n'
      log "api 상태=${state} — 진단 로그"
      dc ps || true
      echo "── migrate ──";   dc logs --tail 40 migrate   2>&1 || true
      echo "── api ──";       dc logs --tail 40 api       2>&1 || true
      die "제한 시간 내 api 가 healthy 가 되지 않았다"
    fi
    printf '.'
    sleep 4
  done
  printf '\n'
  ok "api healthy"
  dc ps
}

# ── 스모크 ───────────────────────────────────────────────────────
# Host 헤더를 명시한다: Caddy 는 사이트 주소(RESIDENT_SITE/ADMIN_SITE)로 라우팅하는데,
# *.localhost 는 브라우저가 내부적으로 127.0.0.1 로 푸는 이름이라 curl·DNS 에는 없을 수 있다.
# 헤더로 주면 이름 해석과 무관하게 라우팅이 검증된다.
smoke() {
  local fails=0
  check() { # check <설명> <Host> <경로> <기대 코드들>
    local desc="$1" host="$2" path="$3" want="$4" code
    code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
              -H "Host: ${host}" "http://127.0.0.1:${CADDY_HTTP}${path}" 2>/dev/null || echo 000)"
    if grep -qw "$code" <<<"$want"; then
      ok "${desc} → ${code}"
    else
      printf '\033[1;31m✗ %s → %s (기대: %s)\033[0m\n' "$desc" "$code" "$want" >&2
      fails=$(( fails + 1 ))
    fi
  }

  log "스모크 — Caddy(:${CADDY_HTTP}) 경유"
  # /api/* 는 handle_path 로 prefix 를 벗겨 api:8000 으로 간다 → api 의 실제 /health.
  check "api /health (resident 경유)" "$RESIDENT_HOST" "/api/health" "200"
  # Next 앱 루트. 미인증이면 로그인으로 보내는 리다이렉트(307/308)도 정상 응답이다.
  check "web-resident /"              "$RESIDENT_HOST" "/"            "200 307 308"
  check "web-admin /"                 "$ADMIN_HOST"    "/"            "200 307 308"
  # 보안 헤더가 프록시에서 실제로 붙는지 1건 확인(docs/06 §6 헤더 세트).
  if curl -sSI --max-time 20 -H "Host: ${RESIDENT_HOST}" \
       "http://127.0.0.1:${CADDY_HTTP}/" 2>/dev/null | grep -qi '^x-frame-options: *DENY'; then
    ok "보안 헤더 X-Frame-Options: DENY"
  else
    printf '\033[1;31m✗ 보안 헤더 X-Frame-Options 누락\033[0m\n' >&2
    fails=$(( fails + 1 ))
  fi

  [ "$fails" -eq 0 ] || die "스모크 ${fails}건 실패"
  ok "스모크 전건 통과 (IMAGE_TAG=${IMAGE_TAG})"
}

# ── 레지스트리 게시 ─────────────────────────────────────────────
# **배포 경로가 아니다.** 기동은 로컬 이미지로 하고(같은 호스트에서 빌드했으므로 pull 이 낭비),
# 이 단계는 이력·백업·타 호스트 배포 경로를 남기기 위한 것이다. 그래서 파이프라인에서
# 스모크 **뒤에** 돈다 — 레지스트리에는 실제로 검증을 통과한 이미지만 올라간다.
#
# 이름 규약이 GHCR 과 다르다:
#   GHCR(release.yml) : ghcr.io/<owner>/liviq-api:<sha>        ← 하이픈
#   GitLab 프로젝트    : <host>/<group>/<project>/api:<sha>     ← 서브경로
# GitLab 은 프로젝트 경로 하위에 이미지를 담으므로 후자가 자연스러운 형태다.
#
# 전제: 이 레지스트리는 평문 HTTP(:5050)라 daemon 이 거부한다 → 호스트에 1회 설정이 필요하다.
#   /etc/docker/daemon.json : {"insecure-registries": ["<host>:5050"]} + systemctl restart docker
# 자격증명은 CI가 자동 주입한다(CI_REGISTRY_USER / CI_REGISTRY_PASSWORD = 잡 토큰).
# **login 을 이 함수가 직접 한다** — 프리플라이트보다 login 이 먼저 일어나면 docker 의 중첩
# 에러가 먼저 터져서 진단이 가려진다(실측). 순서는 프리플라이트 → login → push → logout 이다.
# 토큰은 인자가 아니라 env 로만 받는다(ps 노출 회피). 끝나면 ~/.docker/config.json 을 비운다
# (shell executor 는 홈이 잡 사이에 유지된다).
publish() {
  local target="${REGISTRY_IMAGE:-${CI_REGISTRY_IMAGE:-}}"
  [ -n "$target" ] || die "REGISTRY_IMAGE(또는 CI_REGISTRY_IMAGE) 필요 — 예: 192.168.10.153:5050/dhkim/liviq"

  # ── 프리플라이트: 토큰 realm 이 닿는지 먼저 본다 ────────────────
  # 이걸 안 하면 docker 가 중첩된 메시지로 실패해 원인이 가려진다(실측):
  #   Get "http://<host>:5050/v2/": Get "http://<host>/jwt/auth?...": dial tcp <host>:80: no route to host
  # 진짜 원인은 **GitLab external_url 에 포트가 없어서** 레지스트리가 realm 을 80 으로 알려주는 것이다.
  # 레포에서 고칠 수 없는 서버 설정이므로, 여기서 정확히 지목하고 멈춘다.
  local reg="${CI_REGISTRY:-${target%%/*}}" realm
  realm="$(curl -sS -i --max-time 8 "http://${reg}/v2/" 2>/dev/null \
            | sed -n 's/.*realm="\([^"]*\)".*/\1/p' | head -1)"
  if [ -n "$realm" ]; then
    local realm_host="${realm#http://}"; realm_host="${realm_host#https://}"; realm_host="${realm_host%%/*}"
    if ! curl -sS -o /dev/null --max-time 8 "${realm}" 2>/dev/null; then
      die "레지스트리 인증 realm 에 닿지 못한다: ${realm}
  레지스트리는 ${reg} 로 서비스되는데 토큰 realm 은 ${realm_host} 를 가리킨다.
  원인: GitLab 의 external_url 에 포트가 빠져 있다(§5 ③ 과 같은 뿌리).
  GitLab 호스트에서 고친다 — /etc/gitlab/gitlab.rb :
      external_url          'http://${reg}'
      registry_external_url 'http://${reg}'
    적용: sudo gitlab-ctl reconfigure
  이 수정은 CI 클론 URL 문제도 같이 해결한다(그때는 러너의 clone_url 오버라이드가 불필요해진다).
  배포 자체는 로컬 이미지로 이미 끝나 있다 — 이 실패는 '게시(백업)'만 못 한 것이다."
    fi
  fi

  # ── 로그인 ──────────────────────────────────────────────────────
  if [ -n "${CI_REGISTRY_PASSWORD:-}" ]; then
    trap 'docker logout "$reg" >/dev/null 2>&1 || true' RETURN
    printf '%s' "$CI_REGISTRY_PASSWORD" \
      | docker login "$reg" -u "${CI_REGISTRY_USER:?CI_REGISTRY_USER 필요}" --password-stdin \
      || die "레지스트리 로그인 실패: $reg"
  else
    log "CI_REGISTRY_PASSWORD 없음 — 이미 로그인된 상태를 전제한다"
  fi

  log "게시 — ${target}/*:${IMAGE_TAG}"
  local name src
  for name in api ai-worker web-resident web-admin; do
    src="${IMAGE_PREFIX}${name}:${IMAGE_TAG}"
    docker image inspect "$src" >/dev/null 2>&1 || die "로컬에 없는 이미지: $src (먼저 build)"
    docker tag  "$src" "${target}/${name}:${IMAGE_TAG}"
    docker push "${target}/${name}:${IMAGE_TAG}"
    # latest 는 **편의 포인터일 뿐 배포에 쓰지 않는다**(docs/12 전제 2 — 같은 태그의 실체가
    # push 마다 바뀌어 "직전으로 되돌리기"가 성립하지 않는다).
    docker tag  "$src" "${target}/${name}:latest"
    docker push "${target}/${name}:latest"
  done
  ok "게시 완료 — 4종 × (${IMAGE_TAG}, latest)"
}

status() {
  log "IMAGE_TAG=${IMAGE_TAG} / ENV_FILE=${ENV_FILE}"
  dc ps
  log "실제 기동 중인 이미지"
  docker ps --filter 'label=com.docker.compose.project=liviq-prod' \
            --format '  {{.Names}}\t{{.Image}}\t{{.Status}}'
}

# 로컬에 이미지가 남아 있는 태그 = 지금 당장 되돌릴 수 있는 지점.
tags() {
  log "배포 가능한 태그 (4종 모두 존재하는 것만)"
  local tag n cnt
  # api 이미지의 태그를 기준으로 후보를 뽑고, 나머지 3종이 다 있는지 확인한다.
  docker images --format '{{.Tag}}\t{{.CreatedAt}}' "${IMAGE_PREFIX}api" \
    | sort -k2 -r | while IFS=$'\t' read -r tag created; do
        cnt=0
        for n in api ai-worker web-resident web-admin; do
          docker image inspect "${IMAGE_PREFIX}${n}:${tag}" >/dev/null 2>&1 && cnt=$(( cnt + 1 ))
        done
        [ "$cnt" -eq 4 ] && printf '  %-12s %s\n' "$tag" "$created"
      done
}

# 최근 KEEP_TAGS 개를 뺀 나머지 태그의 이미지를 지운다.
# **기동 중인 태그는 지우지 않는다** — docker 가 사용 중 이미지를 거부하지만, 명시적으로도 건너뛴다.
prune() {
  local running keep_list tag n
  running="$(docker ps --filter 'label=com.docker.compose.project=liviq-prod' \
               --format '{{.Image}}' | sed -E 's/.*://' | sort -u)"
  keep_list="$(docker images --format '{{.Tag}}\t{{.CreatedAt}}' "${IMAGE_PREFIX}api" \
                 | sort -k2 -r | head -n "$KEEP_TAGS" | cut -f1)"
  log "보존: 최근 ${KEEP_TAGS}개 + 기동 중"
  docker images --format '{{.Tag}}' "${IMAGE_PREFIX}api" | sort -u | while read -r tag; do
    [ -n "$tag" ] && [ "$tag" != "<none>" ] || continue
    grep -qx "$tag" <<<"$keep_list" && continue
    grep -qx "$tag" <<<"$running"   && continue
    for n in api ai-worker web-resident web-admin; do
      docker rmi "${IMAGE_PREFIX}${n}:${tag}" >/dev/null 2>&1 \
        && echo "  삭제 ${IMAGE_PREFIX}${n}:${tag}" || true
    done
  done
  # 중간 레이어만 정리한다. `-a` 는 쓰지 않는다 — 롤백 대상 이미지를 통째로 날린다.
  docker image prune -f >/dev/null
  ok "정리 완료"
}

case "${1:-}" in
  build)    build_images ;;
  deploy)   deploy ;;
  smoke)    smoke ;;
  publish)  publish ;;
  status)   status ;;
  tags)     tags ;;
  # 롤백은 재기동과 같은 동작이다 — 다른 IMAGE_TAG 를 주는 것이 전부다(docs/12 전제 2).
  rollback) [ -n "${IMAGE_TAG:-}" ] || die "IMAGE_TAG 필요"; deploy; smoke ;;
  down)     log "정지 (볼륨 보존)"; dc down --remove-orphans; ok "정지 완료" ;;
  prune)    prune ;;
  all)      build_images; deploy; smoke ;;
  *)        sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 2 ;;
esac
