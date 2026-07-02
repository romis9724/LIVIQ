import { defineConfig } from "vitest/config";

// 순수 로직·데이터 무결성 테스트. 컴포넌트(jsdom+RTL)는 추후 도입.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: { provider: "v8", include: ["src/lib/**"] },
  },
});
