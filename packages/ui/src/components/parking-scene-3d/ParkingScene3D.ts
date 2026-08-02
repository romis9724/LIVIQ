/**
 * 지하주차장 fake 3D 씬 — 프로토타입 `parking_view3d.js`(전역 IIFE) 포팅. (H14-4)
 * 배치도 2D 좌표를 미터 바닥면(x,z)에 투영해 면·차량을 InstancedMesh 로 그린다. 실측 3D 모델이
 * 아니라 배치도의 입체 표현이다. 좌표·상태 계산은 parking-scene-data(테스트 대상), 여기는 렌더만.
 * (web-admin → H20-8 공용 승격 — 입주민 3D가 두 번째 소비자. 추천 자리 순위 비콘 추가)
 *
 * three 를 직접 다루는 유일한 주차 모듈 — 소비자는 next/dynamic ssr:false 로만 불러
 * 타 라우트 번들에 새지 않게 한다(facilities/FacilityGraphCanvas 전례 · ADR-0022 결정 4).
 */

import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  SPOT_H_M,
  SPOT_W_M,
  cruiseRoutes,
  floorSize,
  outlineToShape,
  overviewShot,
  pointAlongPath,
  rectCenter,
  spotPlacements,
  spotShot,
  toMeters,
  type CameraShot,
  type CarTone,
  type CruiseRoute,
  type ParkingSceneLayout,
  type SceneState,
  type SpotPlacement,
  type SpotTone,
} from "./parking-scene-data";

/** 씬 색 — three 는 oklch 를 못 읽어 parking-scene-3d.css `:root` 에 sRGB hex 로 따로 둔다. */
export const SCENE_COLOR_VARS = {
  background: "--pk3d-bg",
  floor: "--pk3d-floor",
  line: "--pk3d-line",
  empty: "--pk3d-empty",
  resident: "--pk3d-resident",
  external: "--pk3d-external",
  dim: "--pk3d-dim",
  selected: "--pk3d-selected",
  carResident: "--pk3d-car-resident",
  carExternal: "--pk3d-car-external",
  glass: "--pk3d-glass",
  building: "--pk3d-building",
  core: "--pk3d-core",
  box: "--pk3d-box",
  label: "--pk3d-label",
  cruiseA: "--pk3d-cruise-a",
  cruiseB: "--pk3d-cruise-b",
  beacon: "--pk3d-beacon",
} as const;

export type SceneColors = Record<keyof typeof SCENE_COLOR_VARS, string>;

/** 추천 자리 비콘 1개 — 순위(1부터)와 면 번호. */
export interface SpotBeacon {
  spotNo: string;
  rank: number;
}

export interface ParkingScene3DOptions {
  container: HTMLElement;
  layout: ParkingSceneLayout;
  colors: SceneColors;
  /** 주행 차량·비콘 애니메이션 — prefers-reduced-motion 이면 false(배치만 하고 멈춘다). */
  driving: boolean;
  /** 면·차량 클릭(짧은 클릭만 — 드래그는 카메라 회전). */
  onSpotClick: (spotNo: string) => void;
}

// ── 씬 상수(미터) ────────────────────────────────────────────────────────────
const FLOOR_MARGIN_M = 8;
const SPOT_INSET_M = 0.2; // 면 평면을 주차선 안쪽으로 살짝 들여 선이 보이게
const SPOT_PLANE_Y = 0.02;
const SPOT_LINE_Y = 0.03;
const BUILDING_HEIGHT_M = 6;
const BUILDING_OPACITY = 0.16;
const CORE_HEIGHT_M = 12;
const BOX_HEIGHT_M = 2.2;
const CAR_BODY = { w: 1.9, h: 1.15, d: 4.4 } as const;
const CAR_CABIN = { w: 1.65, h: 0.62, d: 2.1 } as const;
const LABEL_SCALE_M = 0.055; // 캔버스 px → 미터(부감 거리 ~100m 에서 읽히는 크기)
const BUILDING_LABEL_Y = CORE_HEIGHT_M + 3.5;
const BOX_LABEL_Y = BOX_HEIGHT_M + 2;
const CAMERA_FAR_RATIO = 4;
const MIN_REACH_M = 60; // 바닥 폭 하한(카메라 far·최대거리 계산의 0 방지)
const MAX_DISTANCE_RATIO = 2;
const FLY_MS = 1800;
const MAX_PIXEL_RATIO = 2;
const CLICK_MOVE_PX = 6;
const CLICK_MS = 400;
const MAX_FRAME_S = 0.1; // 프레임 간격 상한(탭 복귀 직후 큰 dt 로 차가 튀지 않게)

