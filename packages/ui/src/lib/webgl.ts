/** WebGL 지원 여부 — 미지원이면 캔버스 대신 대체 UI를 띄운다(클라이언트 전용). */
export function isWebglSupported(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return Boolean(canvas.getContext("webgl2") ?? canvas.getContext("webgl"));
  } catch {
    return false;
  }
}
