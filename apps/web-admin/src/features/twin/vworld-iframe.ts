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
  var groundH = 25;           // 지반 고도(m) — sampleGround 가 실측 지반고로 갱신(쉘↔실사건물 정렬, 프로토타입)
  var SHELL_ALPHA = 0.22;     // 실사 건물이 비치도록 낮은 틴트
  var SHELL_SCALE = 1.2;      // 실사 건물보다 살짝 키워 반투명 쉘이 감싸도록
  var POINT_ALPHA = 0.9;      // 포인트 도트 — 실사 건물 위에서도 잘 보이게 진하게(가독성 수정, H9-4)
  var POINT_SIZE = 10;        // 포인트 픽셀 크기
  var POLL_MS = 300;
  var POLL_MAX = 100;         // 30초(300ms×100) 내 뷰어 준비 실패 → error
  var SAMPLE_MS = 400;        // 지반고 샘플 주기
  var SAMPLE_MAX = 20;        // 최대 8초(400ms×20) — 못 정하면 기본 지반고로 진행
  var SETTLE_MS = 300;        // 시점 수렴 확인 주기
  var SETTLE_STABLE = 4;      // 연속 4틱(1.2초) 그대로면 안정으로 본다
  var SETTLE_MAX = 30;        // 최대 9초(300ms×30) — 안 멎어도 그때는 공개
  var WATCH_MAX = 30;         // 공개 후 15초(500ms×30)까지 시점 되돌림 감시
  // 궤도 거리 — 너무 가까우면 VWorld 실사 타일(영상·3D건물)이 선택되지 않아 저해상 지형만 남는다(실측).
  // 프로토타입과 같은 560m 를 하한으로 두고, 단지가 크면 반지름에 비례해 물린다.
  var LOOK_RANGE_MIN = 560;
  var LOOK_RANGE_FACTOR = 2.5;

  var viewer = null;
  var primitive = null;         // 세대 shell Primitive(반투명 압출)
  var points = null;            // 세대 중심 PointPrimitiveCollection(가독성 — H9-4)
  var pointByUid = {};          // householdId → PointPrimitive(recolor 대상)
  var idSet = null;
  var units = [];
  var center = null;
  var started = false;
  var style = "shell";          // 렌더 스타일 — shell·point·off(부모가 postMessage 로 전환)
  var locked = false;           // 시점 단지 고정(lookAt 궤도 회전)
  var orbitTimer = null;        // 360° 자동 회전 setInterval 핸들
  var orbitHeading = 0;         // 현재 회전 방위(rad)
  var complexSphere = null;     // 세대 전체를 감싸는 BoundingSphere — 시점 기준점·궤도 거리
  var appliedSnap = null;       // 우리가 마지막으로 세운 카메라 위치 지문(드리프트 감지용)
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
      var base = groundH + u.baseZ;
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
      asynchronous: false,
      show: style === "shell"
    }));
  }

  // 폴리곤 무게중심 [lon,lat] — 포인트 도트 위치.
  function centroid(coords) {
    var sx = 0, sy = 0, i;
    for (i = 0; i < coords.length; i++) { sx += coords[i][0]; sy += coords[i][1]; }
    return [sx / coords.length, sy / coords.length];
  }

  // 세대 중심 도트 컬렉션 — 반투명 쉘이 안 보이는 희소/균일 오버레이(입주·민원·관리비) 가독성용(H9-4).
  // disableDepthTestDistance=∞ 로 실사 건물에 가려지지 않고 항상 위에 뜬다(프로토타입 방식).
  function buildPoints() {
    var C = Cesium, i, u, c;
    points = viewer.scene.primitives.add(new C.PointPrimitiveCollection());
    points.show = style === "point";
    for (i = 0; i < units.length; i++) {
      u = units[i];
      c = centroid(u.polygon2d);
      pointByUid[u.householdId] = points.add({
        position: C.Cartesian3.fromDegrees(c[0], c[1], groundH + u.baseZ + u.floorHeight / 2),
        pixelSize: POINT_SIZE,
        color: rgba(u.rgb, POINT_ALPHA),
        outlineColor: C.Color.BLACK.withAlpha(0.35),
        outlineWidth: 1,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
        id: u.householdId
      });
    }
  }

  // 지형 타일에서 실제 지반고를 읽어 groundH 를 확정한다(프로토타입 sampleGround).
  // 쉘은 이 값이 정해진 뒤 1회만 만든다 — 나중에 고쳐 지으면 화면에서 높이가 튄다.
  // 저해상도 타일의 엉뚱한 값(예 -65m)을 거르려 상식 범위 + 2회 연속 일치를 요구하고,
  // 최대 SAMPLE_MAX 회 안에 못 정하면 기본값(25m)으로 진행한다.
  function sampleGround(done) {
    var carto = Cesium.Cartographic.fromDegrees(center[0], center[1]);
    var prev = null, tries = 0;
    var iv = setInterval(function () {
      var h;
      try { h = viewer.scene.globe.getHeight(carto); } catch (e) { h = undefined; }
      var ok = typeof h === "number" && isFinite(h) && h > 0 && h < 200;
      if (ok && prev !== null && Math.abs(h - prev) <= 2) {
        groundH = h;
        clearInterval(iv);
        done();
        return;
      }
      prev = ok ? h : null;
      if (++tries >= SAMPLE_MAX) { clearInterval(iv); done(); }
    }, SAMPLE_MS);
  }

  // VWorld 는 map.start() 에서 전지구→단지 flyTo 를 건다. 이 비행이 매 프레임 카메라를 덮어써
  // 우리가 세운 시점이 무시되므로(실측), 시점을 세우기 전에 항상 비행부터 취소한다.
  function cancelFlight() {
    if (viewer.camera.cancelFlight) viewer.camera.cancelFlight();
  }

  // 단지 남동쪽 조감 시점(프로토타입 setCamera) — 단지 고정이 꺼진 경우의 기본 시점.
  function setCamera() {
    cancelFlight();
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(center[0] + 0.003, center[1] - 0.0045, groundH + 330),
      orientation: { heading: Cesium.Math.toRadians(-28), pitch: Cesium.Math.toRadians(-33), roll: 0 }
    });
  }

  // 초기 시점 확정 — 단지 고정이면 단지 중심을 화면 중앙에, 아니면 조감 시점.
  // 적용 직후 위치를 기억해 두고(appliedSnap), 이후 값이 달라지면 VWorld 가 건드린 것으로 본다.
  function frameComplex() {
    if (locked) setLock(true); else setCamera();
    appliedSnap = cameraSnap();
  }

  // 카메라 위치 지문(약 1m 해상도) — 누가 시점을 건드렸는지 비교용.
  function cameraSnap() {
    var c = viewer.camera.positionCartographic, M = Cesium.Math;
    return [Math.round(c.height), Math.round(M.toDegrees(c.longitude) * 1e5), Math.round(M.toDegrees(c.latitude) * 1e5)].join(",");
  }

  // VWorld 는 뷰어 준비 후에도 카메라를 뒤늦게 밀어낸다(실측 — 방향은 그대로라 단지가 화면 위로 치우친다).
  // 우리가 세운 시점이 연속 SETTLE_STABLE 틱 유지될 때까지 오버레이 뒤에서 재적용한 뒤 공개한다.
  function settleCamera(done) {
    var tries = 0, stable = 0;
    var iv = setInterval(function () {
      if (appliedSnap !== null && cameraSnap() === appliedSnap) {
        if (++stable >= SETTLE_STABLE) { clearInterval(iv); done(); return; }
      } else {
        stable = 0;
        frameComplex();
      }
      if (++tries >= SETTLE_MAX) { clearInterval(iv); done(); }
    }, SETTLE_MS);
  }

  // 공개 후에도 VWorld 가 시점을 건드리는 경우가 남아 있어 잠시(WATCH_MAX) 더 감시한다.
  // 사용자가 지도를 만지면(포인터·휠) 즉시 손을 뗀다 — 시점 싸움 방지.
  function watchCamera() {
    var tries = 0, stopped = false;
    function stop() {
      if (stopped) return;
      stopped = true;
      document.removeEventListener("pointerdown", stop, true);
      document.removeEventListener("wheel", stop, true);
    }
    document.addEventListener("pointerdown", stop, true);
    document.addEventListener("wheel", stop, true);
    var iv = setInterval(function () {
      if (stopped || ++tries > WATCH_MAX) { clearInterval(iv); stop(); return; }
      if (appliedSnap !== null && cameraSnap() !== appliedSnap) frameComplex();
    }, 500);
  }

  // 렌더 스타일 전환 — shell·point·off. 부모 세그먼트 토글이 postMessage 로 지시.
  function applyStyle(s) {
    style = s;
    if (primitive) primitive.show = s === "shell";
    if (points) points.show = s === "point";
  }

  // 오버레이 변경 → shell per-instance 색 + 포인트 색 교체(기하 재생성 없음).
  function recolor(colors) {
    var C = Cesium, i, u, c, attrs, pt;
    // 포인트·상태값은 shell 컴파일 여부와 무관하게 항상 갱신.
    for (i = 0; i < units.length; i++) {
      u = units[i];
      c = colors[u.householdId];
      if (!c) continue;
      u.rgb = c;
      pt = pointByUid[u.householdId];
      if (pt) pt.color = rgba(c, POINT_ALPHA);
    }
    if (!primitive) return;
    if (!primitive.ready) {
      // 아직 GPU 컴파일 전이면 속성 접근 불가 → 새 색으로 shell 재생성.
      viewer.scene.primitives.remove(primitive);
      buildShell();
      return;
    }
    for (i = 0; i < units.length; i++) {
      c = colors[units[i].householdId];
      if (!c) continue;
      attrs = primitive.getGeometryInstanceAttributes(units[i].householdId);
      if (attrs) attrs.color = C.ColorGeometryInstanceAttribute.toValue(rgba(c, SHELL_ALPHA), attrs.color);
    }
  }

  // 피킹 — drillPick 으로 실사 건물 뒤 shell 까지 관통, 클릭 householdId 를 부모로 전달.
  function attachPicking() {
    var C = Cesium;
    var handler = new C.ScreenSpaceEventHandler(viewer.scene.canvas);
    function pick(pos) {
      if (style === "off") return null;   // 오버레이 끄면 세대 피킹도 비활성
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

    var centerC = C.Cartesian3.fromDegrees(hx, hy, groundH);
    var enu = C.Transforms.eastNorthUpToFixedFrame(centerC);
    var inv = C.Matrix4.inverse(enu, new C.Matrix4());
    var local = hull.map(function (p) {
      var c = C.Cartesian3.fromDegrees(p[0], p[1], groundH);
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

  // ── 시점: 단지 고정 & 360° 회전 (프로토타입 lookAt 궤도) ──
  // lookAt 으로 카메라 기준점을 단지 중심에 잠그면 드래그·자동회전이 중심 궤도 회전이 된다.
  // 기준점은 세대 정점 전체의 bounding sphere 중심 — 폴리곤 첫 정점 평균(center)은 동 배치에 따라
  // 실제 볼륨 중심에서 100m 이상 치우칠 수 있어 단지가 화면 위쪽으로 밀린다(실측).
  function buildComplexSphere() {
    var pts = [], i, k, u;
    for (i = 0; i < units.length; i++) {
      u = units[i];
      for (k = 0; k < u.polygon2d.length; k++) {
        pts.push(Cesium.Cartesian3.fromDegrees(u.polygon2d[k][0], u.polygon2d[k][1], groundH + u.baseZ + u.floorHeight));
      }
    }
    complexSphere = pts.length ? Cesium.BoundingSphere.fromPoints(pts) : null;
  }
  function lookTarget() {
    if (complexSphere) return complexSphere.center;
    return Cesium.Cartesian3.fromDegrees(center[0], center[1], groundH + 40);
  }
  // 단지 크기에 맞춘 궤도 거리 — 반지름 대비 배수(화면에 여유 있게 담기도록).
  function lookRange() {
    return complexSphere ? Math.max(LOOK_RANGE_MIN, complexSphere.radius * LOOK_RANGE_FACTOR) : LOOK_RANGE_MIN;
  }
  // 현재 orbitHeading 으로 단지 중심을 화면 중앙에 두는 궤도 시점 적용.
  function applyLook() {
    cancelFlight();
    viewer.camera.lookAt(lookTarget(), new Cesium.HeadingPitchRange(orbitHeading, Cesium.Math.toRadians(-33), lookRange()));
  }
  function setLock(on) {
    locked = on;
    if (!viewer || !center) return;
    if (on) {
      orbitHeading = viewer.camera.heading;
      applyLook();
    } else {
      stopOrbit();
      viewer.camera.lookAtTransform(Cesium.Matrix4.IDENTITY);   // 자유 시점 복귀
    }
  }
  function startOrbit() {
    if (!viewer || !center || orbitTimer) return;
    if (!locked) setLock(true);
    orbitTimer = setInterval(function () {
      orbitHeading += Cesium.Math.toRadians(0.3);   // 한 바퀴 약 40초
      applyLook();
    }, 40);
  }
  function stopOrbit() {
    if (orbitTimer) { clearInterval(orbitTimer); orbitTimer = null; }
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

  // 준비 순서가 곧 첫 화면의 품질이다 — 부모는 ready 전까지 오버레이로 iframe 을 덮으므로,
  // 카메라 이동·지반고 확정·쉘 생성을 모두 끝낸 뒤에 ready 를 보내 한 번에 완성된 화면을 보여준다.
  // (중간 단계를 노출하면 시점이 튀고 쉘 높이가 뒤늦게 맞춰지는 게 그대로 보인다.)
  function waitViewer(tries) {
    if (window.ws3d && ws3d.viewer && ws3d.viewer.scene) {
      viewer = ws3d.viewer;
      attachPicking();
      setupTilesets();     // 우리 단지 외 건물 클리핑(clipOn 기본 true)
      setCamera();         // 먼저 단지 상공으로 — 이 지역 지형·건물 타일 로딩을 시작시킨다
      sampleGround(function () {
        buildShell();      // 지반고 확정 후 1회만 생성 — 나중에 고쳐 지으면 높이가 튄다
        buildPoints();
        buildComplexSphere();   // 확정된 높이로 시점 기준 구 계산
        applyStyle(style);
        settleCamera(function () {
          post({ type: "ready" });   // 여기서 처음 화면이 공개된다 — 이미 완성된 상태
          watchCamera();             // 이후 뒤늦은 전지구 리셋만 복구
        });
      });
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
      // 컨트롤 초기값을 init 에서 함께 받는다 — ready 이후 따로 받으면 첫 화면이 한 번 더 튄다.
      if (typeof d.style === "string") style = d.style;
      locked = !!d.lock;
      clipOn = d.clip !== false;
      startMap();
    } else if (d.type === "recolor") {
      if (d.colors) recolor(d.colors);
    } else if (d.type === "style") {
      if (typeof d.style === "string") applyStyle(d.style);
    } else if (d.type === "camera") {
      if (d.cmd === "lock") setLock(!!d.on);
      else if (d.cmd === "orbit") { if (d.on) startOrbit(); else stopOrbit(); }
    } else if (d.type === "clip") {
      applyClip(!!d.on);
    }
  });
})();
</script>
</body>
</html>`;
}
