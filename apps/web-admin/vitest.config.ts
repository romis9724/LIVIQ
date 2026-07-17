import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// 순수 로직·데이터 + 자립형 컴포넌트 테스트.
// Next tsconfig는 jsx: preserve라 vitest용으로 automatic 변환을 명시한다.
export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: {
    // tsconfig paths(@/*)와 정렬 — 런타임 로드되는 모듈이 alias를 쓸 때 필요(web-resident와 동일).
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: { provider: "v8", include: ["src/features/**"] },
  },
});
