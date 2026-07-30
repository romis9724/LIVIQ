import { describe, expect, it } from "vitest";
import type { ParkingOccupancy, ParkingSpot } from "@/lib/api";
import { EXTERNAL_GROUP, elapsedText, matchesGroup, occupancyToSim, summarize } from "./parking-sim";

const NOW_MS = Date.parse("2026-07-25T12:00:00Z");
const HOUR_MS = 3600e3;

/** 테스트 배치 — 한 줄에 n면, 전부 일반면. */
function makeSpots(n: number): ParkingSpot[] {
  return Array.from({ length: n }, (_, i) => ({
    no: String(i + 1).padStart(3, "0"),
    kind: "일반" as const,
    x: 100 + i * 36,
    y: 162,
    dir: (i % 2 === 0 ? "up" : "down") as ParkingSpot["dir"],
  }));
}

function resident(spotNo: string, dong: string, ho: string, parkedHours = 2): ParkingOccupancy {
  return {
    spotNo,
    isExternal: false,
    dong,
    ho,
    model: "아이오닉5",
    plate: `12가${spotNo}`,
    parkedHours,
  };
}

function external(spotNo: string, parkedHours = 30): ParkingOccupancy {
  return {
    spotNo,
    isExternal: true,
    dong: null,
    ho: null,
    model: null,
    plate: `99바${spotNo}`,
    parkedHours,
  };
}

describe("occupancyToSim", () => {
  it("maps occupancy rows into bySpot keyed by spot number", () => {
    const occupancy = [resident("001", "401동", "301호"), external("002")];

    const { bySpot, occupied } = occupancyToSim(occupancy, NOW_MS);

    expect(bySpot.size).toBe(2);
    expect([...occupied].sort()).toEqual(["001", "002"]);
    const car = bySpot.get("001");
    expect(car).toMatchObject({
      plate: "12가001",
      dong: "401동",
      ho: "301호",
      model: "아이오닉5",
      external: false,
    });
  });

  it("marks external rows as external with null household fields", () => {
    const { bySpot } = occupancyToSim([external("005")], NOW_MS);
    const car = bySpot.get("005");

    expect(car?.external).toBe(true);
    expect(car?.dong).toBeNull();
    expect(car?.ho).toBeNull();
    expect(car?.model).toBeNull();
  });

  it("derives entryMs from parked_hours relative to nowMs (stays in the past)", () => {
    const { bySpot } = occupancyToSim([resident("001", "401동", "301호", 3)], NOW_MS);

    expect(bySpot.get("001")?.entryMs).toBe(NOW_MS - 3 * HOUR_MS);
  });

  it("treats missing parked_hours as a just-arrived car (nowMs)", () => {
    const occupancy: ParkingOccupancy[] = [
      { spotNo: "001", isExternal: true, dong: null, ho: null, model: null, plate: "99바1", parkedHours: null },
    ];

    expect(occupancyToSim(occupancy, NOW_MS).bySpot.get("001")?.entryMs).toBe(NOW_MS);
  });
});

describe("summarize", () => {
  it("keeps counts consistent (resident+external=occupied, occupied+empty=total)", () => {
    const spots = makeSpots(10);
    const { bySpot } = occupancyToSim(
      [resident("001", "401동", "301호"), resident("002", "402동", "101호"), external("003")],
      NOW_MS,
    );

    const counts = summarize(spots, bySpot);

    expect(counts.total).toBe(10);
    expect(counts.occupied).toBe(3);
    expect(counts.resident + counts.external).toBe(counts.occupied);
    expect(counts.occupied + counts.empty).toBe(counts.total);
    expect(counts.external).toBe(1);
  });

  it("counts resident cars per building and excludes external cars", () => {
    const { bySpot } = occupancyToSim(
      [
        resident("001", "401동", "301호"),
        resident("002", "401동", "302호"),
        resident("003", "402동", "101호"),
        external("004"),
      ],
      NOW_MS,
    );

    const counts = summarize(makeSpots(10), bySpot);
    const byDongTotal = Object.values(counts.byDong).reduce((sum, n) => sum + n, 0);

    expect(byDongTotal).toBe(counts.resident);
    expect(counts.byDong).toEqual({ "401동": 2, "402동": 1 });
  });

  it("reports an empty layout as all-empty", () => {
    expect(summarize([], new Map())).toEqual({
      total: 0,
      occupied: 0,
      resident: 0,
      external: 0,
      empty: 0,
      byDong: {},
    });
  });
});

describe("matchesGroup", () => {
  it("matches external cars only for the external group key", () => {
    const { bySpot } = occupancyToSim([external("001"), resident("002", "401동", "301호")], NOW_MS);

    expect(matchesGroup(bySpot.get("001"), EXTERNAL_GROUP)).toBe(true);
    expect(matchesGroup(bySpot.get("002"), EXTERNAL_GROUP)).toBe(false);
    expect(matchesGroup(bySpot.get("002"), "401동")).toBe(true);
    expect(matchesGroup(undefined, "401동")).toBe(false);
  });
});

describe("elapsedText", () => {
  it("formats hours and minutes", () => {
    expect(elapsedText(NOW_MS - (3 * 60 + 20) * 60_000, NOW_MS)).toBe("3시간 20분");
  });

  it("omits hours under one hour", () => {
    expect(elapsedText(NOW_MS - 45 * 60_000, NOW_MS)).toBe("45분");
  });

  it("clamps future entry times to 0분", () => {
    expect(elapsedText(NOW_MS + 60_000, NOW_MS)).toBe("0분");
  });
});
