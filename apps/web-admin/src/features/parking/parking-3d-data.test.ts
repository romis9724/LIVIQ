import { describe, expect, it } from "vitest";
import type { ParkingSpot } from "@/lib/api";
import { PX_TO_M, SPOT_H, SPOT_W, type ParkedCar } from "./parking-sim";
import {
  cruiseRoutes,
  entryShot,
  floorSize,
  pathLength,
  pointAlongPath,
  outlineToShape,
  overviewShot,
  rectCenter,
  sceneState,
  spotPlacements,
  spotShot,
  toMeters,
} from "./parking-3d-data";

const SPOTS: ParkingSpot[] = [
  { no: "001", kind: "일반", x: 130, y: 162, dir: "up" },
  { no: "002", kind: "일반", x: 166, y: 162, dir: "down" },
  { no: "003", kind: "전기차", x: 202, y: 162, dir: "up" },
];

function car(overrides: Partial<ParkedCar> = {}): ParkedCar {
  return {
    plate: "12가3456",
    dong: "401동",
    ho: "101호",
    model: "아이오닉5",
    external: false,
    entryMs: 0,
    ...overrides,
  };
}

describe("floorSize", () => {
  it("converts the viewBox size to meters", () => {
    expect(floorSize("0 0 3020 1082")).toEqual({
      w: 3020 * PX_TO_M,
      h: 1082 * PX_TO_M,
    });
  });

  it("falls back to zero when the viewBox is unparseable", () => {
    expect(floorSize("")).toEqual({ w: 0, h: 0 });
  });
});

describe("spotPlacements", () => {
  it("projects the spot centre onto the metre floor plane", () => {
    const [first] = spotPlacements(SPOTS);

    expect(first?.no).toBe("001");
    expect(first?.x).toBeCloseTo(toMeters(130 + SPOT_W / 2), 6);
    expect(first?.z).toBeCloseTo(toMeters(162 + SPOT_H / 2), 6);
  });

  it("rotates spots facing down by 180 degrees", () => {
    const [up, down] = spotPlacements(SPOTS);

    expect(up?.rotY).toBe(0);
    expect(down?.rotY).toBeCloseTo(Math.PI, 6);
  });

  it("keeps the input order so instance indexes stay stable", () => {
    expect(spotPlacements(SPOTS).map((p) => p.no)).toEqual(["001", "002", "003"]);
  });
});

describe("sceneState", () => {
  const placements = spotPlacements(SPOTS);

  it("marks unoccupied spots as empty and emits no car instances", () => {
    const state = sceneState(placements, new Map(), null, null);

    expect(state.tones).toEqual(["empty", "empty", "empty"]);
    expect(state.cars).toEqual([]);
  });

  it("splits occupied spots into resident and external", () => {
    const bySpot = new Map<string, ParkedCar>([
      ["001", car()],
      ["002", car({ external: true, dong: null, ho: null })],
    ]);

    const state = sceneState(placements, bySpot, null, null);

    expect(state.tones).toEqual(["resident", "external", "empty"]);
    expect(state.cars.map((c) => c.no)).toEqual(["001", "002"]);
    expect(state.cars.map((c) => c.tone)).toEqual(["resident", "external"]);
  });

  it("gives the selected spot priority over its occupancy tone", () => {
    const bySpot = new Map<string, ParkedCar>([["001", car()]]);

    const state = sceneState(placements, bySpot, "001", null);

    expect(state.tones[0]).toBe("selected");
    expect(state.cars[0]?.tone).toBe("selected");
  });

  it("dims everything outside the active group, empty spots included", () => {
    const bySpot = new Map<string, ParkedCar>([
      ["001", car({ dong: "401동" })],
      ["002", car({ dong: "402동" })],
    ]);

    const state = sceneState(placements, bySpot, null, "401동");

    expect(state.tones).toEqual(["resident", "dim", "dim"]);
    expect(state.cars.map((c) => c.tone)).toEqual(["resident", "dim"]);
  });

  it("matches external cars for the 외부 group", () => {
    const bySpot = new Map<string, ParkedCar>([
      ["001", car()],
      ["002", car({ external: true, dong: null, ho: null })],
    ]);

    const state = sceneState(placements, bySpot, null, "외부");

    expect(state.tones).toEqual(["dim", "external", "dim"]);
  });

  it("carries the placement of each occupied spot to its car instance", () => {
    const bySpot = new Map<string, ParkedCar>([["002", car()]]);

    const state = sceneState(placements, bySpot, null, null);

    expect(state.cars[0]).toMatchObject({ ...placements[1], tone: "resident" });
  });
});

