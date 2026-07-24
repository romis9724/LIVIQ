/**
 * 단지 트윈 순수 로직 — occupancy 색 스케일·bounds·초기 뷰 상태·범례. (H9-1)
 * 렌더·WebGL과 무관한 계산만 담는다(테스트 대상). deck.gl 렌더는 TwinDeck.
 */

import type { TwinGeometryItem } from "@/lib/api";
import { formatWon } from "@/features/fee-upload/logic";

// deck.gl fill 은 [r,g,b] 0-255 배열이라 CSS 토큰 변수를 직접 못 쓴다(WebGL).
// 아래 RGB 상수는 tokens.css semantic 의도의 근사값이다(설계 예외 — docs/05 §5).
//   VACANT ≈ --color-text-muted (중립 회색)      · 공실(세대원 0)
//   LOW    ≈ --color-accent 옅은 톤               · 1~2인
//   HIGH   ≈ --color-accent 진한 톤               · 3인 이상
// DOM 크롬(범례·패널)은 전부 토큰/컴포넌트를 쓰고, 이 상수는 캔버스 fill·범례 스와치에만 쓴다.
export type Rgb = [number, number, number];

export const OCCUPANCY_COLORS: { vacant: Rgb; low: Rgb; high: Rgb } = {
  vacant: [148, 155, 173], // 중립 회색 (--color-text-muted 근사)
  low: [147, 178, 232], // 옅은 블루 (--color-accent 근사)
  high: [46, 96, 196], // 진한 블루 (--color-accent 근사)
};

// 오버레이 공통 semantic 색 — tokens.css 의도의 RGB 근사(위와 동일한 WebGL fill 예외).
//   NEUTRAL ≈ --color-text-muted · ACCENT ≈ --color-accent · SUCCESS ≈ --color-success
//   CHECK   ≈ --color-warning 옅은 톤 · WARNING ≈ --color-warning · FAULT ≈ warning~danger 사이
//   DANGER  ≈ --color-danger
const SEMANTIC: {
  neutral: Rgb;
  accent: Rgb;
  success: Rgb;
  check: Rgb;
  warning: Rgb;
  fault: Rgb;
  danger: Rgb;
} = {
  neutral: OCCUPANCY_COLORS.vacant, // 중립 회색(공실 톤과 동일)
  accent: OCCUPANCY_COLORS.high, // 진한 블루
  success: [64, 168, 100], // 초록 (--color-success 근사)
  check: [224, 200, 110], // 옅은 노랑 (--color-warning 옅은 톤)
  warning: [232, 168, 92], // 옅은 주황 (--color-warning 근사)
  fault: [220, 124, 52], // 주황 (warning~danger 사이)
  danger: [210, 68, 70], // 빨강 (--color-danger 근사)
};

/** 세대원 수 → 폴리곤 채움 색. 0=공실 회색 · 1~2인 옅은 블루 · 3인+ 진한 블루. */
export function occupancyColor(count: number): Rgb {
  if (count <= 0) return OCCUPANCY_COLORS.vacant;
  if (count <= 2) return OCCUPANCY_COLORS.low;
  return OCCUPANCY_COLORS.high;
}

export type OverlayKind = "occupancy" | "inquiries" | "fees" | "facilities";

/** 세그먼트·범례·상세에서 함께 쓰는 오버레이 순서·라벨. */
export const OVERLAY_KINDS: readonly OverlayKind[] = [
  "occupancy",
  "inquiries",
  "fees",
  "facilities",
];
export const OVERLAY_LABELS: Record<OverlayKind, string> = {
  occupancy: "입주",
  inquiries: "민원",
  fees: "관리비",
  facilities: "설비",
};

// 설비 severity(0~3) → 상태 라벨. undefined/0=정상, 그 이상은 최악값을 취해 붉게.
const FACILITY_SEVERITY_LABELS: readonly string[] = ["정상", "점검 필요", "고장", "위험"];
function facilitySeverityLabel(value: number | undefined): string {
  if (value === undefined || value <= 0) return FACILITY_SEVERITY_LABELS[0]!;
  const idx = Math.min(Math.floor(value), FACILITY_SEVERITY_LABELS.length - 1);
  return FACILITY_SEVERITY_LABELS[idx]!;
}

/**
 * 오버레이 값 → 폴리곤 채움 색. value undefined(맵에 없는 세대)는 각 kind의 무이슈/중립 색.
 * WebGL fill 예외 — SEMANTIC 상수는 tokens.css 의도의 RGB 근사(파일 상단 주석).
 */
export function colorForOverlay(kind: OverlayKind, value: number | undefined): Rgb {
  switch (kind) {
    case "occupancy":
      return occupancyColor(value ?? 0); // undefined=공실(0)
    case "inquiries":
      if (value === undefined || value <= 0) return SEMANTIC.neutral;
      return value <= 2 ? SEMANTIC.warning : SEMANTIC.danger;
    case "fees":
      // H8-7 균등분배라 전 세대 값이 동일 → 부과(accent)/미부과(중립) 2단으로만 렌더된다.
      // 세대별 차등 항목이 분리되면 여기서 금액 밴드(옅은→진한 accent)로 확장한다.
      return value === undefined ? SEMANTIC.neutral : SEMANTIC.accent;
    case "facilities":
      if (value === undefined || value <= 0) return SEMANTIC.success;
      if (value <= 1) return SEMANTIC.check;
      if (value <= 2) return SEMANTIC.fault;
      return SEMANTIC.danger;
  }
}

