// @vitest-environment jsdom
// 민원현황 패널 드릴다운(H20-13) — 상태 카드 → 목록 → 민원 요약. 표시 로직은 panel-data 단위
// 테스트가 맡고, 여기서는 클릭 경로와 서버 조회 횟수(목록 1회·처리 내역은 펼칠 때만)를 고정한다.
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import type { Inquiry, InquiryEvent } from "@/lib/api";

const listAdminInquiries = vi.fn();
const listInquiryEvents = vi.fn();

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listAdminInquiries: () => listAdminInquiries(),
    listInquiryEvents: (id: string) => listInquiryEvents(id),
  };
});
vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

import { InquiryStatusPanel } from "./InquiryStatusPanel";

const DAY = 86_400_000;
const daysAgo = (n: number): string => new Date(Date.now() - n * DAY).toISOString();

function inquiry(over: Partial<Inquiry> & Pick<Inquiry, "id" | "status">): Inquiry {
  return {
    title: `민원 ${over.id}`,
    body: "천장에서 물이 샙니다",
    priority: null,
    categoryCodeId: null,
    assigneeUserId: null,
    authorUserId: "u1",
    createdAt: daysAgo(1),
    updatedAt: daysAgo(1),
    facilityId: null,
    facilityName: null,
    ...over,
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("InquiryStatusPanel 드릴다운", () => {
  it("미배정 카드를 누르면 접수일자·경과일이 붙은 목록이 열린다", async () => {
    listAdminInquiries.mockResolvedValue([
      inquiry({ id: "a", status: "received", createdAt: daysAgo(10) }),
      inquiry({ id: "b", status: "done" }),
    ]);
    render(<InquiryStatusPanel />);

    const card = await screen.findByRole("button", { name: /미배정/ });
    fireEvent.click(card);

    expect(card.getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: /민원 a/ })).toBeTruthy();
    expect(screen.getByText(/10일 경과/)).toBeTruthy();
    // 완료 건은 이 목록에 섞이지 않는다.
    expect(screen.queryByRole("button", { name: /민원 b/ })).toBeNull();
    // 목록은 마운트 1회 조회분을 걸러 쓴다 — 카드 클릭으로 재조회하지 않는다.
    expect(listAdminInquiries).toHaveBeenCalledTimes(1);
  });

  it("완료 카드는 완료일자를 보여주고 경과일은 붙이지 않는다", async () => {
    listAdminInquiries.mockResolvedValue([
      inquiry({ id: "b", status: "done", createdAt: daysAgo(30), updatedAt: daysAgo(2) }),
    ]);
    render(<InquiryStatusPanel />);

    fireEvent.click(await screen.findByRole("button", { name: /완료/ }));

    expect(screen.getByText(/^완료 \d{2}\/\d{2}$/)).toBeTruthy();
    expect(screen.queryByText(/경과/)).toBeNull();
  });

  it("민원을 누르면 내용 요약·처리 내역과 민원 관리 링크가 펼쳐진다", async () => {
    listAdminInquiries.mockResolvedValue([inquiry({ id: "a", status: "in_progress" })]);
    const events: InquiryEvent[] = [
      {
        id: "e1",
        type: "comment",
        actorUserId: null,
        payload: { kind: "reply", body: "배관 교체 예정" },
        createdAt: daysAgo(1),
      },
    ];
    listInquiryEvents.mockResolvedValue(events);
    render(<InquiryStatusPanel />);

    fireEvent.click(await screen.findByRole("button", { name: /처리중/ }));
    // 펼치기 전에는 처리 내역을 조회하지 않는다(토큰·왕복 절약).
    expect(listInquiryEvents).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /민원 a/ }));

    expect(screen.getByText("천장에서 물이 샙니다")).toBeTruthy();
    await waitFor(() => expect(screen.getByText(/담당자 답변 · 배관 교체 예정/)).toBeTruthy());
    expect(screen.getByRole("link", { name: "민원 관리에서 열기" }).getAttribute("href")).toBe(
      "/inquiries?inquiry=a",
    );
  });

  it("처리 내역 조회가 실패해도 패널은 살아 있다", async () => {
    listAdminInquiries.mockResolvedValue([inquiry({ id: "a", status: "received" })]);
    listInquiryEvents.mockRejectedValue(new Error("서버 오류"));
    render(<InquiryStatusPanel />);

    fireEvent.click(await screen.findByRole("button", { name: /미배정/ }));
    fireEvent.click(screen.getByRole("button", { name: /민원 a/ }));

    await waitFor(() => expect(screen.getByText("서버 오류")).toBeTruthy());
    expect(screen.getByText("민원 현황")).toBeTruthy();
  });
});