describe("camera shots", () => {
  const size = { w: 232, h: 83 };

  it("ends the entry sweep above and behind the whole floor", () => {
    const shot = overviewShot(size);

    expect(shot.position.x).toBeCloseTo(size.w / 2, 6);
    expect(shot.position.y).toBeGreaterThan(entryShot(size).position.y);
    expect(shot.position.z).toBeGreaterThan(size.h);
    expect(shot.target).toEqual({ x: size.w / 2, y: 0, z: size.h / 2 });
  });

  it("starts the entry sweep low near the ramp side", () => {
    const shot = entryShot(size);

    expect(shot.position.y).toBeLessThan(overviewShot(size).position.y);
    expect(shot.position.x).toBeLessThan(size.w / 2);
  });

  it("frames the selected spot from just in front of it", () => {
    const [placement] = spotPlacements(SPOTS);
    if (!placement) throw new Error("placement 없음");

    const shot = spotShot(placement);

    expect(shot.position.x).toBeCloseTo(placement.x, 6);
    expect(shot.position.z).toBeGreaterThan(placement.z);
    expect(shot.target.x).toBeCloseTo(placement.x, 6);
    expect(shot.target.z).toBeCloseTo(placement.z, 6);
  });
});

describe("cruiseRoutes", () => {
  // 시드 배치도와 같은 구조 — 4개의 주차열 띠(각 2줄) 사이에 통로가 있다.
  const ROWS = [162, 226, 372, 436, 582, 646, 792, 856];
  const LAYOUT_SPOTS: ParkingSpot[] = ROWS.flatMap((y, row) =>
    [100, 2872].map((x, col) => ({
      no: `${row}-${col}`,
      kind: "일반" as const,
      x,
      y,
      dir: "up" as const,
    })),
  );

  it("puts five cars on the aisles, none on a parking row", () => {
    const routes = cruiseRoutes(LAYOUT_SPOTS);

    expect(routes).toHaveLength(5);
    // 주차열 띠(row..row+SPOT_H)를 가로지르는 가로 차선이 없어야 한다.
    const bands = [
      [162, 290],
      [372, 500],
      [582, 710],
      [792, 920],
    ].map(([top, bottom]) => [toMeters(top ?? 0), toMeters(bottom ?? 0)] as const);
    for (const route of routes) {
      for (const point of route.path) {
        for (const [top, bottom] of bands) {
          expect(point.z > top && point.z < bottom).toBe(false);
        }
      }
    }
  });

  it("spreads the cars along their loop so they never bunch up", () => {
    const routes = cruiseRoutes(LAYOUT_SPOTS);
    const byPath = new Map<string, number[]>();
    for (const route of routes) {
      const key = JSON.stringify(route.path);
      byPath.set(key, [...(byPath.get(key) ?? []), route.startOffsetM]);
    }

    expect(byPath.size).toBe(2); // 바깥 순환 + 안쪽 순환
    for (const offsets of byPath.values()) {
      expect(new Set(offsets).size).toBe(offsets.length);
    }
  });

  it("returns nothing when the layout has no parking rows", () => {
    expect(cruiseRoutes([])).toEqual([]);
  });
});

describe("pointAlongPath", () => {
  const SQUARE = [
    { x: 0, z: 0 },
    { x: 10, z: 0 },
    { x: 10, z: 10 },
    { x: 0, z: 10 },
  ];

  it("walks the segments and faces the direction of travel", () => {
    const at = pointAlongPath(SQUARE, 4);

    expect(at).toMatchObject({ x: 4, z: 0 });
    expect(at.rotY).toBeCloseTo(Math.PI / 2, 6); // +x 방향
  });

  it("wraps around the closed loop", () => {
    expect(pointAlongPath(SQUARE, pathLength(SQUARE) + 4)).toEqual(pointAlongPath(SQUARE, 4));
    expect(pointAlongPath(SQUARE, -pathLength(SQUARE))).toEqual(pointAlongPath(SQUARE, 0));
  });
});

describe("geometry helpers", () => {
  it("flips the y axis of building outlines into floor z", () => {
    expect(outlineToShape([[13, 26]])).toEqual([{ x: 1, y: -2 }]);
  });

  it("returns the centre of a layout rect in metres", () => {
    expect(rectCenter({ x: 13, y: 26, w: 26, h: 52 })).toEqual({ x: 2, z: 4 });
  });
});
