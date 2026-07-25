/**
 * 실사 3D(VWorld/Cesium) iframe 문서 생성 — H9-3b(ADR-0019 개정).
 *
 * VWorld SDK 는 키 검증 후 document.write 로 실제 Cesium 엔진 스크립트를 추가 주입한다.
 * 페이지 로드 후 동적 <script> append 로는 document.write 가 무시돼 vw/ws3d/Cesium 전역이
 * 안 생긴다(실측). 그래서 프로토타입(dashboard_vworld.html)처럼 문서 파싱 중 head 에서
 * 로드해야 하는데, 이를 위해 렌더 로직만 발췌한 자립 HTML 을 iframe srcdoc 으로 띄운다.
 *
 * 역할 분리: 색 계산·범례·상세는 부모(React)가 담당하고, 이 iframe 은 순수 렌더만 한다.
 * 부모는 세대별 rgb 를 계산해 postMessage 로 넘기므로 iframe 은 twin-data(TS) import 불필요.
 *
 * postMessage 계약:
 *   부모 → iframe : { type:'init', center:[lon,lat], units:[{householdId,polygon2d,baseZ,floorHeight,rgb:[r,g,b]}] }
 *                   { type:'recolor', colors:{ [householdId]:[r,g,b] } }
 *   iframe → 부모 : { type:'ready' } · { type:'error', message } · { type:'select', householdId }
 *
 * 개인정보 미전송(규칙 2): units 는 좌표·색·householdId(uuid)뿐. 실명 등은 부모 상세 패널이 마스킹 조회.
 * srcdoc 은 순수 JS 문자열이라 TS 모듈을 import 할 수 없다 — scaleCoords 압출 수학은
 * vworld-render.ts(테스트본)의 인라인 복제다(값 변경 시 양쪽 동기화).
 * TODO(CSP): web-admin CSP 도입 시 frame-src 'self' + iframe script-src 에 map.vworld.kr 허용 필요(docs/06).
 */

