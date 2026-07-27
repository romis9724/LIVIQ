// 평면도 순수 로직 — 카테고리 매핑·좌표 변환·표 그룹핑. UI·네트워크 의존 없음(테스트 대상).

import type { FloorPlanDevice } from "./api";

export type DeviceCategory = "electric" | "network" | "water_heat" | "safety" | "other";
/** 카테고리 칩 + '방 이름' 토글(room 은 마커가 아니라 별도 표기). */
export type FilterKey = DeviceCategory | "room";

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

export const CATEGORY_ORDER: readonly FilterKey[] = [
  "electric",
  "network",
  "water_heat",
  "safety",
  "other",
  "room",
];

export const FILTER_LABEL: Record<FilterKey, string> = {
  electric: "전기",
  network: "통신",
  water_heat: "급수·난방",
  safety: "안전",
  other: "기타",
  room: "방 이름",
};

/** 원본 픽셀 좌표 → 컨테이너 대비 %. total<=0 은 방어적으로 0. */
export function toPercent(value: number, total: number): number {
  if (total <= 0) return 0;
  return (value / total) * 100;
}

const DIR_ROTATION: Record<string, number> = {
  up: 0,
  n: 0,
  right: 90,
  e: 90,
  down: 180,
  s: 180,
  left: 270,
  w: 270,
  ne: 45,
  se: 135,
  sw: 225,
  nw: 315,
};

/** dir → CSS 회전 각도(deg). 알려진 8방위 외엔 숫자(도)로 해석 시도, 실패 시 null(화살표 미표시). */
export function dirRotation(dir: string | null): number | null {
  if (!dir) return null;
  const key = dir.trim().toLowerCase();
  const known = DIR_ROTATION[key];
  if (known !== undefined) return known;
  const num = Number(key);
  return Number.isFinite(num) ? num : null;
}

/** 마커 button aria-label: "{room} {device_type}"(방 없으면 종류만). */
export function ariaLabel(device: Pick<FloorPlanDevice, "room" | "deviceType">): string {
  return device.room ? `${device.room} ${device.deviceType}` : device.deviceType;
}

export interface DeviceRow {
  room: string;
  type: string;
  note: string;
}

/** 접근성 대체 표(방·종류·비고). room 라벨 행은 마커가 아니므로 제외. */
export function tableRows(devices: readonly FloorPlanDevice[]): DeviceRow[] {
  return devices
    .filter((d) => d.deviceType !== "room")
    .map((d) => ({
      room: d.room ?? "-",
      type: d.label ? `${d.deviceType}(${d.label})` : d.deviceType,
      note: d.memo ?? "-",
    }));
}
