"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type PointerEvent,
  type ReactNode,
} from "react";
import type { ParkingLayout, ParkingSpot } from "@/lib/api";
import { SPOT_H, SPOT_W, elapsedText, type ParkedCar } from "./parking-sim";

// 면 상태 — 색·툴팁·강조가 모두 이 값으로 갈린다(색 단독 전달 금지: 툴팁·목록에 문구 병기).
type SpotState = "empty" | "resident" | "external";

/** 소속 필터의 "외부 차량" 그룹 키(동명이 아닌 유일 값). */
export const EXTERNAL_GROUP = "외부";

const NUMBER_OFFSET_TOP = 11; // dir=down 면은 위쪽에 번호
const NUMBER_OFFSET_BOTTOM = 5; // dir=up 면은 아래쪽에 번호
const HL_PAD = 3; // 선택 강조 테두리 여유

/** 줌 배율 — 1 = 전체 보기(컨테이너 폭에 맞춤), 그 이상은 확대 + 드래그 팬. */
const ZOOM_STEPS = [1, 1.5, 2, 3] as const;
const DRAG_THRESHOLD = 4; // px — 이보다 움직였으면 팬 제스처(면 선택 취소)

interface ParkingMapProps {
  layout: ParkingLayout;
  bySpot: ReadonlyMap<string, ParkedCar>;
  nowMs: number;
  /** 선택된 면 번호 — 강조 + 가로 스크롤 포커스. */
  selectedNo: string | null;
  /** 강조할 소속("401동" | "외부") — null 이면 전체 동일 강조. */
  activeGroup: string | null;
  onSelect: (spotNo: string) => void;
  /** 지도 요약(role=img aria-label) — 스크린리더는 목록 표를 대안 경로로 쓴다. */
  summaryLabel: string;
}

/**
 * 지하주차장 2D 배치도(프로토타입 renderParkingSVG 포팅).
 * 442면 x 여러 요소라 정적 레이어·면 레이어를 각각 useMemo 로 고정하고,
 * 선택 강조만 최상단 별도 레이어로 다시 그린다(선택 변경이 면 레이어를 건드리지 않게).
 */
