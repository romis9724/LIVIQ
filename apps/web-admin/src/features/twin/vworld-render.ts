/**
 * 실사 3D(VWorld) 순수 기하 헬퍼 — 단지 중심·쉘 확장 계산(H9-3b, ADR-0019 개정).
 *
 * VWorld/Cesium 렌더는 iframe(vworld-iframe.ts) 안에서 수행한다(페이지 로드 후 동적 로드로는
 * VWorld 가 이어서 document.write 하는 Cesium 엔진이 안 뜨는 실측 이슈 회피). 여기는 부모(React)가
 * iframe 에 넘길 center 를 계산하는 순수 함수만 둔다(테스트 대상, WebGL 무관).
 *
 * scaleCoords 는 srcdoc 쉘 압출 로직의 표준본이다 — srcdoc 은 TS import 가 불가해
 * vworld-iframe.ts 안에 동일 계산을 인라인 복제했다. 값이 바뀌면 양쪽을 함께 고친다.
 */

import type { TwinGeometryItem } from "@/lib/api";

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
