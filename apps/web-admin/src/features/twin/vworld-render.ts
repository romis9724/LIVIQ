/**
 * 실사 3D(VWorld/Cesium) 렌더 헬퍼 — 프로토타입 dashboard_vworld.html 로직을
 * LIVIQ props 계약(geometry·overlay·onSelectHousehold)으로 포팅한다(H9-3b).
 * VWorld 스크립트가 런타임 전역으로 주입하는 Cesium/vw/ws3d 를 window 에서 읽는다
 * (npm 번들 미포함 — 런타임 로드). React·수명주기는 useVWorld 가 담당하고 여기는 순수 헬퍼만.
 *
 * MVP 범위: 실사 배경 + 세대 shell + 클릭 피킹 + 오버레이 recolor.
 * TODO(후속): 우리 단지만 3D 건물 클리핑(프로토타입 setupTilesets·buildClipPlanes)·
 *   지형 지반고 샘플링(sampleGround)은 라이브 검증 후 포팅 — 좌표 평면 수학이라 브라우저 튜닝 필요.
 */

import type { TwinGeometryItem } from "@/lib/api";
import { colorForOverlay, type OverlayKind, type Rgb } from "./twin-data";

// VWorld/Cesium 런타임 객체 — 전량 타입 선언은 YAGNI. 좁은 any 별칭으로 경계 격리(주석 필수).
/* eslint-disable @typescript-eslint/no-explicit-any -- VWorld 전역은 런타임 주입, 번들 타입 없음 */
type CesiumApi = any;
type VwApi = any;
type Viewer = any;
type Primitive = any;
type Handler = any;
type CesiumEvent = any;
/* eslint-enable @typescript-eslint/no-explicit-any */

const VWORLD_SCRIPT_ID = "vworld-webgl-sdk";
const VWORLD_SDK_SRC = "https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=";

// 오버레이 투명도 — 실사 건물이 비치도록 낮은 틴트(프로토타입 SHELL_ALPHA와 동일).
const SHELL_ALPHA = 0.22;
// 지반 고도(m) 상수. ponytail: 지형 샘플링 승급은 후속(프로토타입 sampleGround) — 단지 규모엔 상수로 충분.
const GROUND_HEIGHT_M = 25;
// 실사 건물 모델보다 살짝 키워 반투명 쉘이 감싸도록(안에 묻히면 색이 안 보임).
const SHELL_SCALE = 1.2;

interface VWorldGlobals {
  Cesium?: CesiumApi;
  vw?: VwApi;
  ws3d?: { viewer?: Viewer };
}

function win(): VWorldGlobals {
  return window as unknown as VWorldGlobals;
}

/**
 * VWorld WebGL SDK 를 동적 <script> 로 1회만 로드한다(document.write 금지 — CSP·React).
 * 이미 로드됐으면 즉시 resolve, 로드 진행 중이면 기존 태그에 편승한다.
 */
export function loadVWorldScript(apiKey: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (win().vw?.Map) {
      resolve();
      return;
    }
    const existing = document.getElementById(VWORLD_SCRIPT_ID);
    if (existing) {
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error("VWorld 스크립트 로드 실패")), {
        once: true,
      });
      return;
    }
    const script = document.createElement("script");
    script.id = VWORLD_SCRIPT_ID;
    script.src = VWORLD_SDK_SRC + encodeURIComponent(apiKey);
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("VWorld 스크립트 로드 실패"));
    document.head.appendChild(script);
  });
}

/** 전 세대 폴리곤 첫 정점 평균 = 단지 중심 [lon, lat]. 정점이 없으면 [0, 0]. */
export function centerOf(geometry: readonly TwinGeometryItem[]): [number, number] {
  let sx = 0;
  let sy = 0;
  let n = 0;
  for (const item of geometry) {
    const p = item.polygon2d[0];
    if (!p) continue;
    sx += p[0] ?? 0;
    sy += p[1] ?? 0;
    n += 1;
  }
  if (n === 0) return [0, 0];
  return [sx / n, sy / n];
}

/** 폴리곤을 무게중심 기준으로 f배 확장 — 반투명 쉘이 실사 건물을 감싸게 한다. */
export function scaleCoords(coords: number[][], f: number): [number, number][] {
  let sx = 0;
  let sy = 0;
  for (const p of coords) {
    sx += p[0] ?? 0;
    sy += p[1] ?? 0;
  }
  const cx = sx / coords.length;
  const cy = sy / coords.length;
  return coords.map((p) => [cx + ((p[0] ?? 0) - cx) * f, cy + ((p[1] ?? 0) - cy) * f]);
}

function toCesiumColor(C: CesiumApi, [r, g, b]: Rgb, alpha: number): CesiumApi {
  return new C.Color(r / 255, g / 255, b / 255, alpha);
}

function shellColor(
  C: CesiumApi,
  item: TwinGeometryItem,
  overlay: Record<string, number>,
  overlayKind: OverlayKind,
): CesiumApi {
  return toCesiumColor(C, colorForOverlay(overlayKind, overlay[item.householdId]), SHELL_ALPHA);
}

/**
 * VWorld 맵 시작 — 컨테이너 id 에 조감도 initPosition 으로 렌더한다(프로토타입 startMap).
 * 뷰어 준비는 getReadyViewer 폴링으로 확인(비동기).
 */