export function ParkingMap({
  layout,
  bySpot,
  nowMs,
  selectedNo,
  activeGroup,
  onSelect,
  summaryLabel,
}: ParkingMapProps) {
  const staticLayer = useMemo(() => renderStatic(layout), [layout]);
  const spotLayer = useMemo(
    () => layout.spots.map((spot) => renderSpot(spot, bySpot.get(spot.no), nowMs, activeGroup)),
    [layout.spots, bySpot, nowMs, activeGroup],
  );
  const selected = useMemo(
    () => (selectedNo ? layout.spots.find((sp) => sp.no === selectedNo) ?? null : null),
    [layout.spots, selectedNo],
  );

  const [zoomIndex, setZoomIndex] = useState(0);
  const zoom = ZOOM_STEPS[zoomIndex] ?? 1;
  const viewportRef = useRef<HTMLDivElement>(null);

  // 확대 상태에서 선택된 면이 화면 밖이면 그 면을 화면 가운데로 옮긴다(목록 행 클릭 → 지도 포커스).
  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !selected || zoom === 1) return;
    const [, , width, height] = parseViewBox(layout.viewBox);
    if (width <= 0 || height <= 0) return;
    const left =
      ((selected.x + SPOT_W / 2) / width) * viewport.scrollWidth - viewport.clientWidth / 2;
    const top =
      ((selected.y + SPOT_H / 2) / height) * viewport.scrollHeight - viewport.clientHeight / 2;
    // behavior:"auto" 고정 — smooth 는 일부 브라우저에서 조용히 무시된다(팬 위치가 안 맞는 버그).
    viewport.scrollTo({ left: Math.max(0, left), top: Math.max(0, top), behavior: "auto" });
  }, [selected, zoom, layout.viewBox]);

  // 확대 상태 이동은 드래그 팬 — 스크롤바 대신 지도를 잡아 끈다. 위치는 스크롤 오프셋으로 유지.
  const dragRef = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const [dragging, setDragging] = useState(false);
  const draggedRef = useRef(false); // 끌고 나서 손을 떼는 순간의 click 은 면 선택으로 보지 않는다

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    const viewport = viewportRef.current;
    if (!viewport || zoom === 1 || event.button !== 0) return;
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      left: viewport.scrollLeft,
      top: viewport.scrollTop,
    };
    draggedRef.current = false;
    setDragging(true);
    viewport.setPointerCapture(event.pointerId);
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const viewport = viewportRef.current;
    const start = dragRef.current;
    if (!viewport || !start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD) draggedRef.current = true;
    viewport.scrollLeft = start.left - dx;
    viewport.scrollTop = start.top - dy;
  }

  function handlePointerUp(event: PointerEvent<HTMLDivElement>) {
    const viewport = viewportRef.current;
    if (viewport?.hasPointerCapture(event.pointerId)) {
      viewport.releasePointerCapture(event.pointerId);
    }
    dragRef.current = null;
    setDragging(false);
  }

  function handleClick(event: MouseEvent<SVGSVGElement>) {
    if (draggedRef.current) return; // 팬 제스처였다 — 선택 아님
    // 면 rect 에 data-no 를 심고 루트에서 위임 — 442개 핸들러를 만들지 않는다.
    const target = (event.target as Element | null)?.closest("[data-no]");
    const no = target?.getAttribute("data-no");
    if (no) onSelect(no);
  }

  return (
    <div className="pk-map">
      <div className="pk-zoom" role="group" aria-label="배치도 확대·축소">
        <button
          type="button"
          className="pk-zoom__btn"
          onClick={() => setZoomIndex((i) => Math.max(0, i - 1))}
          disabled={zoomIndex === 0}
          aria-label="축소"
        >
          −
        </button>
        <span className="pk-zoom__value" aria-live="polite">
          {zoom === 1 ? "전체" : `${zoom}×`}
        </span>
        <button
          type="button"
          className="pk-zoom__btn"
          onClick={() => setZoomIndex((i) => Math.min(ZOOM_STEPS.length - 1, i + 1))}
          disabled={zoomIndex === ZOOM_STEPS.length - 1}
          aria-label="확대"
        >
          +
        </button>
        {zoom !== 1 ? (
          <>
            <span className="pk-zoom__hint">끌어서 이동</span>
            <button type="button" className="pk-zoom__reset" onClick={() => setZoomIndex(0)}>
              전체 보기
            </button>
          </>
        ) : null}
      </div>

      {/* 배율 1 = 컨테이너 폭에 맞춘 전체 보기. 확대하면 지도를 끌어서 이동(키보드는 방향키 스크롤). */}
      <div
        className="pk-map__viewport"
        ref={viewportRef}
        data-zoomed={zoom === 1 ? undefined : true}
        data-dragging={dragging ? true : undefined}
        role={zoom === 1 ? undefined : "region"}
        aria-label={zoom === 1 ? undefined : "지하주차장 배치도 (확대 — 끌어서 이동, 방향키 가능)"}
        tabIndex={zoom === 1 ? undefined : 0}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
      >
        <svg
          className="pk-map__svg"
          viewBox={layout.viewBox}
          style={{ width: `${zoom * 100}%` }}
          role="img"
          aria-label={summaryLabel}
          onClick={handleClick}
        >
          {staticLayer}
          {spotLayer}
          {selected ? (
            <rect
              className="pk-hl"
              x={selected.x - HL_PAD}
              y={selected.y - HL_PAD}
              width={SPOT_W + HL_PAD * 2}
              height={SPOT_H + HL_PAD * 2}
              rx={5}
              pointerEvents="none"
            />
          ) : null}
        </svg>
      </div>
    </div>
  );
}

/** 외곽 프레임 + 램프·설비실 박스 + 동 footprint(동명·엘리베이터). 데이터가 고정이라 1회만 만든다. */
function renderStatic(layout: ParkingLayout): ReactNode {
  const [minX, minY, width, height] = parseViewBox(layout.viewBox);
  const inset = 8;
  return (
    <g>
      <rect
        className="pk-frame"
        x={minX + inset}
        y={minY + inset}
        width={Math.max(0, width - inset * 2)}
        height={Math.max(0, height - inset * 2)}
        rx={4}
      />
      {layout.boxes.map((box) => (
        <g key={`${box.label}-${box.x}-${box.y}`}>
          <rect className="pk-box" x={box.x} y={box.y} width={box.w} height={box.h} rx={4} />
          <text
            className="pk-box__label"
            x={box.x + box.w / 2}
            y={box.y + box.h / 2 + 4}
            textAnchor="middle"
          >
            {box.label}
          </text>
        </g>
      ))}
      {layout.buildings.map((building) => (
        <g key={building.name}>
          <polygon
            className="pk-building"
            points={building.outline.map((p) => p.join(",")).join(" ")}
          />
          <text
            className="pk-building__name"
            x={building.cx}
            y={building.cy - 8}
            textAnchor="middle"
          >
            {building.name}
          </text>
          <text className="pk-building__core" x={building.cx} y={building.cy + 20} textAnchor="middle">
            🛗
          </text>
        </g>
      ))}
    </g>
  );
}

