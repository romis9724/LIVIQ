/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // 게이트 빌드(pnpm build)가 실행 중인 dev 서버의 .next를 덮어써 500을 내던 충돌 방지 —
  // build/start는 NEXT_DIST_DIR=.next-build로 분리 실행(package.json), dev는 기본 .next.
  distDir: process.env.NEXT_DIST_DIR || ".next",
  transpilePackages: ["@liviq/ui"],
  experimental: {
    optimizePackageImports: ["@liviq/ui"],
  },
};

export default nextConfig;
