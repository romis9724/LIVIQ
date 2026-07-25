import { describe, expect, it } from "vitest";
import type { ParkingCore, ParkingSpot, ParkingVehicle } from "@/lib/api";
import {
  OCCUPANCY_RATE,
  SIM_SEED,
  elapsedText,
  makeRand,
  simulateParking,
  summarize,
} from "./parking-sim";

const NOW_MS = Date.parse("2026-07-25T12:00:00Z");
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

const CORES: ParkingCore[] = [
  { name: "401동", x: 200, y: 100, w: 72, h: 128 },
  { name: "402동", x: 900, y: 100, w: 72, h: 128 },
];

function makeVehicles(n: number, everyEv = 0): ParkingVehicle[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `veh-${i}`,
    householdId: `hh-${i}`,
    dong: i % 2 === 0 ? "401동" : "402동",
    ho: `${100 + i}호`,
    plate: `${10 + i}가${1000 + i}`,
    model: "아이오닉5",
    isEv: everyEv > 0 && i % everyEv === 0,
  }));
}

describe("makeRand", () => {
  it("returns the same sequence for the same seed", () => {
    const a = makeRand(SIM_SEED);
    const b = makeRand(SIM_SEED);
    const seqA = [a(), a(), a(), a()];
    const seqB = [b(), b(), b(), b()];

    expect(seqA).toEqual(seqB);
    expect(seqA.every((v) => v >= 0 && v < 1)).toBe(true);
  });

  it("returns a different sequence for a different seed", () => {
    expect(makeRand(1)()).not.toBe(makeRand(2)());
  });
});

