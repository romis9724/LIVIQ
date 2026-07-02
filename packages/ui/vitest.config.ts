import { defineConfig } from "vitest/config";

// 순수 유틸·로직 단위 테스트. DOM 필요한 컴포넌트 테스트는
// jsdom + @testing-library/react 도입 후 environment를 "jsdom"으로 전환.
export default defineConfig({
  test: {
    // 기본 node. 컴포넌트 테스트는 파일 상단 `// @vitest-environment jsdom`로 개별 전환.
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      include: ["src/lib/**", "src/components/**"],
    },
  },
});
