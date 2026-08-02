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
import { cx } from "../../lib/cx";
import { SPOT_H, SPOT_W, parseViewBox } from "./parking-map-data";

/**
 * 면 상태 — 색·차량 글리프가 이 값으로 갈린다. 색 단독 전달 금지라 문구는 tooltip 이 담당한다.
 * 관리자는 소속을 구분(resident·external)하고, 입주민은 타 세대 차량을 구분하면 안 되므로
 * 점유 전부를 `occupied` 로, 본인 차량만 `mine` 으로 준다(규칙 2).
 */
export type ParkingSpotState = "empty" | "occupied" | "resident" | "external" | "mine";

/** 주차면 1개. x·y 는 배치도 좌표(면 34x64px), dir 은 차량 진행 방향(글리프 회전). */
export interface ParkingMapSpot {
  no: string;
  kind: string; // "일반" | "장애인" | "전기차"
  x: number;
  y: number;
  dir: "up" | "down";
}

/** 동 footprint — cx·cy 는 동명·엘리베이터 라벨 위치. */
export interface ParkingMapBuilding {
  name: string;
  outline: readonly (readonly number[])[];
  cx: number;
  cy: number;
}

/** 램프·기계전기실 등 주차면 아닌 구역 박스. */
export interface ParkingMapBox {
  label: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ParkingMapLayout {
  viewBox: string; // "0 0 3020 1082"
  buildings: readonly ParkingMapBuilding[];
  boxes: readonly ParkingMapBox[];
  spots: readonly ParkingMapSpot[];
}

/** 면 1개의 표시 상태 — 문구 생성·필터 판정은 전부 호출자 몫이고 여기선 그리기만 한다. */
export interface ParkingSpotView {
  state: ParkingSpotState;
  /** `<title>` 툴팁 — 색으로만 전달하지 않기 위해 상태 문구를 반드시 담는다. */
  tooltip: string;
  /** 필터에 걸러진 면(흐리게). */
  dim?: boolean;
}

export interface ParkingMapProps {
  layout: ParkingMapLayout;
  /** 면 번호 → 표시 상태. 없는 면은 빈자리로 그린다. */
  spotViews: ReadonlyMap<string, ParkingSpotView>;
  /** 추천 면 강조(입주민 "가까운 빈자리") — 선택 강조와 다른 색. */
  highlightNos?: readonly string[];
  /** 선택된 면 번호 — 강조 + 확대 상태에서 그 면으로 포커스. */
  selectedNo: string | null;
  onSelect: (spotNo: string) => void;
  /**
   * 초기 배율(기본 1 = 전체 보기). 좁은 컨테이너에서 442면 전체를 보면 면이 4px 라
   * 읽히지 않는다 — 볼 면이 정해진 진입(내 차·추천 자리)은 확대해서 시작한다.
   */
  initialZoom?: number;
  /** 지도 요약(role=img aria-label) — 스크린리더의 대안 경로. */
  summaryLabel: string;
  className?: string;
}

const NUMBER_OFFSET_TOP = 11; // dir=down 면은 위쪽에 번호
const NUMBER_OFFSET_BOTTOM = 5; // dir=up 면은 아래쪽에 번호
const HL_PAD = 3; // 선택 강조 테두리 여유

/**
 * 줌 배율 — 1 = 전체 보기(컨테이너 폭에 맞춤), 그 이상은 확대 + 드래그 팬.
 * 5× 는 사용자 요청(2026-08-01) — 3× 로도 면 번호가 작다는 지적. 팬·포커스는 배율에 비례해
 * 계산하므로(scrollWidth 기준) 단계 추가만으로 동작한다.
 */
const ZOOM_STEPS = [1, 1.5, 2, 3, 5] as const;
const DRAG_THRESHOLD = 4; // px — 이보다 움직였으면 팬 제스처(면 선택 취소)

const EMPTY_VIEW: ParkingSpotView = { state: "empty", tooltip: "" };

/** 요청 배율에 해당하는 단계 index — 목록에 없는 값은 전체 보기(0)로 접는다. */
function zoomIndexFor(zoom: number | undefined): number {
  if (zoom === undefined) return 0;
  const index = ZOOM_STEPS.indexOf(zoom as (typeof ZOOM_STEPS)[number]);
  return index >= 0 ? index : 0;
}

/**
 * 지하주차장 2D 배치도(프로토타입 renderParkingSVG 포팅 → H17-2 공용 승격).
 * 442면 x 여러 요소라 정적 레이어·면 레이어를 각각 useMemo 로 고정하고,
 * 선택 강조만 최상단 별도 레이어로 다시 그린다(선택 변경이 면 레이어를 건드리지 않게).
 * 프레젠테이션 전용 — 데이터 로딩·문구 생성은 소비 측 책임(FloorPlanViewer 와 같은 계약).
 */
export function ParkingMap({
  layout,
  spotViews,
  highlightNos,
  selectedNo,
  onSelect,
  summaryLabel,
  initialZoom,
  className,
}: ParkingMapProps) {
  const staticLayer = useMemo(() => renderStatic(layout), [layout]);
  const spotLayer = useMemo(
    () => layout.spots.map((spot) => renderSpot(spot, spotViews.get(spot.no) ?? EMPTY_VIEW)),
    [layout.spots, spotViews],
  );
  const selected = useMemo(
    () => (selectedNo ? layout.spots.find((sp) => sp.no === selectedNo) ?? null : null),
    [layout.spots, selectedNo],
  );
  const highlighted = useMemo(() => {
    if (!highlightNos || highlightNos.length === 0) return [];
    const wanted = new Set(highlightNos);
    return layout.spots.filter((spot) => wanted.has(spot.no));
  }, [layout.spots, highlightNos]);

  const [zoomIndex, setZoomIndex] = useState(() => zoomIndexFor(initialZoom));
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
    // 캡처는 아직 안 한다 — pointerdown에서 캡처하면 이어지는 click이 뷰포트로 리타게팅돼
    // SVG의 면 클릭(onClick 위임)이 영영 안 온다(2026-08-03 사용자 신고 — 확대 상태에서
    // 면을 눌러도 하단 정보가 안 바뀌던 버그). 드래그로 판정된 뒤에만 캡처한다.
  }