/** VWorld 실사 3D 를 렌더하는 자립 HTML 을 반환한다(iframe srcdoc 용). apiKey 는 도메인 잠금이라 인라인 무방. */
export function buildVWorldSrcdoc(apiKey: string): string {
  // 키는 문서 파싱 중 head 스크립트에 안전 삽입 — JSON.stringify 로 이스케이프.
  const keyLiteral = JSON.stringify(apiKey);
  return `<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<script>
(function () {
  var KEY = ${keyLiteral};
  if (KEY) {
    // 파싱 중 document.write — VWorld 가 이어서 주입하는 Cesium 엔진 스크립트가 정상 로드된다.
    document.write('<scr' + 'ipt src="https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=' + encodeURIComponent(KEY) + '"></scr' + 'ipt>');
  }
})();
</script>
<style>
  html, body { margin: 0; padding: 0; width: 100%; height: 100%; overflow: hidden; background: #0d0d1f; }
  #vmap { position: absolute; inset: 0; }
</style>
</head>
<body>
<div id="vmap"></div>
<script>
(function () {
  "use strict";
  var GROUND_HEIGHT_M = 25;   // 지반 고도(m) 상수 — 단지 규모엔 지형 샘플링 없이 충분
  var SHELL_ALPHA = 0.22;     // 실사 건물이 비치도록 낮은 틴트
  var SHELL_SCALE = 1.2;      // 실사 건물보다 살짝 키워 반투명 쉘이 감싸도록
  var POLL_MS = 300;
  var POLL_MAX = 100;         // 30초(300ms×100) 내 뷰어 준비 실패 → error

  var viewer = null;
  var primitive = null;
  var idSet = null;
  var units = [];
  var center = null;
  var started = false;
  var buildingTileset = null;   // VWorld 3D 건물 타일셋(map4) — 우리 단지 볼록껍질로 클리핑
  var poiTilesets = [];         // POI 타일셋 — 클립 시 숨김
  var clipOn = true;            // 기본 우리 단지만 표시(첫마을 4단지 외 건물 숨김)

  function post(msg) { parent.postMessage(msg, "*"); }

  // vworld-render.ts scaleCoords 의 인라인 복제 — 무게중심 기준 f배 확장(양쪽 동기화 필요).
  function scaleCoords(coords, f) {
    var sx = 0, sy = 0, i;
    for (i = 0; i < coords.length; i++) { sx += coords[i][0]; sy += coords[i][1]; }
    var cx = sx / coords.length, cy = sy / coords.length;
    var out = [];
    for (i = 0; i < coords.length; i++) {
      out.push([cx + (coords[i][0] - cx) * f, cy + (coords[i][1] - cy) * f]);
    }
    return out;
  }

  function rgba(rgb, a) { return new Cesium.Color(rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, a); }

  // 세대 shell 을 단일 Primitive(draw call 1)로 배치 — polygon2d 를 살짝 키워 압출, id=householdId.
  function buildShell() {
    var C = Cesium;
    var instances = units.map(function (u) {
      var flat = [], coords = scaleCoords(u.polygon2d, SHELL_SCALE), k;
      for (k = 0; k < coords.length; k++) { flat.push(coords[k][0], coords[k][1]); }
      var base = GROUND_HEIGHT_M + u.baseZ;
      return new C.GeometryInstance({
        geometry: new C.PolygonGeometry({
          polygonHierarchy: new C.PolygonHierarchy(C.Cartesian3.fromDegreesArray(flat)),
          height: base,
          extrudedHeight: base + u.floorHeight,
          vertexFormat: C.PerInstanceColorAppearance.FLAT_VERTEX_FORMAT
        }),
        attributes: { color: C.ColorGeometryInstanceAttribute.fromColor(rgba(u.rgb, SHELL_ALPHA)) },
        id: u.householdId
      });
    });
    primitive = viewer.scene.primitives.add(new C.Primitive({
      geometryInstances: instances,
      appearance: new C.PerInstanceColorAppearance({ flat: true, translucent: true, closed: false }),
      asynchronous: false
    }));
  }

  // 오버레이 변경 → per-instance 색 교체(기하 재생성 없음). 아직 컴파일 전이면 새 색으로 재생성.
  function recolor(colors) {
    if (!primitive) return;
    var C = Cesium, i, c, attrs;
    if (!primitive.ready) {
      for (i = 0; i < units.length; i++) { c = colors[units[i].householdId]; if (c) units[i].rgb = c; }
      viewer.scene.primitives.remove(primitive);
      buildShell();
      return;
    }
    for (i = 0; i < units.length; i++) {
      c = colors[units[i].householdId];
      if (!c) continue;
      units[i].rgb = c;
      attrs = primitive.getGeometryInstanceAttributes(units[i].householdId);
      if (attrs) attrs.color = C.ColorGeometryInstanceAttribute.toValue(rgba(c, SHELL_ALPHA), attrs.color);
    }
  }

  // 피킹 — drillPick 으로 실사 건물 뒤 shell 까지 관통, 클릭 householdId 를 부모로 전달.
  function attachPicking() {
    var C = Cesium;
    var handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
    function pick(pos) {
      var picks = viewer.scene.drillPick(pos, 8), i, p;
      for (i = 0; i < picks.length; i++) {
        p = picks[i];
        if (p && typeof p.id === "string" && idSet.has(p.id)) return p.id;
      }
      return null;
    }
    handler.setInputAction(function (m) {
      viewer.scene.canvas.style.cursor = pick(m.endPosition) ? "pointer" : "default";
    }, C.ScreenSpaceEventType.MOUSE_MOVE);
    handler.setInputAction(function (m) {
      var id = pick(m.position);
      if (id) post({ type: "select", householdId: id });
    }, C.ScreenSpaceEventType.LEFT_CLICK);
  }

  // 세대 외곽점 볼록껍질 — Andrew monotone chain, CCW 반환(프로토타입 그대로).
  function convexHull(pts) {
    var P = pts.slice().sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    function cross(o, a, b) { return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0]); }
    var lo = [], hi = [], i, p;
    for (i = 0; i < P.length; i++) { p = P[i]; while (lo.length >= 2 && cross(lo[lo.length-2], lo[lo.length-1], p) <= 0) lo.pop(); lo.push(p); }
    for (i = P.length-1; i >= 0; i--) { p = P[i]; while (hi.length >= 2 && cross(hi[hi.length-2], hi[hi.length-1], p) <= 0) hi.pop(); hi.push(p); }
    lo.pop(); hi.pop();
    return lo.concat(hi);
  }

  // 단지 볼록껍질을 수직 평면들로 만들어 ClippingPlaneCollection 생성(프로토타입 buildClipPlanes 수학 그대로).
  function buildClipPlanes() {
    var C = Cesium, pts = [], i, k, u;
    for (i = 0; i < units.length; i++) { u = units[i]; for (k = 0; k < u.polygon2d.length; k++) pts.push(u.polygon2d[k]); }
    var hull = convexHull(pts);
    var hx = 0, hy = 0;
    for (i = 0; i < hull.length; i++) { hx += hull[i][0]; hy += hull[i][1]; }
    hx /= hull.length; hy /= hull.length;
    hull = hull.map(function (p) { return [hx + (p[0]-hx)*1.03, hy + (p[1]-hy)*1.03]; });   // 가장자리 건물 안 잘리게 살짝만 바깥 버퍼

    var centerC = C.Cartesian3.fromDegrees(hx, hy, GROUND_HEIGHT_M);
    var enu = C.Transforms.eastNorthUpToFixedFrame(centerC);
    var inv = C.Matrix4.inverse(enu, new C.Matrix4());
    var local = hull.map(function (p) {
      var c = C.Cartesian3.fromDegrees(p[0], p[1], GROUND_HEIGHT_M);
      var l = C.Matrix4.multiplyByPoint(inv, c, new C.Cartesian3());
      return [l.x, l.y];   // east, north
    });

    var planes = [], N = local.length, a, b, nx, ny, mx, my, len, dist;
    for (i = 0; i < N; i++) {
      a = local[i]; b = local[(i+1) % N];
      nx = b[1] - a[1]; ny = -(b[0] - a[0]);            // edge 에 수직
      mx = (a[0]+b[0])/2; my = (a[1]+b[1])/2;
      if (nx*(-mx) + ny*(-my) < 0) { nx = -nx; ny = -ny; }  // 안쪽(원점) 향하도록
      len = Math.hypot(nx, ny); nx /= len; ny /= len;
      dist = -(nx*a[0] + ny*a[1]);
      planes.push(new C.ClippingPlane(new C.Cartesian3(nx, ny, 0), dist));
    }
    return new C.ClippingPlaneCollection({ planes: planes, modelMatrix: enu, unionClippingRegions: true, edgeWidth: 0 });
  }

  // 클립 on: 우리 단지만 표시 + 타일 경량화 + POI 숨김. off: 전체 복원.
  function applyClip(on) {
    clipOn = on;
    if (!buildingTileset) return;
    if (on) {
      if (!buildingTileset.clippingPlanes) buildingTileset.clippingPlanes = buildClipPlanes();
      else buildingTileset.clippingPlanes.enabled = true;
      buildingTileset.maximumScreenSpaceError = 24;   // 타일 덜 로드 → 가볍게
      poiTilesets.forEach(function (t) { t.show = false; });
    } else {
      if (buildingTileset.clippingPlanes) buildingTileset.clippingPlanes.enabled = false;
      buildingTileset.maximumScreenSpaceError = 16;
      poiTilesets.forEach(function (t) { t.show = true; });
    }
  }

  // scene.primitives 에서 건물 타일셋(map4)·POI 타일셋을 폴링으로 찾아 클립 적용(프로토타입 setupTilesets).
  // 건물·POI 타일셋은 비동기로 늦게 로드된다 — 건물을 찾아도 인터벌을 멈추지 않고 30초간 계속
  // 스캔해, 뒤늦게 올라오는 POI 타일셋까지 숨긴다(clipOn 시 우리 단지 외 라벨 잔존 방지).
  function setupTilesets() {
    var tries = 0, clipped = false;
    var iv = setInterval(function () {
      var prims = viewer.scene.primitives, i, pr, url;
      for (i = 0; i < prims.length; i++) {
        pr = prims.get(i);
        if (pr instanceof Cesium.Cesium3DTileset && pr.resource) {
          url = pr.resource.url || "";
          if (!buildingTileset && url.indexOf("map4") >= 0) buildingTileset = pr;
          if (url.indexOf("/poi/") >= 0 && poiTilesets.indexOf(pr) < 0) poiTilesets.push(pr);
        }
      }
      if (buildingTileset && !clipped) { applyClip(clipOn); clipped = true; }
      // 늦게 로드된 POI 도 계속 숨김(clipOn 시).
      if (clipped && clipOn) poiTilesets.forEach(function (t) { t.show = false; });
      if (++tries > 60) clearInterval(iv);   // 30초까지 스캔 후 종료
    }, 500);
  }

  // 조감도 initPosition 으로 맵 시작 후 뷰어 준비 폴링(프로토타입 startMap/waitViewer).
  function startMap() {
    if (typeof vw === "undefined" || !vw.Map) {
      post({ type: "error", message: "VWorld 지도를 불러오지 못했습니다. 인증키·서비스 URL 등록을 확인해 주세요." });
      return;
    }
    var cx = center[0], cy = center[1];
    var map = new vw.Map();
    map.setOption({
      mapId: "vmap",
      initPosition: new vw.CameraPosition(
        new vw.CoordZ(cx + 0.0018, cy - 0.0026, 260),   // 남동쪽 조감도 각도
        new vw.Direction(-28, -33, 0)
      ),
      logo: false,
      navigation: true
    });
    map.start();
    waitViewer(0);
  }

  function waitViewer(tries) {
    if (window.ws3d && ws3d.viewer && ws3d.viewer.scene) {
      viewer = ws3d.viewer;
      buildShell();
      attachPicking();
      setupTilesets();   // 우리 단지 외 건물 클리핑(clipOn 기본 true)
      post({ type: "ready" });
    } else if (tries >= POLL_MAX) {
      post({ type: "error", message: "실사 3D 초기화에 실패했습니다. VWorld 인증키·서비스 URL 등록을 확인해 주세요." });
    } else {
      setTimeout(function () { waitViewer(tries + 1); }, POLL_MS);
    }
  }

  window.addEventListener("message", function (e) {
    if (e.source !== window.parent) return;   // 부모 프레임만 신뢰(임의 메시지 차단)
    var d = e.data;
    if (!d || typeof d !== "object") return;
    if (d.type === "init") {
      if (started) return;                    // init 은 1회만(재토글은 부모가 iframe 을 새로 마운트)
      started = true;
      units = Array.isArray(d.units) ? d.units : [];
      idSet = new Set(units.map(function (u) { return u.householdId; }));
      center = d.center;
      startMap();
    } else if (d.type === "recolor") {
      if (d.colors) recolor(d.colors);
    }
  });
})();
</script>
</body>
</html>`;
}