// 비콘 — 추천 면 위에 떠 있는 역원뿔 + 순위 스프라이트. 부감(~100m)에서도 읽혀야 한다.
const BEACON_CONE_RADIUS_M = 1.6;
const BEACON_CONE_HEIGHT_M = 3.2;
const BEACON_BASE_Y = 6.5; // 원뿔 중심 높이
const BEACON_LABEL_GAP_M = 3.4; // 원뿔 위 순위 라벨까지 간격
const BEACON_BOB_M = 0.7; // 위아래 부유 진폭
const BEACON_BOB_HZ = 0.6;

const SPOT_TONE_COLOR: Record<SpotTone, keyof SceneColors> = {
  empty: "empty",
  resident: "resident",
  external: "external",
  dim: "dim",
  selected: "selected",
};
const CAR_TONE_COLOR: Record<CarTone, keyof SceneColors> = {
  resident: "carResident",
  external: "carExternal",
  dim: "dim",
  selected: "selected",
};

const easeInOutCubic = (t: number): number =>
  t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;

interface Tween {
  start: number;
  dur: number;
  fromPosition: THREE.Vector3;
  toPosition: THREE.Vector3;
  fromTarget: THREE.Vector3;
  toTarget: THREE.Vector3;
}

/** 텍스트 스프라이트(동명·구역명·비콘 순위) — 라벨 라이브러리 없이 이미 의존성인 three 만 쓴다. */
function textSprite(text: string, color: string): THREE.Sprite {
  const fontSize = 48;
  const padding = 16;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const font = `700 ${fontSize}px sans-serif`;
  if (ctx) {
    ctx.font = font;
    canvas.width = Math.ceil(ctx.measureText(text).width) + padding * 2;
    canvas.height = fontSize + padding * 2;
    ctx.font = font; // 캔버스 크기 변경은 컨텍스트를 리셋한다
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    // 라벨은 어두운 바닥 위와 밝은 배경 위를 모두 지나간다 — 외곽선을 둘러 어디서나 읽히게 한다.
    ctx.lineJoin = "round";
    ctx.lineWidth = 8;
    ctx.strokeStyle = "rgba(20, 24, 28, 0.75)";
    ctx.strokeText(text, canvas.width / 2, canvas.height / 2);
    ctx.fillStyle = color;
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({ map: texture, depthTest: false, transparent: true }),
  );
  sprite.scale.set(canvas.width * LABEL_SCALE_M, canvas.height * LABEL_SCALE_M, 1);
  return sprite;
}

export class ParkingScene3D {
  private readonly container: HTMLElement;
  private readonly colors: SceneColors;
  private readonly onSpotClick: (spotNo: string) => void;
  private readonly placements: SpotPlacement[];
  private readonly size: { w: number; h: number };

  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly controls: OrbitControls;
  private readonly spotMesh: THREE.InstancedMesh;
  private readonly bodyMesh: THREE.InstancedMesh;
  private readonly cabinMesh: THREE.InstancedMesh;
  private readonly resizeObserver: ResizeObserver;

  /** 주행 차량 5대 — 픽킹 대상이 아니고(raycast 목록 밖) 점유 데이터와도 무관한 연출이다. */
  private readonly cruisers: { group: THREE.Group; route: CruiseRoute; distance: number }[] = [];
  private readonly driving: boolean;

  /** 추천 자리 비콘 — setBeacons() 로 통째로 갈아 끼운다. 부유 애니메이션은 animate 루프. */
  private beacons: { group: THREE.Group; baseY: number; phase: number }[] = [];

