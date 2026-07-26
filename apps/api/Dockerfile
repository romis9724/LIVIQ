# LIVIQ api 이미지 — FastAPI 서버 + Alembic 마이그레이션 러너 (ADR-0020 결정 1·5)
# 빌드 컨텍스트는 **레포 루트**다 (uv workspace 단일 lock):
#   docker build -f apps/api/Dockerfile -t liviq-api:local .

# ── 빌더 스테이지 ─────────────────────────────────────────────
# 태그 핀: `latest`는 재빌드마다 실체가 바뀐다(docs/09 §4.3 "고정 태그 핀").
# uv 0.11.14 = 로컬 개발 버전과 동일. bookworm 이 아니라 trixie 인 이유: uv 공식 이미지의
# bookworm 변형은 0.9.30 에서 끊겼다(현행 태그는 trixie/alpine뿐 — ghcr 태그 목록 실측).
# python3.12 는 런타임 스테이지와 **동일 마이너**, Debian 도 **동일 릴리스**여야
# 복사한 .venv 와 컴파일 wheel(glibc)이 그대로 동작한다.
FROM ghcr.io/astral-sh/uv:0.11.14-python3.12-trixie-slim AS builder

# UV_COMPILE_BYTECODE: 콜드 스타트 단축(런타임은 쓰기 금지라 여기서 미리 컴파일)
# UV_LINK_MODE=copy: 캐시 마운트에서의 하드링크 경고 회피(컨테이너 빌드 권장값)
# UV_PYTHON_DOWNLOADS=never: 베이스 이미지의 Python만 쓴다(다른 마이너 끌어오는 사고 방지)
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# 1단계 캐시: 매니페스트+lock 만 복사해 **외부 의존만** 설치.
# --no-install-workspace = 변경이 잦은 워크스페이스 멤버를 건너뛴다 → 소스만 바뀌면
# 이 레이어가 그대로 재사용된다. lock 검증을 위해 멤버 4종의 pyproject.toml 은 모두 필요.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY apps/ai-worker/pyproject.toml apps/ai-worker/
COPY packages/ai-core/pyproject.toml packages/ai-core/
COPY packages/db/pyproject.toml packages/db/
RUN uv sync --frozen --no-dev --no-editable --package liviq-api --no-install-workspace

# 2단계: 소스 복사 후 워크스페이스 멤버 설치. liviq-api 의 의존은 db·ai-core 뿐이라
# ai-worker 소스는 복사하지 않는다.
# --no-editable: 멤버를 실제 wheel 로 site-packages 에 넣는다. editable(기본값)이면
# .venv 가 빌더의 소스 경로를 가리켜 런타임 스테이지에서 import 가 깨진다.
COPY packages/db packages/db
COPY packages/ai-core packages/ai-core
COPY apps/api apps/api
RUN uv sync --frozen --no-dev --no-editable --package liviq-api

# ── 런타임 스테이지 ───────────────────────────────────────────
FROM python:3.12-slim-trixie AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# non-root 실행(ADR-0020 결정 1). 홈·셸 없는 시스템 계정.
RUN groupadd --system --gid 10001 liviq \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin liviq

WORKDIR /app

# 빌더 산출물은 .venv 만 — api·db·ai-core 코드는 --no-editable 로 이미 그 안에 있다.
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv

# Alembic 자산은 wheel 밖이다(hatch wheel 은 src/liviq_db 만 포함) → 명시 복사(ADR-0020 결정 5).
# alembic.ini 의 `script_location = alembic` 은 상대경로라 아래 경로가 작업 디렉토리여야 한다.
COPY --chown=10001:10001 packages/db/alembic /app/packages/db/alembic
COPY --chown=10001:10001 packages/db/alembic.ini /app/packages/db/alembic.ini

# 최초 SYS_ADMIN 부트스트랩(H7-2, ADR-0014) — 신규 배포에서 첫 관리자를 만드는 **유일한 경로**라
# 이미지에 포함해야 한다(없으면 빈 DB에 로그인할 계정이 없다). 실행:
#   docker compose ... run --rm --workdir /app api \
#     python scripts/bootstrap_sys_admin.py --email admin@example.com
# scripts/ 의 나머지(seed_demo·seed_parking·seed_households·backfill)는 **넣지 않는다** —
# seed_demo 는 공개된 고정 비밀번호로 MANAGER 계정을 만들어 운영 이미지에 두면 위험하고,
# 데이터 적재 스크립트는 워크스테이션에서 DB에 직접 붙여 1회 실행하는 성격이다.
COPY --chown=10001:10001 apps/api/scripts/bootstrap_sys_admin.py /app/scripts/bootstrap_sys_admin.py

# 마이그레이션 러너로 쓸 때(compose one-shot `migrate` 서비스)는 커맨드 오버라이드:
#   working_dir: /app/packages/db
#   command: ["alembic", "upgrade", "head"]
# DATABASE_URL 은 alembic/env.py 가 liviq_db.config(Pydantic Settings)에서 읽으므로
# CLI 인자로 넘기지 않는다. 시크릿·env 는 전부 런타임 주입(이미지에 미포함).

USER 10001:10001

EXPOSE 8000

# /health 는 apps/api/app/main.py 의 실제 엔드포인트. slim 베이스에 curl·wget 이 없어
# (그리고 apt 설치를 피하려고) venv 의 python 으로 확인한다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

# --proxy-headers: web tier 리버스 프록시(Caddy) 뒤에서 스킴·클라이언트 IP 정합(ADR-0020 결정 4).
# ★ 그것만으로는 부족하다: uvicorn은 `--forwarded-allow-ips`(기본 127.0.0.1)에 있는 peer의
#   X-Forwarded-For만 신뢰한다. Caddy는 **다른 컨테이너/호스트**라 기본값에서는 무시되고,
#   `request.client.host`가 프록시 IP가 된다(감사 로그 ip가 전부 Caddy IP로 찍힌 실측 결함).
#   신뢰 범위는 배포 형상에 달렸으므로 이미지에 굽지 않고 env `FORWARDED_ALLOW_IPS`로 준다
#   (uvicorn이 직접 읽는 표준 env — infra/env.prod.example 참조).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