/** hover tooltip 등에서 쓰는 값 라벨 — 각 kind의 값 의미를 사람이 읽는 문구로. */
export function overlayValueText(kind: OverlayKind, value: number | undefined): string {
  switch (kind) {
    case "occupancy":
      return `세대원 ${value ?? 0}명`;
    case "inquiries":
      return `미종결 ${value ?? 0}건`;
    case "fees":
      return value === undefined ? "부과 내역 없음" : formatWon(value);
    case "facilities":
      return facilitySeverityLabel(value);
  }
}

export interface LegendEntry {
  label: string;
  color: Rgb;
}

// 색만으로 상태 전달 금지(docs/05 §6) — 범례는 색+텍스트 병기.
export const OCCUPANCY_LEGEND: readonly LegendEntry[] = [
  { label: "공실", color: OCCUPANCY_COLORS.vacant },
  { label: "1~2인", color: OCCUPANCY_COLORS.low },
  { label: "3인 이상", color: OCCUPANCY_COLORS.high },
];

const INQUIRIES_LEGEND: readonly LegendEntry[] = [
  { label: "미종결 없음", color: SEMANTIC.neutral },
  { label: "1~2건", color: SEMANTIC.warning },
  { label: "3건 이상", color: SEMANTIC.danger },
];

const FEES_LEGEND: readonly LegendEntry[] = [
  { label: "미부과", color: SEMANTIC.neutral },
  { label: "부과됨", color: SEMANTIC.accent },
];

const FACILITIES_LEGEND: readonly LegendEntry[] = [
  { label: "정상", color: SEMANTIC.success },
  { label: "점검 필요", color: SEMANTIC.check },
  { label: "고장", color: SEMANTIC.fault },
  { label: "위험", color: SEMANTIC.danger },
];

/** kind별 범례(색+텍스트). 색 단독 전달 금지 — 항상 라벨을 병기한다. */
export function legendForOverlay(kind: OverlayKind): readonly LegendEntry[] {
  switch (kind) {
    case "occupancy":
      return OCCUPANCY_LEGEND;
    case "inquiries":
      return INQUIRIES_LEGEND;
    case "fees":
      return FEES_LEGEND;
    case "facilities":
      return FACILITIES_LEGEND;
  }
}

/** RGB 상수 → CSS 문자열(범례 스와치용 인라인 스타일). */
export function rgbCss([r, g, b]: Rgb): string {
  return `rgb(${r} ${g} ${b})`;
}

export interface Bounds {
  minLng: number;
  minLat: number;
  maxLng: number;
  maxLat: number;
}

/** 전 세대 폴리곤(2D 정점)의 경위도 bounds. 정점이 하나도 없으면 null. */
export function computeBounds(items: readonly TwinGeometryItem[]): Bounds | null {
  let minLng = Infinity;
  let minLat = Infinity;
  let maxLng = -Infinity;
  let maxLat = -Infinity;
  for (const item of items) {
    for (const vertex of item.polygon2d) {
      const lng = vertex[0];
      const lat = vertex[1];
      if (lng === undefined || lat === undefined) continue;
      if (lng < minLng) minLng = lng;
      if (lat < minLat) minLat = lat;
      if (lng > maxLng) maxLng = lng;
      if (lat > maxLat) maxLat = lat;
    }
  }
  if (!Number.isFinite(minLng) || !Number.isFinite(minLat)) return null;
  return { minLng, minLat, maxLng, maxLat };
}

export interface ViewState {
  longitude: number;
  latitude: number;
  zoom: number;
}

// 웹메르카토르 세계 폭(deck.gl 타일 512px 기준) — bounds → zoom 근사에 사용.
const TILE_SIZE = 512;
const ZOOM_MIN = 1;
const ZOOM_MAX = 20;
const DEGENERATE_ZOOM = 18; // 단일 세대 등 span≈0일 때 기본 확대율
const FIT_PADDING = 1.25; // bounds 를 여유 있게 담기 위한 span 확대 배수

/**
 * bounds → 초기 뷰 상태(중심 + zoom). zoom 은 경위도 span 을 뷰포트 폭에 맞추는 메르카토르 근사.
 * ponytail: 뷰포트 실측 없이 기준 폭(viewportWidth)으로 계산하는 근사 — 단지 규모엔 충분,
 *           정밀 fit 이 필요하면 렌더 후 deck WebMercatorViewport.fitBounds 로 교체.
 */
export function boundsToViewState(bounds: Bounds, viewportWidth = 900): ViewState {
  const longitude = (bounds.minLng + bounds.maxLng) / 2;
  const latitude = (bounds.minLat + bounds.maxLat) / 2;
  // 위도는 메르카토르에서 압축되므로 cos(lat) 로 보정해 경도 span 과 같은 축척으로 비교한다.
  const lngSpan = (bounds.maxLng - bounds.minLng) * FIT_PADDING;
  const latSpan = ((bounds.maxLat - bounds.minLat) / Math.cos((latitude * Math.PI) / 180)) * FIT_PADDING;
  const span = Math.max(lngSpan, latSpan);
  if (span <= 0) return { longitude, latitude, zoom: DEGENERATE_ZOOM };
  const zoom = Math.log2((viewportWidth * 360) / (TILE_SIZE * span));
  return { longitude, latitude, zoom: clamp(zoom, ZOOM_MIN, ZOOM_MAX) };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