  /** 차량 인스턴스 index → 면 번호(픽킹). */
  private carSpotNos: string[] = [];
  private tween: Tween | null = null;
  private frameId: number | null = null;
  private lastFrameMs = 0;
  private active = false;
  private disposed = false;
  private pointerStart = { x: 0, y: 0, at: 0 };

  constructor({ container, layout, colors, driving, onSpotClick }: ParkingScene3DOptions) {
    this.container = container;
    this.colors = colors;
    this.driving = driving;
    this.onSpotClick = onSpotClick;
    this.placements = spotPlacements(layout.spots);
    this.size = floorSize(layout.viewBox);

    // 바닥 폭 기준 원·최대거리 — viewBox 가 비정상이어도 카메라가 무효값이 되지 않게 하한을 둔다.
    const reach = Math.max(MIN_REACH_M, this.size.w);
    this.camera = new THREE.PerspectiveCamera(55, 16 / 9, 0.1, reach * CAMERA_FAR_RATIO);
    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setPixelRatio(Math.min(MAX_PIXEL_RATIO, window.devicePixelRatio));
    container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI / 2 - 0.06; // 바닥 아래로 못 내려간다
    this.controls.maxDistance = reach * MAX_DISTANCE_RATIO;

    this.buildStatic(layout);
    this.spotMesh = this.buildSpotMesh();
    const [bodyMesh, cabinMesh] = this.buildCarMeshes();
    this.bodyMesh = bodyMesh;
    this.cabinMesh = cabinMesh;
    this.buildCruisers(layout.spots);

    // 진입 스윕 없이 바로 전체 부감(사용자 지시) — 이동 애니메이션은 면 클로즈업·'전체 보기'에서만.
    this.applyShot(overviewShot(this.size));
    this.renderer.domElement.addEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.addEventListener("pointerup", this.handlePointerUp);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
  }