export function startVWorldMap(containerId: string, center: [number, number]): void {
  const { vw } = win();
  const [cx, cy] = center;
  const map = new vw.Map();
  map.setOption({
    mapId: containerId,
    initPosition: new vw.CameraPosition(
      new vw.CoordZ(cx + 0.0018, cy - 0.0026, 260), // 남동쪽 조감도 각도
      new vw.Direction(-28, -33, 0),
    ),
    logo: false,
    navigation: true,
  });
  map.start();
}

/** ws3d.viewer 가 준비(scene 존재·미파괴)됐으면 반환, 아니면 null(폴링용). */
export function getReadyViewer(): Viewer | null {
  const viewer = win().ws3d?.viewer;
  if (viewer && viewer.scene && !viewer.isDestroyed?.()) return viewer;
  return null;
}

/** 전역 ws3d.viewer 를 안전하게 파괴(언마운트 정리). */
export function destroyViewer(): void {
  const viewer = win().ws3d?.viewer;
  if (viewer && !viewer.isDestroyed?.()) viewer.destroy();
}

/**
 * 세대 shell 을 단일 Primitive(draw call 1)로 배치한다(프로토타입 buildShellPrimitive).
 * 각 세대 polygon2d 를 살짝 키운 압출 폴리곤 + per-instance color(id=householdId → 피킹).
 */
export function buildShellPrimitive(
  viewer: Viewer,
  geometry: readonly TwinGeometryItem[],
  overlay: Record<string, number>,
  overlayKind: OverlayKind,
): Primitive {
  const C: CesiumApi = win().Cesium;
  const instances = geometry.map((item) => {
    const flat: number[] = [];
    for (const p of scaleCoords(item.polygon2d, SHELL_SCALE)) flat.push(p[0], p[1]);
    const base = GROUND_HEIGHT_M + item.baseZ;
    return new C.GeometryInstance({
      geometry: new C.PolygonGeometry({
        polygonHierarchy: new C.PolygonHierarchy(C.Cartesian3.fromDegreesArray(flat)),
        height: base,
        extrudedHeight: base + item.floorHeight,
        vertexFormat: C.PerInstanceColorAppearance.FLAT_VERTEX_FORMAT,
      }),
      attributes: {
        color: C.ColorGeometryInstanceAttribute.fromColor(shellColor(C, item, overlay, overlayKind)),
      },
      id: item.householdId,
    });
  });
  return viewer.scene.primitives.add(
    new C.Primitive({
      geometryInstances: instances,
      appearance: new C.PerInstanceColorAppearance({ flat: true, translucent: true, closed: false }),
      asynchronous: false,
    }),
  );
}

/**
 * 오버레이 변경 시 shell 색 갱신 — GPU per-instance 속성만 교체(기하 재생성 없음).
 * 아직 컴파일 전(!ready)이면 프로토타입처럼 새 색으로 재생성해 반환한다.
 */
export function recolorShell(
  viewer: Viewer,
  primitive: Primitive,
  geometry: readonly TwinGeometryItem[],
  overlay: Record<string, number>,
  overlayKind: OverlayKind,
): Primitive {
  const C: CesiumApi = win().Cesium;
  if (!primitive.ready) {
    viewer.scene.primitives.remove(primitive);
    return buildShellPrimitive(viewer, geometry, overlay, overlayKind);
  }
  for (const item of geometry) {
    const attrs = primitive.getGeometryInstanceAttributes(item.householdId);
    if (!attrs) continue;
    attrs.color = C.ColorGeometryInstanceAttribute.toValue(
      shellColor(C, item, overlay, overlayKind),
      attrs.color,
    );
  }
  return primitive;
}

/**
 * 피킹 핸들러 — hover 는 커서만 pointer, click 은 세대 id → onSelect(프로토타입 attachPicking).
 * drillPick 으로 실사 건물 뒤의 shell 까지 관통 탐색. 반환 Handler 는 정리 시 destroy.
 */
export function attachPicking(
  viewer: Viewer,
  householdIds: ReadonlySet<string>,
  onSelect: (householdId: string) => void,
): Handler {
  const C: CesiumApi = win().Cesium;
  const handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);

  const pick = (pos: CesiumEvent): string | null => {
    const picks = viewer.scene.drillPick(pos, 8);
    for (const p of picks) {
      if (p && typeof p.id === "string" && householdIds.has(p.id)) return p.id;
    }
    return null;
  };

  handler.setInputAction((m: CesiumEvent) => {
    viewer.scene.canvas.style.cursor = pick(m.endPosition) ? "pointer" : "default";
  }, C.ScreenSpaceEventType.MOUSE_MOVE);

  handler.setInputAction((m: CesiumEvent) => {
    const id = pick(m.position);
    if (id) onSelect(id);
  }, C.ScreenSpaceEventType.LEFT_CLICK);

  return handler;
}

/**
 * 인트로 비행이 끝나지 않는 비정상 상황(20초 후에도 고고도)에서만 단지 시점으로 1회 강제 이동.
 * 반환 타이머는 언마운트 시 clear.
 */
export function enforceCamera(viewer: Viewer, center: [number, number]): ReturnType<typeof setTimeout> {
  const C: CesiumApi = win().Cesium;
  const [cx, cy] = center;
  return setTimeout(() => {
    if (viewer.isDestroyed?.() || viewer.camera.positionCartographic.height <= 5000) return;
    viewer.camera.setView({
      destination: C.Cartesian3.fromDegrees(cx + 0.003, cy - 0.0045, GROUND_HEIGHT_M + 330),
      orientation: {
        heading: C.Math.toRadians(-28),
        pitch: C.Math.toRadians(-33),
        roll: 0,
      },
    });
  }, 20000);
}