  function handlePointerMove(event: PointerEvent<HTMLDivElement>) {
    const viewport = viewportRef.current;
    const start = dragRef.current;
    if (!viewport || !start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if (
      !draggedRef.current &&
      (Math.abs(dx) > DRAG_THRESHOLD || Math.abs(dy) > DRAG_THRESHOLD)
    ) {
      draggedRef.current = true;
      setDragging(true);
      viewport.setPointerCapture(event.pointerId);
    }
    if (!draggedRef.current) return;
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
    <div className={cx("pk-map", className)}>
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
          {highlighted.map((spot) => (
            <SpotOutline key={`rec-${spot.no}`} spot={spot} recommend />
          ))}
          {selected ? <SpotOutline spot={selected} /> : null}
        </svg>
      </div>
    </div>
  );
}

/** 외곽 프레임 + 램프·설비실 박스 + 동 footprint(동명·엘리베이터). 데이터가 고정이라 1회만 만든다. */
function renderStatic(layout: ParkingMapLayout): ReactNode {
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
          <text
            className="pk-building__core"
            x={building.cx}
            y={building.cy + 20}
            textAnchor="middle"
          >
            🛗
          </text>
        </g>
      ))}
    </g>
  );
}

/** 면 1개 — 바닥 rect(+툴팁) · 차량 글리프 · 특수면 아이콘 · 면 번호. */
function renderSpot(spot: ParkingMapSpot, view: ParkingSpotView): ReactNode {
  const numberY =
    spot.dir === "up" ? spot.y + SPOT_H - NUMBER_OFFSET_BOTTOM : spot.y + NUMBER_OFFSET_TOP;

  return (
    <g key={spot.no} className="pk-cell" data-dim={view.dim || undefined}>
      <rect
        className="pk-spot"
        data-no={spot.no}
        data-state={view.state}
        data-kind={spot.kind}
        x={spot.x}
        y={spot.y}
        width={SPOT_W}
        height={SPOT_H}
        rx={3}
      >
        <title>{view.tooltip || `${spot.no}면`}</title>
      </rect>
      {view.state !== "empty" ? <CarGlyph spot={spot} state={view.state} /> : null}
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
function CarGlyph({ spot, state }: { spot: ParkingMapSpot; state: ParkingSpotState }) {
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

/** 선택·추천 면 테두리 — 면 레이어 위에 따로 그려 선택 변경이 442면 재렌더를 부르지 않게 한다. */
function SpotOutline({ spot, recommend }: { spot: ParkingMapSpot; recommend?: boolean }) {
  return (
    <rect
      className="pk-hl"
      data-recommend={recommend || undefined}
      x={spot.x - HL_PAD}
      y={spot.y - HL_PAD}
      width={SPOT_W + HL_PAD * 2}
      height={SPOT_H + HL_PAD * 2}
      rx={5}
      pointerEvents="none"
    />
  );
}
