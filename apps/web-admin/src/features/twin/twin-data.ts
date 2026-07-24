/**
 * 단지 트윈 순수 로직 — occupancy 색 스케일·bounds·초기 뷰 상태·범례. (H9-1)
 * 렌더·WebGL과 무관한 계산만 담는다(테스트 대상). deck.gl 렌더는 TwinDeck.
 */

import type { TwinGeometryItem } from "@/lib/api";

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

/** 세대원 수 → 폴리곤 채움 색. 0=공실 회색 · 1~2인 옅은 블루 · 3인+ 진한 블루. */
export function occupancyColor(count: number): Rgb {
  if (count <= 0) return OCCUPANCY_COLORS.vacant;
  if (count <= 2) return OCCUPANCY_COLORS.low;
  return OCCUPANCY_COLORS.high;
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