describe("simulateParking", () => {
  it("produces identical occupancy for the same seed and inputs", () => {
    const spots = makeSpots(60);
    const vehicles = makeVehicles(30);

    const first = simulateParking(spots, CORES, vehicles, SIM_SEED, NOW_MS);
    const second = simulateParking(spots, CORES, vehicles, SIM_SEED, NOW_MS);

    expect([...second.bySpot.entries()]).toEqual([...first.bySpot.entries()]);
    expect([...second.occupied]).toEqual([...first.occupied]);
  });

  it("parks roughly the configured occupancy rate of resident vehicles", () => {
    const spots = makeSpots(400);
    const vehicles = makeVehicles(200);

    const { bySpot } = simulateParking(spots, CORES, vehicles, SIM_SEED, NOW_MS);
    const residents = [...bySpot.values()].filter((car) => !car.external);

    // 재실률 75% ±10%p — 시드 고정이라 결정적이지만 구현 세부에 과하게 묶지 않는다.
    const rate = residents.length / vehicles.length;
    expect(rate).toBeGreaterThan(OCCUPANCY_RATE - 0.1);
    expect(rate).toBeLessThan(OCCUPANCY_RATE + 0.1);
  });

  it("never assigns accessible spots and reserves EV spots for EV vehicles", () => {
    const spots = makeSpots(40, {
      0: { kind: "장애인" },
      1: { kind: "장애인" },
      2: { kind: "전기차" },
      3: { kind: "전기차" },
    });
    const vehicles = makeVehicles(30); // EV 없음

    const { bySpot } = simulateParking(spots, CORES, vehicles, SIM_SEED, NOW_MS);

    expect(bySpot.has("001")).toBe(false);
    expect(bySpot.has("002")).toBe(false);
    expect(bySpot.has("003")).toBe(false);
    expect(bySpot.has("004")).toBe(false);
  });

  it("allows EV vehicles on EV spots", () => {
    // 전기차면만 있는 배치 — EV 차량이면 배정되고, 비-EV 차량이면 한 대도 못 세운다.
    const spots = makeSpots(6, {
      0: { kind: "전기차" },
      1: { kind: "전기차" },
      2: { kind: "전기차" },
      3: { kind: "전기차" },
      4: { kind: "전기차" },
      5: { kind: "전기차" },
    });

    const evSim = simulateParking(spots, CORES, makeVehicles(6, 1), SIM_SEED, NOW_MS);
    const gasSim = simulateParking(spots, CORES, makeVehicles(6), SIM_SEED, NOW_MS);

    expect([...evSim.bySpot.values()].filter((car) => !car.external).length).toBeGreaterThan(0);
    expect([...gasSim.bySpot.values()].filter((car) => !car.external)).toHaveLength(0);
  });

  it("adds 8 external cars with plates that never collide", () => {
    const spots = makeSpots(200);
    const vehicles = makeVehicles(50);

    const { bySpot } = simulateParking(spots, CORES, vehicles, SIM_SEED, NOW_MS);
    const externals = [...bySpot.values()].filter((car) => car.external);
    const plates = [...bySpot.values()].map((car) => car.plate);
    const residentPlates = new Set(vehicles.map((v) => v.plate));

    expect(externals).toHaveLength(8);
    expect(new Set(plates).size).toBe(plates.length);
    expect(externals.some((car) => residentPlates.has(car.plate))).toBe(false);
    // 외부 차량은 세대 정보가 없다(입주민 DB 미등록).
    expect(externals.every((car) => car.dong === null && car.ho === null)).toBe(true);
  });

  it("keeps entry times in the past relative to nowMs", () => {
    const { bySpot } = simulateParking(makeSpots(120), CORES, makeVehicles(40), SIM_SEED, NOW_MS);

    expect([...bySpot.values()].every((car) => car.entryMs < NOW_MS)).toBe(true);
  });

  it("stops assigning when spots run out", () => {
    const spots = makeSpots(5);

    const { bySpot, occupied } = simulateParking(spots, CORES, makeVehicles(50), SIM_SEED, NOW_MS);

    expect(bySpot.size).toBeLessThanOrEqual(spots.length);
    expect(occupied.size).toBe(bySpot.size);
  });

  it("prefers spots near the vehicle's own building core", () => {
    // 401동 코어(x≈236)와 402동 코어(x≈936) 사이에 넓게 면을 깔고 401동 차량만 세운다.
    const spots = makeSpots(60);
    const vehicles = makeVehicles(8).map((v) => ({ ...v, dong: "401동" }));

    const { bySpot } = simulateParking(spots, [CORES[0]!], vehicles, SIM_SEED, NOW_MS, 1);
    const xs = [...bySpot.keys()]
      .map((no) => spots.find((sp) => sp.no === no))
      .filter((sp): sp is ParkingSpot => sp !== undefined)
      .filter((sp) => !bySpot.get(sp.no)?.external)
      .map((sp) => sp.x);

    // 코어(x 236) 근처에 몰려야 한다 — 평균이 배치 중앙(x≈1160)보다 훨씬 왼쪽.
    const mean = xs.reduce((sum, x) => sum + x, 0) / xs.length;
    expect(mean).toBeLessThan(700);
  });
});

describe("summarize", () => {
  it("keeps counts consistent (resident+external=occupied, occupied+empty=total)", () => {
    const spots = makeSpots(120);
    const { bySpot } = simulateParking(spots, CORES, makeVehicles(40), SIM_SEED, NOW_MS);

    const counts = summarize(spots, bySpot);

    expect(counts.total).toBe(spots.length);
    expect(counts.resident + counts.external).toBe(counts.occupied);
    expect(counts.occupied + counts.empty).toBe(counts.total);
    expect(counts.occupied).toBe(bySpot.size);
  });

  it("counts resident cars per building and excludes external cars", () => {
    const spots = makeSpots(40);
    const { bySpot } = simulateParking(spots, CORES, makeVehicles(20), SIM_SEED, NOW_MS);

    const counts = summarize(spots, bySpot);
    const byDongTotal = Object.values(counts.byDong).reduce((sum, n) => sum + n, 0);

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
