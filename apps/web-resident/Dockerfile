# syntax=docker/dockerfile:1
# @liviq/web-resident 프로덕션 이미지 (ADR-0020 — Next standalone 산출물만 런타임에 복사).
# 빌드 컨텍스트는 반드시 레포 루트: docker build -f apps/web-resident/Dockerfile .

# Node 20 LTS 고정 핀. latest·lts 태그는 재빌드마다 실체가 바뀌어 sha 롤백이 성립하지 않는다(docs/09 §4.3).
ARG NODE_IMAGE=node:20.20.1-alpine3.22

# ---------- builder ----------
FROM ${NODE_IMAGE} AS builder
WORKDIR /repo

# 루트 package.json 의 packageManager(pnpm@9.12.3)를 그대로 쓰기 위해 corepack 사용.
# 비대화 빌드에서 다운로드 확인 프롬프트가 뜨지 않게 끈다.
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

# 락파일 + 전 워크스페이스 매니페스트만 먼저 복사해 install 레이어를 캐시한다.
# --frozen-lockfile 은 워크스페이스 전체 매니페스트를 락파일과 대조하므로 멤버 하나라도 빠지면 실패한다.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/ai-worker/package.json ./apps/ai-worker/
COPY apps/api/package.json ./apps/api/
COPY apps/web-admin/package.json ./apps/web-admin/
COPY apps/web-resident/package.json ./apps/web-resident/
COPY packages/ai-core/package.json ./packages/ai-core/
COPY packages/api-types/package.json ./packages/api-types/
COPY packages/config-ts/package.json ./packages/config-ts/
COPY packages/db/package.json ./packages/db/
COPY packages/ui/package.json ./packages/ui/
COPY tests/e2e/package.json ./tests/e2e/

# 이 앱과 그 워크스페이스 의존만 설치(`...` = 의존 포함). e2e(playwright) 등은 제외된다.
RUN pnpm install --frozen-lockfile --filter @liviq/web-resident...

# 소스는 필요한 경로만 명시 복사한다 — 호스트의 node_modules 심볼릭 링크·빌드 산출물·.env.local 유입 차단.
# @liviq/ui 는 빌드 산출물 없이 소스를 export 하므로(transpilePackages) 빌드 시점에 src 가 있어야 한다.
COPY packages/config-ts ./packages/config-ts
COPY packages/ui/tsconfig.json ./packages/ui/
COPY packages/ui/src ./packages/ui/src
COPY apps/web-resident/next.config.mjs apps/web-resident/tsconfig.json apps/web-resident/next-env.d.ts ./apps/web-resident/
COPY apps/web-resident/src ./apps/web-resident/src

# NEXT_PUBLIC_* 은 빌드타임에 번들로 인라인되어 런타임 주입이 불가능하다(ADR-0020 결정 4).
# 기본값 /api = web tier 리버스 프록시 경유 same-origin 호출.
ARG NEXT_PUBLIC_API_BASE_URL=/api
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}

# 기존 스크립트 그대로 사용 — NEXT_DIST_DIR=.next-build 를 설정하므로 산출물은 .next-build/ 다.
RUN pnpm --filter @liviq/web-resident build

# ---------- runner ----------
FROM ${NODE_IMAGE} AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
# standalone 서버는 HOSTNAME 을 그대로 바인드한다 — 기본값이면 localhost 만 열려 컨테이너 밖에서 접속 불가.
ENV HOSTNAME=0.0.0.0

# standalone 트리는 outputFileTracingRoot(레포 루트) 기준이라 서버 진입점이 apps/web-resident/server.js 다.
COPY --from=builder --chown=node:node /repo/apps/web-resident/.next-build/standalone ./
# standalone 서버는 정적 자산을 자기 트리의 <distDir>/static 에서 찾는다 — distDir 이 .next-build 이므로 그 위치로 복사.
COPY --from=builder --chown=node:node /repo/apps/web-resident/.next-build/static ./apps/web-resident/.next-build/static
# public/ 디렉토리는 이 앱에 없어서 복사하지 않는다.

# alpine 기본 비특권 유저.
USER node

EXPOSE 3000

CMD ["node", "apps/web-resident/server.js"]