/** 면 1개 — 바닥 rect(+툴팁) · 차량 글리프 · 특수면 아이콘 · 면 번호. */
function renderSpot(
  spot: ParkingSpot,
  car: ParkedCar | undefined,
  nowMs: number,
  activeGroup: string | null,
): ReactNode {
  const state: SpotState = car ? (car.external ? "external" : "resident") : "empty";
  const dim = activeGroup !== null && !matchesGroup(car, activeGroup);
  const numberY =
    spot.dir === "up" ? spot.y + SPOT_H - NUMBER_OFFSET_BOTTOM : spot.y + NUMBER_OFFSET_TOP;

  return (
    <g key={spot.no} className="pk-cell" data-dim={dim || undefined}>
      <rect
        className="pk-spot"
        data-no={spot.no}
        data-state={state}
        data-kind={spot.kind}
        x={spot.x}
        y={spot.y}
        width={SPOT_W}
        height={SPOT_H}
        rx={3}
      >
        <title>{spotTooltip(spot, car, nowMs)}</title>
      </rect>
      {car ? <CarGlyph spot={spot} state={state} /> : null}
      {spot.kind === "장애인" ? (
        <text
          className="pk-spot__icon"
          x={spot.x + SPOT_W / 2}
          y={spot.y + SPOT_H / 2 + 5}
          textAnchor="middle"
          pointerEvents="none"
        >
          ♿
        </text>
      ) : null}
      {spot.kind === "전기차" ? (
        <text
          className="pk-spot__icon pk-spot__icon--ev"
          x={spot.x + SPOT_W - 8}
          y={spot.y + 13}
          textAnchor="middle"
          pointerEvents="none"
        >
          ⚡
        </text>
      ) : null}
      <text
        className="pk-spot__no"
        x={spot.x + SPOT_W / 2}
        y={numberY}
        textAnchor="middle"
        pointerEvents="none"
      >
        {spot.no}
      </text>
    </g>
  );
}

/** 차량 글리프 — 차체 + 앞유리. dir=down 이면 면 중심 기준 180° 회전. */
function CarGlyph({ spot, state }: { spot: ParkingSpot; state: SpotState }) {
  const cx = spot.x + SPOT_W / 2;
  const cy = spot.y + SPOT_H / 2;
  return (
    <g
      className="pk-car"
      data-state={state}
      transform={spot.dir === "down" ? `rotate(180 ${cx} ${cy})` : undefined}
      pointerEvents="none"
    >
      <rect className="pk-car__body" x={spot.x + 6} y={spot.y + 7} width={22} height={50} rx={7} />
      <rect className="pk-car__glass" x={spot.x + 9} y={spot.y + 17} width={16} height={9} rx={3} />
    </g>
  );
}

/** 소속 필터 대조 — "외부"는 외부 차량, 그 외는 동명. 빈자리는 어느 그룹에도 속하지 않는다. */
function matchesGroup(car: ParkedCar | undefined, group: string): boolean {
  if (!car) return false;
  return group === EXTERNAL_GROUP ? car.external : car.dong === group;
}

/** 툴팁 — 면 번호·특수면 종류 + 차량 정보(관리자는 번호판 전체 표시). */
function spotTooltip(spot: ParkingSpot, car: ParkedCar | undefined, nowMs: number): string {
  const head = `${spot.no}면${spot.kind !== "일반" ? ` (${spot.kind})` : ""}`;
  if (!car) return `${head} — 빈자리`;
  if (car.external) {
    return `${head} — 외부차량 ${car.plate} · 주차 ${elapsedText(car.entryMs, nowMs)} 경과`;
  }
  return `${head} — ${car.plate} · ${car.dong} ${car.ho}`;
}

/** "0 0 3020 1082" → [minX, minY, width, height]. 파싱 실패는 0 으로 둔다(프레임 크기만 영향). */
function parseViewBox(viewBox: string): [number, number, number, number] {
  const parts = viewBox
    .trim()
    .split(/[\s,]+/)
    .map((v) => Number.parseFloat(v));
  return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0, parts[3] ?? 0];
}
