import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// 순수 로직·데이터 무결성 테스트. 컴포넌트(jsdom+RTL)는 추후 도입.
export default defineConfig({
  resolve: {
    // tsconfig paths(@/*) 와 정렬 — 런타임 로드되는 모듈이 alias 를 쓸 때 필요.
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: { provider: "v8", include: ["src/lib/**"] },
  },
});
