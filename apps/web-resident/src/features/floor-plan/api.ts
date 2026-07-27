// 우리집 평면도 — apps/api HTTP 클라이언트. GET /me/floor-plan (docs/05 평면도 절, FR-PLAN-01).
// 본인 세대 한정(서버 세션으로 결정) — 404 = 평면도 없음(세대 없음·매칭 실패 포함).

import { API_BASE_URL, DEV_HEADERS, apiFetch } from "@/lib/dev-context";

export interface FloorPlan {
  id: string;
  imageUrl: string; // 서명 URL
  imageWidth: number;
  imageHeight: number;
  unitTypeName: string | null;
}

export interface FloorPlanDevice {
  id: string;
  deviceType: string;
  x: number; // 원본 이미지 픽셀 좌표
  y: number;
  room: string | null;
  dir: string | null;
  label: string | null;
  memo: string | null;
  facilityId: string | null;
}

export interface FloorPlanData {
  plan: FloorPlan;
  devices: FloorPlanDevice[];
}

// api FloorPlanDeviceOut(snake_case) → FloorPlanDevice(camelCase).
interface RawPlan {
  id: string;
  image_url: string;
  image_width: number;
  image_height: number;
  unit_type_name: string | null;
}

interface RawDevice {
  id: string;
  device_type: string;
  x: number;
  y: number;
  room: string | null;
  dir: string | null;
  label: string | null;
  memo: string | null;
  facility_id: string | null;
}

function toDevice(raw: RawDevice): FloorPlanDevice {
  return {
    id: raw.id,
    deviceType: raw.device_type,
    x: raw.x,
    y: raw.y,
    room: raw.room,
    dir: raw.dir,
    label: raw.label,
    memo: raw.memo,
    facilityId: raw.facility_id,
  };
}

/** 본인 세대 평면도 + 시설 마커. 404(평면도 없음·세대 없음·매칭 실패 포함)는 null. */
export async function getMyFloorPlan(): Promise<FloorPlanData | null> {
  const response = await apiFetch(`${API_BASE_URL}/me/floor-plan`, { headers: DEV_HEADERS });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`평면도 조회 실패 (${response.status})`);
  const body = await response.json();
  const plan = body.plan as RawPlan;
  return {
    plan: {
      id: plan.id,
      imageUrl: plan.image_url,
      imageWidth: plan.image_width,
      imageHeight: plan.image_height,
      unitTypeName: plan.unit_type_name ?? null,
    },
    devices: (body.devices as RawDevice[]).map(toDevice),
  };
}
