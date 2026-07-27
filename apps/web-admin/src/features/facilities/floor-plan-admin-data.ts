// 평면도 편집기(H13-4) 순수 로직 — %↔픽셀 변환·카테고리색·목록 헬퍼. UI·네트워크 의존 없음(테스트 대상).
// web-resident/features/floor-plan/floor-plan-data.ts 와 카테고리 개념은 같지만, 앱은 leaf라
// 서로 import하지 않는다(각 CLAUDE.md 규칙) — 그래서 여기 별도로 둔다.

export type DeviceCategory = "electric" | "network" | "water_heat" | "safety" | "other";

const DEVICE_CATEGORY_MAP: Record<string, DeviceCategory> = {
  콘센트: "electric",
  분전함: "electric",
  "조명 스위치": "electric",
  통신단자함: "network",
  TV: "network",
  "인터넷 단자": "network",
  월패드: "network",
  가스밸브: "water_heat",
  "수도 차단밸브": "water_heat",
  보일러: "water_heat",
  "난방 분배기": "water_heat",
  온도조절기: "water_heat",
  "에어컨 배관": "water_heat",
  소화기: "safety",
  화재감지기: "safety",
  경량칸막이: "safety",
};

/** device_type → 카테고리. 미지 타입은 '기타'. */
export function deviceCategory(deviceType: string): DeviceCategory {
  return DEVICE_CATEGORY_MAP[deviceType] ?? "other";
}

// 카테고리 → 마커 색(CSS 변수명, 토큰만 — 하드코딩 금지). 값은 resident 평면도 뷰의 배색과 맞춘다.
const CATEGORY_COLOR_VAR: Record<DeviceCategory, string> = {
  electric: "--color-warning",
  network: "--color-accent",
  water_heat: "--color-success",
  safety: "--color-danger",
  other: "--color-text-muted",
};

/** 카테고리 → 마커 배경색 CSS 변수명(`var()` 없이 변수명만 — 소비 측이 감싼다). */
export function categoryColorVar(category: DeviceCategory): string {
  return CATEGORY_COLOR_VAR[category];
}

/** 원본 픽셀 좌표 → 컨테이너 대비 %. total<=0 은 방어적으로 0. */
export function toPercent(value: number, total: number): number {
  if (total <= 0) return 0;
  return (value / total) * 100;
}

/** 컨테이너 대비 % → 원본 픽셀 좌표(반올림). total<=0 은 방어적으로 0. */
export function toPixel(percent: number, total: number): number {
  if (total <= 0) return 0;
  return Math.round((percent / 100) * total);
}

/**
 * 도면 클릭 좌표(캔버스 컨테이너 기준 px) → 원본 이미지 픽셀 좌표.
 * 컨테이너 크기<=0 은 방어적으로 {0,0}(클릭 위치를 알 수 없을 때 좌상단으로 몰지 않기 위한 안전값).
 */
export function pixelFromClick(
  clickX: number,
  clickY: number,
  containerWidth: number,
  containerHeight: number,
  imageWidth: number,
  imageHeight: number,
): { x: number; y: number } {
  if (containerWidth <= 0 || containerHeight <= 0) return { x: 0, y: 0 };
  return {
    x: toPixel((clickX / containerWidth) * 100, imageWidth),
    y: toPixel((clickY / containerHeight) * 100, imageHeight),
  };
}

export const DIR_OPTIONS: readonly { value: string; label: string }[] = [
  { value: "", label: "없음" },
  { value: "up", label: "위" },
  { value: "down", label: "아래" },
  { value: "left", label: "왼쪽" },
  { value: "right", label: "오른쪽" },
];

/** 공백 아닌 고유 값(가나다 정렬) — device_type·room 입력의 datalist 후보. */
export function distinctNonEmpty(values: readonly (string | null | undefined)[]): string[] {
  const set = new Set<string>();
  for (const value of values) {
    if (value && value.trim()) set.add(value.trim());
  }
  return [...set].sort((a, b) => a.localeCompare(b, "ko"));
}

/** 마커 라벨/툴팁 텍스트 — "{room} {device_type}"(+" — {label}" 있으면). room 없으면 종류만. */
export function markerLabel(device: {
  room: string | null;
  deviceType: string;
  label: string | null;
}): string {
  const base = device.room ? `${device.room} ${device.deviceType}` : device.deviceType;
  return device.label ? `${base} — ${device.label}` : base;
}

/**
 * 트윈 세대 상세의 unitTypeLabel("84M(공공임대)") → 평면도 unit_type_name 매칭 키("84M").
 * 괄호 앞부분만 취하고 트림. 괄호가 없으면 원문 트림. 빈 값·공백만 남으면 null.
 */
export function normalizeUnitType(label: string | null): string | null {
  if (!label) return null;
  const parenIndex = label.indexOf("(");
  const base = parenIndex >= 0 ? label.slice(0, parenIndex) : label;
  const trimmed = base.trim();
  return trimmed || null;
}
