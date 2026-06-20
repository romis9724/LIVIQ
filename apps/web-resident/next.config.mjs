/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // @liviq/ui 는 빌드 산출물 없이 소스(TS/CSS)를 그대로 export → Next 가 트랜스파일.
  transpilePackages: ["@liviq/ui"],
  experimental: {
    optimizePackageImports: ["@liviq/ui"],
  },
};

export default nextConfig;
