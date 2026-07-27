// @vitest-environment jsdom
// 목록 조회 응답 순서 회귀 — 느린 첫 조회가 등록 직후 목록을 덮어쓰면 안 된다(E2E 간헐 실패 원인).
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";

import type { Facility, FacilityDetail } from "@/lib/api";

const listFacilities = vi.fn();
const createFacility = vi.fn();
const getFacility = vi.fn();

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {},
  listFacilities: () => listFacilities(),
  createFacility: (input: unknown) => createFacility(input),
  getFacility: (id: string) => getFacility(id),
  patchFacility: vi.fn(),
  createIncident: vi.fn(),
  createMaintenance: vi.fn(),
}));

import { FacilityManager } from "./FacilityManager";

function facility(name: string, id: string): Facility {
  return {
    id,
    code: null,
    name,
    location: null,
    type: null,
    status: "normal",
    nextCheckAt: null,
    createdAt: "2026-07-25T00:00:00Z",
  };
}

function detailOf(item: Facility): FacilityDetail {
  return { ...item, incidents: [], maintenanceLogs: [] };
}

/** 수동으로 완료 시점을 정하는 지연 응답 — 응답 역전을 결정론적으로 만든다. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

beforeEach(() => {
  getFacility.mockImplementation((id: string) =>
    Promise.resolve(detailOf(facility("E2E 승강기", id))),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FacilityManager 목록 응답 순서", () => {
  it("느린 첫 조회가 늦게 도착해도 등록 직후 목록을 덮어쓰지 않는다", async () => {
    const created = facility("E2E 승강기 1784980256630", "f-new");
    const slowFirstLoad = deferred<Facility[]>();

    // 1회차(마운트 시) 조회는 보류시켰다가 나중에 "빈 목록"으로 응답 — CI 콜드스타트 재현.
    listFacilities
      .mockReturnValueOnce(slowFirstLoad.promise)
      .mockResolvedValue([created]);
    createFacility.mockResolvedValue(created);

    render(<FacilityManager />);

    fireEvent.click(screen.getByRole("button", { name: "설비 등록" }));
    fireEvent.change(screen.getByLabelText("설비 이름"), { target: { value: created.name } });
    fireEvent.click(screen.getByRole("button", { name: "등록" }));

    // 등록 후 재조회가 먼저 반영된다.
    await waitFor(() => expect(screen.getByText(created.name)).toBeDefined());

    // 그제서야 첫 조회(등록 전 스냅샷)가 도착 — 이 결과는 버려져야 한다.
    slowFirstLoad.resolve([]);
    await waitFor(() => expect(listFacilities).toHaveBeenCalledTimes(2));

    expect(screen.getByText(created.name)).toBeDefined();
    expect(screen.queryByText("시설이 없습니다")).toBeNull();
  });
});
