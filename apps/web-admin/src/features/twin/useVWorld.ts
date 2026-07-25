"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type RefObject } from "react";

import type { TwinGeometryItem } from "@/lib/api";
import { colorForOverlay, type OverlayKind, type RenderStyle, type Rgb } from "./twin-data";
import { buildVWorldSrcdoc } from "./vworld-iframe";
import { centerOf } from "./vworld-render";

export type VWorldStatus = "loading" | "ready" | "error";

export interface VWorldState {
  status: VWorldStatus;
  error: string | null;
  srcDoc: string;
  iframeRef: RefObject<HTMLIFrameElement | null>;
  onLoad: () => void;
}

// iframe 에 넘기는 세대 단위 — 좌표·색·householdId 뿐(개인정보 없음, 규칙 2).
interface UnitMessage {
  householdId: string;
  polygon2d: number[][];
  baseZ: number;
  floorHeight: number;
  rgb: Rgb;
}

interface UseVWorldParams {
  apiKey: string;
  geometry: TwinGeometryItem[];
  overlay: Record<string, number>;
  overlayKind: OverlayKind;
  renderStyle: RenderStyle; // 쉘·포인트·끄기
  cameraLock: boolean; // 시점 단지 고정
  orbit: boolean; // 360° 자동 회전
  clipOn: boolean; // 우리 단지만 표시(clip)
  onSelectHousehold: (householdId: string) => void;
}

/** 세대별 오버레이 색을 부모가 계산(colorForOverlay 재사용) — iframe 은 색 로직을 모른다. */
function colorsFor(
  geometry: readonly TwinGeometryItem[],
  overlay: Record<string, number>,
  overlayKind: OverlayKind,
): Record<string, Rgb> {
  const out: Record<string, Rgb> = {};
  for (const g of geometry) out[g.householdId] = colorForOverlay(overlayKind, overlay[g.householdId]);
  return out;
}

function unitsFor(
  geometry: readonly TwinGeometryItem[],
  overlay: Record<string, number>,
  overlayKind: OverlayKind,
): UnitMessage[] {
  return geometry.map((g) => ({
    householdId: g.householdId,
    polygon2d: g.polygon2d,
    baseZ: g.baseZ,
    floorHeight: g.floorHeight,
    rgb: colorForOverlay(overlayKind, overlay[g.householdId]),
  }));
}

/**
 * VWorld 실사 3D iframe 수명주기 훅 — srcdoc 생성·데이터 postMessage·클릭 수신(H9-3b, ADR-0019 개정).
 * 렌더는 iframe(vworld-iframe.ts) 안에서, 부모는 색 계산·상태·범례를 담당한다. iframe 파괴가 곧 정리라
 * 별도 Cesium destroy 는 없다(React 가 iframe 을 제거). 오버레이 변경은 recolor 로 재초기화 없이 갱신.
 */
export function useVWorld({
  apiKey,
  geometry,
  overlay,
  overlayKind,
  renderStyle,
  cameraLock,
  orbit,
  clipOn,
  onSelectHousehold,
}: UseVWorldParams): VWorldState {
  const [status, setStatus] = useState<VWorldStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  // srcdoc 은 apiKey 로만 결정 — 메모이즈해 오버레이 변경 때 iframe 이 재로드되지 않게 한다.
  const srcDoc = useMemo(() => buildVWorldSrcdoc(apiKey), [apiKey]);

  // 최신 값 참조(리스너·onLoad 를 재생성하지 않고 최신 데이터로 init/select 처리).
  const geometryRef = useRef(geometry);
  const overlayRef = useRef(overlay);
  const overlayKindRef = useRef(overlayKind);
  const onSelectRef = useRef(onSelectHousehold);
  const controlsRef = useRef({ renderStyle, cameraLock, clipOn });
  geometryRef.current = geometry;
  overlayRef.current = overlay;
  overlayKindRef.current = overlayKind;
  onSelectRef.current = onSelectHousehold;
  controlsRef.current = { renderStyle, cameraLock, clipOn };

  // iframe → 부모 메시지 수신. srcdoc origin 은 신뢰 못하므로(about:srcdoc) 소스 참조로 검증.
  useEffect(() => {
    function onMessage(event: MessageEvent) {
      const iframe = iframeRef.current;
      if (!iframe || event.source !== iframe.contentWindow) return; // 임의 메시지 차단
      const data: unknown = event.data;
      if (!data || typeof data !== "object") return;
      const type = (data as { type?: unknown }).type;
      if (type === "ready") {
        setStatus("ready");
        setError(null);
      } else if (type === "error") {
        const message = (data as { message?: unknown }).message;
        setError(typeof message === "string" ? message : "실사 3D 초기화에 실패했습니다.");
        setStatus("error");
      } else if (type === "select") {
        const id = (data as { householdId?: unknown }).householdId;
        if (typeof id === "string") onSelectRef.current(id);
      }
    }
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // iframe 로드 완료(문서·VWorld 스크립트 파싱 끝) → 최신 데이터로 init 전송.
  const onLoad = useCallback(() => {
    const iframe = iframeRef.current;
    if (!iframe?.contentWindow) return;
    setStatus("loading");
    setError(null);
    const g = geometryRef.current;
    const c = controlsRef.current;
    iframe.contentWindow.postMessage(
      {
        type: "init",
        center: centerOf(g),
        units: unitsFor(g, overlayRef.current, overlayKindRef.current),
        // 컨트롤 초기값을 함께 넘긴다 — iframe 이 첫 화면을 한 번에 확정하게(ready 후 재적용은 no-op).
        style: c.renderStyle,
        lock: c.cameraLock,
        clip: c.clipOn,
      },
      "*",
    );
  }, []);

  // 오버레이·오버레이 종류 변경 → recolor 전송(ready 이후에만, init 이 초기 색을 이미 실음).
  useEffect(() => {
    if (status !== "ready") return;
    const iframe = iframeRef.current;
    if (!iframe?.contentWindow) return;
    iframe.contentWindow.postMessage(
      { type: "recolor", colors: colorsFor(geometry, overlay, overlayKind) },
      "*",
    );
  }, [overlay, overlayKind, geometry, status]);

  // 컨트롤 변경 → iframe 전달(ready 이후). status 의존으로 초기 ready 시 현재 값 동기화도 겸한다.
  useEffect(() => {
    if (status !== "ready") return;
    iframeRef.current?.contentWindow?.postMessage({ type: "style", style: renderStyle }, "*");
  }, [renderStyle, status]);

  useEffect(() => {
    if (status !== "ready") return;
    iframeRef.current?.contentWindow?.postMessage({ type: "camera", cmd: "lock", on: cameraLock }, "*");
  }, [cameraLock, status]);

  useEffect(() => {
    if (status !== "ready") return;
    iframeRef.current?.contentWindow?.postMessage({ type: "camera", cmd: "orbit", on: orbit }, "*");
  }, [orbit, status]);

  useEffect(() => {
    if (status !== "ready") return;
    iframeRef.current?.contentWindow?.postMessage({ type: "clip", on: clipOn }, "*");
  }, [clipOn, status]);

  return { status, error, srcDoc, iframeRef, onLoad };
}
