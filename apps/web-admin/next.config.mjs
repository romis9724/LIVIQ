/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  transpilePackages: ["@liviq/ui"],
  experimental: {
    optimizePackageImports: ["@liviq/ui"],
  },
};

export default nextConfig;
