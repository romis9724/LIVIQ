// 입주민 주차맵 — apps/api HTTP 클라이언트. GET /parking/map (H17-2).
// 서버가 주는 건 배치도·점유 면 번호·본인 세대 차량 위치뿐이다 — 타 세대 차량번호·동호수는
// 응답 스키마에 아예 없다(규칙 2). 403=권한 없음, layout null=배치도 미적재(빈 상태).

import type { ParkingMapLayout, ParkingMapSpot } from "@liviq/ui";
import { API_BASE_URL, DEV_HEADERS, apiFetch } from "@/lib/dev-context";

/** 본인 세대 차량 1대의 주차 위치. */
export interface MyParkedVehicle {
  spotNo: string;
  entryAt: string | null; // ISO8601
}

export interface ParkingMapData {
  layout: ParkingMapLayout | null;
  occupiedSpotNos: string[];
  myVehicles: MyParkedVehicle[];
}

/** 상태코드를 담은 에러 — 화면 분기용(fees/api 와 동일 계약). */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function ensureOk(response: Response): Promise<void> {
  if (response.ok) return;
  let detail = `요청 실패 (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") detail = body.detail;
  } catch {
    // 본문 파싱 실패는 무시 — 상태코드 기반 기본 메시지 유지
  }
  throw new ApiError(response.status, detail);
}

interface RawBuilding {
  outline: number[][];
  cx: number;
  cy: number;
}

interface RawLayout {
  viewBox: string;
  buildings?: Record<string, RawBuilding>;
  boxes?: { label: string; x: number; y: number; w: number; h: number }[];
  spots?: { no: string; kind: string; x: number; y: number; dir: string }[];
}

/** buildings 는 동명 키 맵 — 렌더 순서를 고정하려고 동명 정렬 배열로 바꾼다(관리자와 동일). */
function toLayout(raw: RawLayout): ParkingMapLayout {
  return {
    viewBox: raw.viewBox,
    buildings: Object.entries(raw.buildings ?? {})
      .map(([name, b]) => ({ name, outline: b.outline, cx: b.cx, cy: b.cy }))
      .sort((a, b) => a.name.localeCompare(b.name, "ko")),
    boxes: raw.boxes ?? [],
    spots: (raw.spots ?? []).map(
      (s): ParkingMapSpot => ({
        no: s.no,
        kind: s.kind,
        x: s.x,
        y: s.y,
        // 배치도는 서버가 해석하지 않고 통과시키는 JSONB — 알 수 없는 방향은 down 으로 접는다.
        dir: s.dir === "up" ? "up" : "down",
      }),
    ),
  };
}

export async function getParkingMap(): Promise<ParkingMapData> {
  const response = await apiFetch(`${API_BASE_URL}/parking/map`, { headers: DEV_HEADERS });
  await ensureOk(response);
  const body = await response.json();
  return {
    layout: body.layout ? toLayout(body.layout as RawLayout) : null,
    occupiedSpotNos: (body.occupied_spot_nos as string[]) ?? [],
    myVehicles: ((body.my_vehicles as { spot_no: string; entry_at: string | null }[]) ?? []).map(
      (v) => ({ spotNo: v.spot_no, entryAt: v.entry_at ?? null }),
    ),
  };
}
