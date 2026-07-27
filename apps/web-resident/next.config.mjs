import path from "node:path";
import { fileURLToPath } from "node:url";

// 모노레포 루트(레포 루트) — 하드코딩 절대경로 금지, 이 파일 위치에서 계산.
const MONOREPO_ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 컨테이너 이미지는 standalone 산출물만 복사한다(ADR-0020) — 런타임에 node_modules 전체 불필요.
  output: "standalone",
  // pnpm 심볼릭 링크 워크스페이스에서 추적 루트를 레포 루트로 고정하지 않으면
  // 워크스페이스 의존을 잘못된 상대경로로 추적해 런타임 모듈 해석이 깨진다.
  outputFileTracingRoot: MONOREPO_ROOT,
  // 게이트 빌드(pnpm build)가 실행 중인 dev 서버의 .next를 덮어써 500을 내던 충돌 방지 —
  // build/start는 NEXT_DIST_DIR=.next-build로 분리 실행(package.json), dev는 기본 .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  // @liviq/ui 는 빌드 산출물 없이 소스(TS/CSS)를 그대로 export → Next 가 트랜스파일.
  transpilePackages: ["@liviq/ui"],
  // optimizePackageImports(["@liviq/ui"]) 제거(H14) — dev 서버가 배럴 분석을 캐시해
  // ui에 export를 추가할 때마다 undefined 컴포넌트로 깨졌다(.next 삭제 전까지, 3회 실증).
  // 프로덕션 tree-shaking은 ESM으로 충분하다.
};

export default nextConfig;