  // ── 정적 씬 ────────────────────────────────────────────────────────────────
  private buildStatic(layout: ParkingSceneLayout): void {
    const { w, h } = this.size;
    this.scene.background = new THREE.Color(this.colors.background);
    const reach = Math.max(MIN_REACH_M, w);
    this.scene.fog = new THREE.Fog(this.colors.background, reach * 1.2, reach * 3);
    // 원본은 어두운 씬이라 밝기 합이 1.85 였다 — 라이트 테마 팔레트에서는 흰색으로 날아가므로
    // 위쪽을 향한 면(바닥·주차면)이 1.0 근처에 떨어지도록 낮춰 잡는다.
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x8d949c, 0.62));
    const sun = new THREE.DirectionalLight(0xffffff, 0.45);
    sun.position.set(w * 0.3, w * 0.5, h * 0.4);
    this.scene.add(sun);

    const floor = new THREE.Mesh(
      new THREE.PlaneGeometry(w + FLOOR_MARGIN_M, h + FLOOR_MARGIN_M),
      new THREE.MeshLambertMaterial({ color: this.colors.floor }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(w / 2, 0, h / 2);
    this.scene.add(floor);
    this.scene.add(this.buildSpotLines());
    this.buildLayoutSolids(layout);
  }

  /** 동 footprint(반투명 extrude)·엘리베이터 코어·램프/설비실 박스 + 이름 라벨. */
  private buildLayoutSolids(layout: ParkingSceneLayout): void {
    for (const building of layout.buildings) {
      const shape = new THREE.Shape(
        outlineToShape(building.outline).map((p) => new THREE.Vector2(p.x, p.y)),
      );
      const mesh = new THREE.Mesh(
        new THREE.ExtrudeGeometry(shape, { depth: BUILDING_HEIGHT_M, bevelEnabled: false }),
        new THREE.MeshLambertMaterial({
          color: this.colors.building,
          transparent: true,
          opacity: BUILDING_OPACITY,
          depthWrite: false,
        }),
      );
      mesh.rotation.x = -Math.PI / 2; // shape(x,-y) → 바닥(x,z), extrude → +y
      this.scene.add(mesh);

      const label = textSprite(building.name, this.colors.label);
      label.position.set(toMeters(building.cx), BUILDING_LABEL_Y, toMeters(building.cy));
      this.scene.add(label);
    }

    for (const core of layout.cores) {
      const center = rectCenter(core);
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(toMeters(core.w), CORE_HEIGHT_M, toMeters(core.h)),
        new THREE.MeshLambertMaterial({ color: this.colors.core }),
      );
      mesh.position.set(center.x, CORE_HEIGHT_M / 2, center.z);
      this.scene.add(mesh);
    }

    for (const box of layout.boxes) {
      const center = rectCenter(box);
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(toMeters(box.w), BOX_HEIGHT_M, toMeters(box.h)),
        new THREE.MeshLambertMaterial({ color: this.colors.box }),
      );
      mesh.position.set(center.x, BOX_HEIGHT_M / 2, center.z);
      this.scene.add(mesh);
      const label = textSprite(box.label, this.colors.label);
      label.position.set(center.x, BOX_LABEL_Y, center.z);
      this.scene.add(label);
    }
  }

  /** 주차선 — 면마다 사각 테두리를 하나의 LineSegments 로 병합한다(드로우콜 1회). */
  private buildSpotLines(): THREE.LineSegments {
    const points: number[] = [];
    for (const placement of this.placements) {
      const x0 = placement.x - SPOT_W_M / 2;
      const x1 = placement.x + SPOT_W_M / 2;
      const z0 = placement.z - SPOT_H_M / 2;
      const z1 = placement.z + SPOT_H_M / 2;
      const y = SPOT_LINE_Y;
      points.push(
        ...[x0, y, z0, x1, y, z0, x1, y, z0, x1, y, z1],
        ...[x1, y, z1, x0, y, z1, x0, y, z1, x0, y, z0],
      );
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute(points, 3));
    return new THREE.LineSegments(
      geometry,
      new THREE.LineBasicMaterial({ color: this.colors.line, transparent: true, opacity: 0.7 }),
    );
  }

  /** 면 상태 평면 — 위치는 고정이라 여기서 굳히고, 색만 update() 에서 바꾼다. */
  private buildSpotMesh(): THREE.InstancedMesh {
    const geometry = new THREE.PlaneGeometry(
      SPOT_W_M - SPOT_INSET_M * 2,
      SPOT_H_M - SPOT_INSET_M * 2,
    );
    geometry.rotateX(-Math.PI / 2);
    const mesh = new THREE.InstancedMesh(
      geometry,
      new THREE.MeshLambertMaterial({ transparent: true, opacity: 0.9 }),
      Math.max(1, this.placements.length),
    );
    const matrix = new THREE.Matrix4();
    const color = new THREE.Color(this.colors.empty);
    this.placements.forEach((placement, index) => {
      matrix.makeTranslation(placement.x, SPOT_PLANE_Y, placement.z);
      mesh.setMatrixAt(index, matrix);
      mesh.setColorAt(index, color);
    });
    mesh.count = this.placements.length;
    this.scene.add(mesh);
    return mesh;
  }

  /** 차량 인스턴스 2벌(차체 + 캐빈). update() 전에는 아무것도 그리지 않는다. */
  private buildCarMeshes(): [THREE.InstancedMesh, THREE.InstancedMesh] {
    const capacity = Math.max(1, this.placements.length);
    const bodyGeometry = new THREE.BoxGeometry(CAR_BODY.w, CAR_BODY.h, CAR_BODY.d);
    bodyGeometry.translate(0, CAR_BODY.h / 2 + 0.15, 0);
    const cabinGeometry = new THREE.BoxGeometry(CAR_CABIN.w, CAR_CABIN.h, CAR_CABIN.d);
    cabinGeometry.translate(0, CAR_BODY.h + CAR_CABIN.h / 2 + 0.15, 0.25);
    const bodyMesh = new THREE.InstancedMesh(
      bodyGeometry,
      new THREE.MeshLambertMaterial(),
      capacity,
    );
    const cabinMesh = new THREE.InstancedMesh(
      cabinGeometry,
      new THREE.MeshLambertMaterial({ color: this.colors.glass }),
      capacity,
    );
    bodyMesh.count = 0;
    cabinMesh.count = 0;
    this.scene.add(bodyMesh, cabinMesh);
    return [bodyMesh, cabinMesh];
  }

  /**
   * 앰비언트 주행 차량 — 차로(주차열 사이 통로)만 순환한다. 지오메트리는 주차 차량과 공유하고,
   * 5대뿐이라 인스턴싱 없이 Group 으로 둔다. 픽킹 목록에 넣지 않아 클릭에는 반응하지 않는다.
   */
  private buildCruisers(spots: ParkingSceneLayout["spots"]): void {
    const materialA = new THREE.MeshLambertMaterial({ color: this.colors.cruiseA });
    const materialB = new THREE.MeshLambertMaterial({ color: this.colors.cruiseB });
    const cabinMaterial = new THREE.MeshLambertMaterial({ color: this.colors.glass });
    cruiseRoutes(spots).forEach((route, index) => {
      const group = new THREE.Group();
      group.add(
        new THREE.Mesh(this.bodyMesh.geometry, index % 2 === 0 ? materialA : materialB),
        new THREE.Mesh(this.cabinMesh.geometry, cabinMaterial),
      );
      const cruiser = { group, route, distance: route.startOffsetM };
      placeCruiser(cruiser);
      this.scene.add(group);
      this.cruisers.push(cruiser);
    });
  }

  /** 주행 한 프레임. prefers-reduced-motion 이면 호출하지 않아 배치만 남는다. */
  private stepCruisers(deltaSeconds: number): void {
    for (const cruiser of this.cruisers) {
      cruiser.distance += cruiser.route.speedMps * deltaSeconds;
      placeCruiser(cruiser);
    }
  }

  // ── 추천 자리 비콘(H20-8) ──────────────────────────────────────────────────
  /**
   * 추천 면 위에 순위 비콘(역원뿔 + 순위 숫자)을 세운다. 이전 비콘은 통째로 치운다.
   * 없는 면 번호는 조용히 건너뛴다(추천 목록은 도구 확정값이지만 배치도와 어긋날 수 있다).
   */
  setBeacons(beacons: readonly SpotBeacon[]): void {
    if (this.disposed) return;
    for (const beacon of this.beacons) {
      this.scene.remove(beacon.group);
      beacon.group.traverse(disposeObject);
    }
    this.beacons = [];

    for (const { spotNo, rank } of beacons) {
      const placement = this.placements.find((item) => item.no === spotNo);
      if (!placement) continue;
      const group = new THREE.Group();
      const cone = new THREE.Mesh(
        new THREE.ConeGeometry(BEACON_CONE_RADIUS_M, BEACON_CONE_HEIGHT_M, 16),
        new THREE.MeshLambertMaterial({ color: this.colors.beacon }),
      );
      cone.rotation.x = Math.PI; // 꼭짓점이 면을 가리키게 뒤집는다
      group.add(cone);
      const label = textSprite(String(rank), this.colors.label);
      label.position.y = BEACON_LABEL_GAP_M;
      group.add(label);
      group.position.set(placement.x, BEACON_BASE_Y, placement.z);
      this.scene.add(group);
      // 순위별 위상차 — 셋이 같은 박자로 출렁이면 하나처럼 보인다.
      this.beacons.push({ group, baseY: BEACON_BASE_Y, phase: rank * 0.9 });
    }
    // 루프가 꺼진 상태(reduced motion)에서도 비콘이 바로 보이게 한 프레임 그린다.
    if (!this.active) this.renderer.render(this.scene, this.camera);
  }

  /** 비콘 부유 한 프레임 — driving(모션 허용)일 때만 호출된다. */
  private stepBeacons(nowMs: number): void {
    for (const beacon of this.beacons) {
      beacon.group.position.y =
        beacon.baseY + Math.sin((nowMs / 1000) * Math.PI * 2 * BEACON_BOB_HZ + beacon.phase) * BEACON_BOB_M;
    }
  }

  // ── 갱신 ───────────────────────────────────────────────────────────────────
  /** 점유·선택·필터 반영. 면 색은 제자리 갱신, 차량은 인스턴스 배열을 다시 채운다. */
  update(state: SceneState): void {
    if (this.disposed) return;
    const color = new THREE.Color();
    state.tones.forEach((tone, index) => {
      this.spotMesh.setColorAt(index, color.set(this.colors[SPOT_TONE_COLOR[tone]]));
    });
    if (this.spotMesh.instanceColor) this.spotMesh.instanceColor.needsUpdate = true;

    const matrix = new THREE.Matrix4();
    const euler = new THREE.Euler();
    this.carSpotNos = state.cars.map((car) => car.no);
    state.cars.forEach((car, index) => {
      euler.set(0, car.rotY, 0);
      matrix.makeRotationFromEuler(euler);
      matrix.setPosition(car.x, 0, car.z);
      this.bodyMesh.setMatrixAt(index, matrix);
      this.cabinMesh.setMatrixAt(index, matrix);
      this.bodyMesh.setColorAt(index, color.set(this.colors[CAR_TONE_COLOR[car.tone]]));
    });
    this.bodyMesh.count = state.cars.length;
    this.cabinMesh.count = state.cars.length;
    this.bodyMesh.instanceMatrix.needsUpdate = true;
    this.cabinMesh.instanceMatrix.needsUpdate = true;
    if (this.bodyMesh.instanceColor) this.bodyMesh.instanceColor.needsUpdate = true;
    // 인스턴스 경계구는 count=0 이던 첫 렌더 값이 그대로 남는다 — 다시 계산하지 않으면 카메라가
    // 원점에서 멀어질 때 차량 전체가 프러스텀 컬링으로 사라지고 픽킹도 빗나간다.
    this.bodyMesh.computeBoundingSphere();
    this.cabinMesh.computeBoundingSphere();
  }

  // ── 카메라 ─────────────────────────────────────────────────────────────────
  /** 전체 부감으로 이동('전체 보기' 버튼). instant 면 트윈 없이 즉시. */
  flyOverview(instant: boolean): void {
    this.flyTo(overviewShot(this.size), instant ? 0 : FLY_MS);
  }

  /** 선택한 면 클로즈업. 없는 면 번호는 무시한다. */
  flyToSpot(spotNo: string, instant: boolean): void {
    const placement = this.placements.find((item) => item.no === spotNo);
    if (!placement) return;
    this.flyTo(spotShot(placement), instant ? 0 : FLY_MS);
  }

  private flyTo(shot: CameraShot, duration: number): void {
    if (duration <= 0) {
      this.tween = null;
      this.applyShot(shot);
      return;
    }
    this.tween = {
      start: performance.now(),
      dur: duration,
      fromPosition: this.camera.position.clone(),
      toPosition: new THREE.Vector3(shot.position.x, shot.position.y, shot.position.z),
      fromTarget: this.controls.target.clone(),
      toTarget: new THREE.Vector3(shot.target.x, shot.target.y, shot.target.z),
    };
  }

  private applyShot(shot: CameraShot): void {
    this.camera.position.set(shot.position.x, shot.position.y, shot.position.z);
    this.controls.target.set(shot.target.x, shot.target.y, shot.target.z);
    this.controls.update();
  }

  private stepTween(now: number): void {
    const tween = this.tween;
    if (!tween) return;
    const progress = Math.min(1, (now - tween.start) / tween.dur);
    const eased = easeInOutCubic(progress);
    this.camera.position.lerpVectors(tween.fromPosition, tween.toPosition, eased);
    this.controls.target.lerpVectors(tween.fromTarget, tween.toTarget, eased);
    if (progress >= 1) this.tween = null;
  }

  // ── 루프·리사이즈·픽킹 ─────────────────────────────────────────────────────
  /** 렌더 루프 on/off — 탭 숨김·뷰 전환 시 끈다(GPU 절전). */
  setActive(active: boolean): void {
    if (this.disposed || active === this.active) return;
    this.active = active;
    if (!active) {
      if (this.frameId !== null) cancelAnimationFrame(this.frameId);
      this.frameId = null;
      return;
    }
    this.lastFrameMs = performance.now(); // 멈춰 있던 시간만큼 차가 순간이동하지 않게
    this.frameId = requestAnimationFrame(this.animate);
  }

  private readonly animate = (now: number): void => {
    if (!this.active || this.disposed) return;
    this.frameId = requestAnimationFrame(this.animate);
    const deltaSeconds = Math.min(MAX_FRAME_S, (now - this.lastFrameMs) / 1000 || 0);
    this.lastFrameMs = now;
    if (this.driving) {
      this.stepCruisers(deltaSeconds);
      this.stepBeacons(now);
    }
    this.stepTween(now);
    // 트윈 중에는 트윈이 카메라를 소유한다(controls.update 와 싸우면 카메라가 튄다).
    if (!this.tween) this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  private resize(): void {
    const width = this.container.clientWidth;
    const height = this.container.clientHeight;
    if (this.disposed || !width || !height) return;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
    // 루프가 꺼진 상태에서 크기만 바뀌어도 화면이 남지 않게 한 프레임 그린다.
    if (!this.active) this.renderer.render(this.scene, this.camera);
  }

  private readonly handlePointerDown = (event: PointerEvent): void => {
    this.pointerStart = { x: event.clientX, y: event.clientY, at: performance.now() };
  };

  /** 짧게 누른 클릭만 선택으로 본다 — 길게 끈 것은 카메라 회전이다. */
  private readonly handlePointerUp = (event: PointerEvent): void => {
    const moved = Math.hypot(
      event.clientX - this.pointerStart.x,
      event.clientY - this.pointerStart.y,
    );
    if (moved > CLICK_MOVE_PX || performance.now() - this.pointerStart.at > CLICK_MS) return;
    const spotNo = this.pick(event);
    if (spotNo) this.onSpotClick(spotNo);
  };

  private pick(event: PointerEvent): string | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(pointer, this.camera);
    const [hit] = raycaster.intersectObjects([this.bodyMesh, this.spotMesh]);
    if (hit?.instanceId === undefined) return null;
    return hit.object === this.spotMesh
      ? (this.placements[hit.instanceId]?.no ?? null)
      : (this.carSpotNos[hit.instanceId] ?? null);
  }

  // ── 정리 ───────────────────────────────────────────────────────────────────
  /** WebGL 컨텍스트는 브라우저당 개수 제한이 있다 — 2D/3D 토글마다 확실히 반납한다. */
  dispose(): void {
    if (this.disposed) return;
    this.setActive(false);
    this.disposed = true;
    this.resizeObserver.disconnect();
    this.renderer.domElement.removeEventListener("pointerdown", this.handlePointerDown);
    this.renderer.domElement.removeEventListener("pointerup", this.handlePointerUp);
    this.controls.dispose();
    this.scene.traverse(disposeObject);
    this.scene.clear();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.renderer.domElement.remove();
  }
}

/** 주행 차량을 경로 위 현재 거리 지점에 놓는다(진행 방향으로 회전). */
function placeCruiser(cruiser: { group: THREE.Group; route: CruiseRoute; distance: number }): void {
  const at = pointAlongPath(cruiser.route.path, cruiser.distance);
  cruiser.group.position.set(at.x, 0, at.z);
  cruiser.group.rotation.y = at.rotY;
}

/** 지오메트리·머티리얼·텍스처 반납. 스프라이트 지오메트리는 three 가 전역 공유하므로 건드리지 않는다. */
function disposeObject(object: THREE.Object3D): void {
  if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
    object.geometry.dispose();
  }
  const material = (object as Partial<THREE.Mesh>).material;
  const materials = Array.isArray(material) ? material : material ? [material] : [];
  for (const item of materials) {
    if (item instanceof THREE.SpriteMaterial) item.map?.dispose();
    item.dispose();
  }
}
