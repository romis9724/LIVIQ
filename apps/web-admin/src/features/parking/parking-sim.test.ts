import { describe, expect, it } from "vitest";
import type { ParkingSpot, ParkingVehicle } from "@/lib/api";
import {
  EXTERNAL_GROUP,
  elapsedText,
  matchesGroup,
  occupancyFromVehicles,
  summarize,
} from "./parking-sim";

const NOW_MS = Date.parse("2026-07-25T12:00:00Z");
const ENTRY_AT = "2026-07-25T09:30:00Z";
const SPOT_PITCH = 36;

/** 테스트 배치 — 한 줄에 n면, 기본은 전부 일반면. */
function makeSpots(n: number, override: Partial<Record<number, Partial<ParkingSpot>>> = {}) {
  return Array.from({ length: n }, (_, i) => ({
    no: String(i + 1).padStart(3, "0"),
    kind: "일반" as const,
    x: 100 + i * SPOT_PITCH,
    y: 162,
    dir: (i % 2 === 0 ? "up" : "down") as ParkingSpot["dir"],
    ...override[i],
  }));
}

function vehicle(overrides: Partial<ParkingVehicle> = {}): ParkingVehicle {
  return {
    id: "veh-1",
    householdId: "hh-1",
    dong: "401동",
    ho: "101호",
    plate: "12가3456",
    model: "아이오닉5",
    isEv: false,
    spotNo: "001",
    entryAt: ENTRY_AT,
    external: false,
    ...overrides,
  };
}

/** 입주민 n대 — 면 001부터 순서대로 주차. */
function parkedResidents(n: number): ParkingVehicle[] {
  return Array.from({ length: n }, (_, i) =>
    vehicle({
      id: `veh-${i}`,
      householdId: `hh-${i}`,
      dong: i % 2 === 0 ? "401동" : "402동",
      ho: `${100 + i}호`,
      plate: `${10 + i}가${1000 + i}`,
      spotNo: String(i + 1).padStart(3, "0"),
    }),
  );
}

describe("occupancyFromVehicles", () => {
  it("indexes parked vehicles by spot number", () => {
    // Arrange
    const vehicles = parkedResidents(3);

    // Act
    const { bySpot, occupied } = occupancyFromVehicles(vehicles);

    // Assert
    expect([...bySpot.keys()]).toEqual(["001", "002", "003"]);
    expect([...occupied]).toEqual(["001", "002", "003"]);
    expect(bySpot.get("002")).toEqual({
      plate: "11가1001",
      dong: "402동",
      ho: "101호",
      model: "아이오닉5",
      external: false,
      entryMs: Date.parse(ENTRY_AT),
    });
  });

  it("excludes vehicles without a spot (registered but not parked)", () => {
    // Arrange
    const vehicles = [vehicle({ spotNo: null, entryAt: null }), vehicle({ id: "veh-2" })];

    // Act
    const { bySpot } = occupancyFromVehicles(vehicles);

    // Assert
    expect(bySpot.size).toBe(1);
    expect(bySpot.has("001")).toBe(true);
  });

  it("maps external vehicles without household labels", () => {
    // Arrange
    const external = vehicle({
      id: "veh-ext",
      householdId: null,
      dong: null,
      ho: null,
      model: null,
      external: true,
      spotNo: "010",
    });

    // Act
    const car = occupancyFromVehicles([external]).bySpot.get("010");

    // Assert
    expect(car).toMatchObject({ external: true, dong: null, ho: null, model: null });
  });

  it("falls back to entryMs 0 when entryAt is missing or unparseable", () => {
    // Arrange
    const vehicles = [
      vehicle({ id: "veh-1", spotNo: "001", entryAt: null }),
      vehicle({ id: "veh-2", spotNo: "002", entryAt: "not-a-date" }),
    ];

    // Act
    const { bySpot } = occupancyFromVehicles(vehicles);

    // Assert
    expect(bySpot.get("001")?.entryMs).toBe(0);
    expect(bySpot.get("002")?.entryMs).toBe(0);
  });

  it("keeps the last vehicle when two share a spot (DB partial unique should prevent it)", () => {
    // Arrange
    const vehicles = [
      vehicle({ id: "veh-1", plate: "11가1111", spotNo: "001" }),
      vehicle({ id: "veh-2", plate: "22나2222", spotNo: "001" }),
    ];

    // Act
    const { bySpot, occupied } = occupancyFromVehicles(vehicles);

    // Assert
    expect(bySpot.size).toBe(1);
    expect(occupied.size).toBe(1);
    expect(bySpot.get("001")?.plate).toBe("22나2222");
  });

  it("returns an empty occupancy for no vehicles", () => {
    expect(occupancyFromVehicles([]).bySpot.size).toBe(0);
  });
});

describe("summarize", () => {
  it("keeps counts consistent (resident+external=occupied, occupied+empty=total)", () => {
    const spots = makeSpots(120);
    const { bySpot } = occupancyFromVehicles([
      ...parkedResidents(40),
      vehicle({ id: "ext-1", external: true, dong: null, ho: null, spotNo: "100" }),
    ]);

    const counts = summarize(spots, bySpot);

    expect(counts.total).toBe(spots.length);
    expect(counts.resident + counts.external).toBe(counts.occupied);
    expect(counts.occupied + counts.empty).toBe(counts.total);
    expect(counts.occupied).toBe(bySpot.size);
  });

  it("counts resident cars per building and excludes external cars", () => {
    const spots = makeSpots(40);
    const { bySpot } = occupancyFromVehicles([
      ...parkedResidents(20),
      vehicle({ id: "ext-1", external: true, dong: null, ho: null, spotNo: "030" }),
    ]);

    const counts = summarize(spots, bySpot);
    const byDongTotal = Object.values(counts.byDong).reduce((sum, n) => sum + n, 0);

    expect(counts.external).toBe(1);
    expect(byDongTotal).toBe(counts.resident);
    expect(Object.keys(counts.byDong).sort()).toEqual(["401동", "402동"]);
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
  it("matches resident cars by building name", () => {
    const car = occupancyFromVehicles([vehicle()]).bySpot.get("001");

    expect(matchesGroup(car, "401동")).toBe(true);
    expect(matchesGroup(car, "402동")).toBe(false);
    expect(matchesGroup(car, EXTERNAL_GROUP)).toBe(false);
  });

  it("matches external cars only on the external group", () => {
    const car = occupancyFromVehicles([
      vehicle({ external: true, dong: null, ho: null }),
    ]).bySpot.get("001");

    expect(matchesGroup(car, EXTERNAL_GROUP)).toBe(true);
    expect(matchesGroup(car, "401동")).toBe(false);
  });

  it("never matches an empty spot", () => {
    expect(matchesGroup(undefined, "401동")).toBe(false);
    expect(matchesGroup(undefined, EXTERNAL_GROUP)).toBe(false);
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
