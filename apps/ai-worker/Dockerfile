# LIVIQ ai-worker 이미지 — arq 큐 워커 (ADR-0020 결정 1)
# 빌드 컨텍스트는 **레포 루트**다 (uv workspace 단일 lock):
#   docker build -f apps/ai-worker/Dockerfile -t liviq-ai-worker:local .

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
RUN uv sync --frozen --no-dev --no-editable --package liviq-ai-worker --no-install-workspace

# 2단계: 소스 복사 후 워크스페이스 멤버 설치. liviq-ai-worker 의 의존은 db·ai-core 뿐이라
# api 소스는 복사하지 않는다.
# --no-editable: 멤버를 실제 wheel 로 site-packages 에 넣는다. editable(기본값)이면
# .venv 가 빌더의 소스 경로를 가리켜 런타임 스테이지에서 import 가 깨진다.
COPY packages/db packages/db
COPY packages/ai-core packages/ai-core
COPY apps/ai-worker apps/ai-worker
RUN uv sync --frozen --no-dev --no-editable --package liviq-ai-worker

# ── 런타임 스테이지 ───────────────────────────────────────────
FROM python:3.12-slim-trixie AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"

# non-root 실행(ADR-0020 결정 1). 홈·셸 없는 시스템 계정.
RUN groupadd --system --gid 10001 liviq \
 && useradd --system --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin liviq

WORKDIR /app

# 빌더 산출물은 .venv 만 — ai_worker·db·ai-core 코드는 --no-editable 로 이미 그 안에 있다.
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv

USER 10001:10001

# HTTP 표면이 없는 큐 워커 → EXPOSE·HEALTHCHECK 없음(찍을 엔드포인트가 없다).
# env·시크릿은 전부 런타임 주입(이미지에 미포함).
CMD ["arq", "ai_worker.worker.WorkerSettings"]
