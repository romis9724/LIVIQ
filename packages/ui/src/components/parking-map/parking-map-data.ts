/**
 * 주차 배치도 순수 로직 — 축척 상수·viewBox 파싱·경과시간 포맷. (H17-2, admin ParkingMap 승격)
 *
 * 렌더·네트워크와 무관해 여기 모은다. 관리자 2D·3D 뷰와 입주민 주차맵이 **같은 상수**를
 * 써야 좌표가 맞으므로 값을 앱에 복제하지 않는다(admin parking-sim 은 이 모듈을 re-export).
 */

// 배치도 축척 — 면 1개 34x64px = 2.5m x 5.0m (13px/m). 프로토타입 좌표계와 동일해야 한다.
export const SPOT_W = 34;
export const SPOT_H = 64;

/**
 * "0 0 3020 1082" → [minX, minY, width, height]. 파싱 실패는 0 으로 둔다(2D·3D 공용).
 * 빈 문자열·비숫자는 NaN 이 되는데, 그대로 흘리면 SVG 좌표가 통째로 깨지므로 여기서 접는다.
 */
export function parseViewBox(viewBox: string): [number, number, number, number] {
  const parts = viewBox
    .trim()
    .split(/[\s,]+/)
    .map((v) => Number.parseFloat(v));
  const at = (i: number): number => (Number.isFinite(parts[i]) ? (parts[i] as number) : 0);
  return [at(0), at(1), at(2), at(3)];
}

/** 주차 경과 시간 — "3시간 20분" / "20분". 미래 입차(음수)는 "0분". */
export function elapsedText(entryMs: number, nowMs: number): string {
  const minutes = Math.max(0, Math.floor((nowMs - entryMs) / 60000));
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours > 0 ? `${hours}시간 ${rest}분` : `${rest}분`;
}
