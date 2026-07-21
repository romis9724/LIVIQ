// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

import type { Approval } from "@/lib/api";

// api 모듈을 목킹 — 컴포넌트 배선(마스킹 그대로 노출·거절 사유 필수)만 검증한다.
const listApprovals = vi.fn();
const approveSignup = vi.fn();
const rejectSignup = vi.fn();
const uploadRoster = vi.fn();
const listRoster = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  ROSTER_TEMPLATE_URL: "http://test/admin/roster/template",
  listApprovals: () => listApprovals(),
  approveSignup: (id: string) => approveSignup(id),
  rejectSignup: (id: string, reason: string) => rejectSignup(id, reason),
  uploadRoster: (file: File) => uploadRoster(file),
  listRoster: (params?: object) => listRoster(params),
}));

import { Residents } from "./Residents";

const SIGNUPS: Approval[] = [
  {
    userId: "u1",
    nameMasked: "홍*동",
    rosterMatched: true,
    mismatchReason: null,
    buildingName: "103",
    floor: 15,
    unitNo: 1502,
    requestedAt: "2026-07-13T09:00:00Z",
  },
  {
    userId: "u2",
    nameMasked: "김*늘",
    rosterMatched: false,
    mismatchReason: "person_mismatch",
    buildingName: "103",
    floor: 2,
    unitNo: 208,
    requestedAt: "2026-07-12T09:00:00Z",
  },
];

beforeEach(() => {
  listApprovals.mockResolvedValue([...SIGNUPS]);
  listRoster.mockResolvedValue({
    items: [
      { nameMasked: "박*부", buildingName: "103", floor: 15, unitNo: 1502, state: "unregistered" },
    ],
    total: 1,
    counts: { total: 1, unregistered: 1, joined: 0, movedOut: 0 },
    lastUpload: { uploadedAt: "2026-07-22T10:00:00Z", rowCount: 3, errorCount: 0 },
  });
  approveSignup.mockResolvedValue(undefined);
  rejectSignup.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("Approvals", () => {
  it("서버가 마스킹한 이름을 그대로 노출한다(재마스킹 없음)", async () => {
    render(<Residents />);
    expect(await screen.findByText("홍*동")).toBeDefined();
    expect(screen.getByText("103동 1502호")).toBeDefined();
  });

  it("명부 일치/불일치 배지를 노출한다", async () => {
    const { container } = render(<Residents />);
    await screen.findByText("홍*동");
    expect(container.querySelectorAll(".apv-match--ok").length).toBe(1);
    expect(container.querySelectorAll(".apv-match--warn").length).toBe(1);
  });

  it("승인하면 목록에서 사라지고 대기 건수가 준다", async () => {
    const { container } = render(<Residents />);
    await screen.findByText("홍*동");
    const count = () => container.querySelector(".apv-count")?.textContent;
    expect(count()).toBe("2건 대기");

    fireEvent.click(screen.getAllByRole("button", { name: "승인" })[0]!);
    await waitFor(() => expect(count()).toBe("1건 대기"));
    expect(approveSignup).toHaveBeenCalledWith("u1");
  });

  it("거절은 사유 입력 전까지 확정 버튼이 비활성", async () => {
    render(<Residents />);
    await screen.findByText("홍*동");
    fireEvent.click(screen.getAllByRole("button", { name: "거절" })[0]!);

    const confirm = screen.getByRole("button", { name: "거절 확정" }) as HTMLButtonElement;
    expect(confirm.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/거절 사유/), {
      target: { value: "명부 미등록 세대" },
    });
    expect(confirm.disabled).toBe(false);
  });

  it("모든 신청을 처리하면 빈 상태를 보여준다", async () => {
    listApprovals.mockResolvedValue([]);
    render(<Residents />);
    expect(await screen.findByText(/대기 중인 가입 신청이 없습니다/)).toBeDefined();
  });
});
