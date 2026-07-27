// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

import type { StaffMember } from "@/lib/api";

const listStaff = vi.fn();
const getMe = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  listStaff: () => listStaff(),
  getMe: () => getMe(),
  inviteStaff: vi.fn(),
  deactivateStaff: vi.fn(),
  deleteStaff: vi.fn(),
}));

import { StaffAdmin } from "./StaffAdmin";

const STAFF: StaffMember[] = [
  {
    userId: "u-me",
    name: "김소장",
    email: "manager@example.com",
    roles: ["MANAGER", "STAFF"],
    status: "active",
    invitedAt: "2026-07-01T09:00:00Z",
  },
  {
    userId: "u-staff",
    name: "박직원",
    email: "staff@example.com",
    roles: ["STAFF"],
    status: "invited",
    invitedAt: "2026-07-20T09:00:00Z",
  },
];

beforeEach(() => {
  listStaff.mockResolvedValue([...STAFF]);
  getMe.mockResolvedValue({ userId: "u-me" });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("StaffAdmin 직원 목록", () => {
  it("문서 관리와 같은 열 헤더를 가진 표로 렌더한다", async () => {
    render(<StaffAdmin />);
    await screen.findByText("박직원");

    for (const name of ["이름", "이메일", "역할", "상태", "초대일", "관리"]) {
      expect(screen.getByRole("columnheader", { name })).toBeDefined();
    }
  });

  it("역할·상태·초대일을 행에 노출하고 자기 자신 행에는 삭제를 숨긴다", async () => {
    render(<StaffAdmin />);
    await screen.findByText("박직원");

    expect(screen.getByText("소장 · 직원")).toBeDefined();
    expect(screen.getByText("초대됨")).toBeDefined();
    expect(screen.getByText("2026-07-20")).toBeDefined();
    // 소장(자기 자신) 행은 삭제 불가 → 삭제 버튼은 직원 행 1개뿐.
    expect(screen.getAllByRole("button", { name: "삭제" }).length).toBe(1);
  });

  // e2e(signup-journey)가 /staff 진입 즉시 초대 폼을 채우므로 상시 노출을 고정한다.
  it("초대 폼은 접기 토글 없이 항상 노출된다", async () => {
    render(<StaffAdmin />);
    await screen.findByLabelText("직원 이름");

    expect(screen.getByRole("region", { name: "직원 초대" })).toBeDefined();
    // "직원 초대" 버튼은 폼 제출 1개뿐 — 토글 버튼은 없다.
    expect(screen.getAllByRole("button", { name: "직원 초대" }).length).toBe(1);
    expect(screen.queryByRole("button", { name: "초대 폼 닫기" })).toBeNull();
  });

  it("1페이지뿐이면 페이저를 숨긴다", async () => {
    render(<StaffAdmin />);
    await screen.findByText("박직원");

    expect(screen.queryByRole("navigation", { name: "직원 목록 페이지" })).toBeNull();
  });

  it("20건을 넘으면 첫 페이지 20건만 렌더하고 페이저를 보인다", async () => {
    const many = Array.from({ length: 21 }, (_, i) => ({
      ...STAFF[1],
      userId: `u-${i}`,
      name: `직원${String(i).padStart(2, "0")}`,
      email: `staff${i}@example.com`,
    }));
    listStaff.mockResolvedValue(many);
    render(<StaffAdmin />);
    await screen.findByText("직원00");

    expect(screen.getByRole("navigation", { name: "직원 목록 페이지" })).toBeDefined();
    expect(screen.getByText("1 / 2 페이지 · 21건")).toBeDefined();
    expect(screen.queryByText("직원20")).toBeNull();
  });
});
