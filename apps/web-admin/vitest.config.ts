import { defineConfig } from "vitest/config";

// 순수 로직·데이터 + 자립형 컴포넌트 테스트.
// Next tsconfig는 jsx: preserve라 vitest용으로 automatic 변환을 명시한다.
export default defineConfig({
  esbuild: { jsx: "automatic" },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: { provider: "v8", include: ["src/features/**"] },
  },
});
