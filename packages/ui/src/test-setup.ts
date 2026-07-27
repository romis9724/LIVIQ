// 테스트 격리 — 파일 안에서 여러 번 render 해도 이전 DOM이 남지 않게 정리한다.
// (globals:false 라 @testing-library/react 자동 cleanup 이 등록되지 않는다.)
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(cleanup);
