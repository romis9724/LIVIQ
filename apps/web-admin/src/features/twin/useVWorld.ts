"use client";

import { useEffect, useRef, useState } from "react";

import type { TwinGeometryItem } from "@/lib/api";
import type { OverlayKind } from "./twin-data";
import {
  attachPicking,
  buildShellPrimitive,
  centerOf,
  destroyViewer,
  enforceCamera,
  getReadyViewer,
  loadVWorldScript,
  recolorShell,
  startVWorldMap,
} from "./vworld-render";

// VWorld 맵 컨테이너 id — 뷰 토글로 단일 인스턴스만 마운트되므로 고정 id로 충분.
const CONTAINER_ID = "vworld-map";
const VIEWER_POLL_MS = 300;
const VIEWER_POLL_MAX = 100; // 30초(300ms×100) 내 준비 실패 → 에러

// Cesium 런타임 객체 ref — 좁은 any 경계(vworld-render 와 동일 이유).
/* eslint-disable-next-line @typescript-eslint/no-explicit-any -- VWorld 전역, 번들 타입 없음 */
type CesiumRef = any;

export type VWorldStatus = "loading" | "ready" | "error";

export interface VWorldState {
  status: VWorldStatus;
  error: string | null;
  containerId: string;
}

interface UseVWorldParams {
  apiKey: string;
  geometry: TwinGeometryItem[];
  overlay: Record<string, number>;
  overlayKind: OverlayKind;
  onSelectHousehold: (householdId: string) => void;
}

/**
 * VWorld 실사 3D 뷰어 수명주기 훅 — 스크립트 로드 → 맵 시작 → 뷰어 폴링 → shell·피킹 배치,
 * 언마운트 시 뷰어 파괴·타이머 정리(SPA 재토글 안전). 오버레이 변경은 재초기화 없이 recolor.
 */
export function useVWorld({
  apiKey,
  geometry,
  overlay,
  overlayKind,
  onSelectHousehold,
}: UseVWorldParams): VWorldState {
  const [status, setStatus] = useState<VWorldStatus>("loading");
  const [error, setError] = useState<string | null>(null);

  const viewerRef = useRef<CesiumRef>(null);
  const primitiveRef = useRef<CesiumRef>(null);
  const handlerRef = useRef<CesiumRef>(null);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  // 최신 오버레이·콜백을 init effect 재실행 없이 참조(init 은 apiKey·geometry 로만 재실행).
  const overlayRef = useRef(overlay);
  const overlayKindRef = useRef(overlayKind);
  const onSelectRef = useRef(onSelectHousehold);
  overlayRef.current = overlay;
  overlayKindRef.current = overlayKind;
  onSelectRef.current = onSelectHousehold;

  useEffect(() => {
    let disposed = false;
    setStatus("loading");
    setError(null);

    const fail = (message: string) => {
      if (disposed) return;
      setError(message);
      setStatus("error");
    };

    const onReady = (viewer: CesiumRef) => {
      if (disposed) return;
      viewerRef.current = viewer;
      const center = centerOf(geometry);
      const ids = new Set(geometry.map((g) => g.householdId));
      primitiveRef.current = buildShellPrimitive(
        viewer,
        geometry,
        overlayRef.current,
        overlayKindRef.current,
      );
      handlerRef.current = attachPicking(viewer, ids, (id) => onSelectRef.current(id));
      timersRef.current.push(enforceCamera(viewer, center));
      setStatus("ready");
    };

    const poll = (tries: number) => {
      if (disposed) return;
      const viewer = getReadyViewer();
      if (viewer) {
        onReady(viewer);
      } else if (tries >= VIEWER_POLL_MAX) {
        fail("실사 3D 초기화에 실패했습니다. VWorld 인증키·서비스 URL 등록을 확인해 주세요.");
      } else {
        timersRef.current.push(setTimeout(() => poll(tries + 1), VIEWER_POLL_MS));
      }
    };

    loadVWorldScript(apiKey)
      .then(() => {
        if (disposed) return;
        startVWorldMap(CONTAINER_ID, centerOf(geometry));
        poll(0);
      })
      .catch((e: unknown) => fail(e instanceof Error ? e.message : "실사 3D 로드에 실패했습니다."));

    return () => {
      disposed = true;
      for (const t of timersRef.current) clearTimeout(t);
      timersRef.current = [];
      handlerRef.current?.destroy?.();
      handlerRef.current = null;
      // ponytail: 언마운트 시 전역 뷰어 파괴. VWorld 전역 재초기화 안전성은 라이브 검증 필요 —
      //           재토글이 불안정하면 iframe 격리로 승급.
      destroyViewer();
      viewerRef.current = null;
      primitiveRef.current = null;
      const container = document.getElementById(CONTAINER_ID);
      if (container) container.innerHTML = "";
    };
  }, [apiKey, geometry]);

  // 오버레이·오버레이 종류 변경 → shell recolor(재초기화 없이 GPU 속성 교체).
  useEffect(() => {
    const viewer = viewerRef.current;
    const primitive = primitiveRef.current;
    if (status !== "ready" || !viewer || !primitive) return;
    primitiveRef.current = recolorShell(viewer, primitive, geometry, overlay, overlayKind);
  }, [overlay, overlayKind, geometry, status]);

  return { status, error, containerId: CONTAINER_ID };
}
