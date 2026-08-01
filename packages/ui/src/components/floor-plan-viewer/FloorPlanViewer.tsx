"use client";

import { useEffect, useMemo, useState } from "react";
import { cx } from "../../lib/cx";
import {
  CATEGORY_ORDER,
  FILTER_LABEL,
  ariaLabel,
  deviceCategory,
  dirRotation,
  isHighlightedDevice,
  tableRows,
  toPercent,
  type FilterKey,
} from "./floor-plan-data";

export interface FloorPlanViewerPlan {
  imageUrl: string;
  /** 원본 이미지 픽셀 크기 — 마커 좌표를 % 로 환산하는 기준. */
  imageWidth: number;
  imageHeight: number;
  unitTypeName?: string | null;
}

export interface FloorPlanViewerDevice {
  id: string;
  deviceType: string;
  /** 원본 이미지 픽셀 좌표. */
  x: number;
  y: number;
  room: string | null;
  dir: string | null;
  label: string | null;
  memo: string | null;
}

export interface FloorPlanViewerProps {
  plan: FloorPlanViewerPlan;
  devices: readonly FloorPlanViewerDevice[];
  /** 접근성 대체 표("목록으로 보기") 노출 여부. 기본 true. */
  showListToggle?: boolean;
  /**
   * 처음부터 강조할 기기 라벨(AI 비서 딥링크 `?device=`). 기기 종류·이름과 부분 일치하는
   * 마커를 전부 강조하고 첫 마커를 선택 상태로 연다. 없으면(기본) 평소와 같다.
   */
  highlightLabels?: readonly string[];
  className?: string;
}

/**
 * 평면도 뷰어 — 도면 이미지 + 카테고리 칩 토글 + 마커(방향 화살표)·클릭 팝오버 + 방 라벨.
 * 프레젠테이션 전용(데이터 로딩은 소비 측 책임) — 입주민 우리집 평면도·관리자 트윈 세대 상세 공용.
 */
export function FloorPlanViewer({
  plan,
  devices,
  showListToggle = true,
  highlightLabels,
  className,
}: FloorPlanViewerProps) {
  const highlighted = useMemo(() => {
    if (!highlightLabels || highlightLabels.length === 0) return new Set<string>();
    return new Set(
      devices
        .filter((d) => d.deviceType !== "room" && isHighlightedDevice(d, highlightLabels))
        .map((d) => d.id),
    );
  }, [devices, highlightLabels]);

  const [enabled, setEnabled] = useState<Set<FilterKey>>(() => new Set(CATEGORY_ORDER));
  // 강조 마커가 있으면 첫 마커를 열어 둔다(주차맵의 추천 면 선택과 같은 동선). 마운트 시 1회.
  // ponytail: 이후 devices·highlightLabels 변경은 재선택하지 않는다 — 페이지가 매번 새로 마운트된다.
  const [selected, setSelected] = useState<FloorPlanViewerDevice | null>(
    () => devices.find((d) => highlighted.has(d.id)) ?? null,
  );
  const [showList, setShowList] = useState(false);

  const toggle = (key: FilterKey): void => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const rooms = useMemo(() => devices.filter((d) => d.deviceType === "room"), [devices]);
  const markers = useMemo(
    () =>
      devices.filter(
        (d) => d.deviceType !== "room" && enabled.has(deviceCategory(d.deviceType)),
      ),
    [devices, enabled],
  );
  const visibleRooms = enabled.has("room") ? rooms : [];
  const rows = useMemo(() => tableRows(devices), [devices]);

  return (
    <div className={cx("floor-plan-viewer", className)}>
      <div className="floor-plan-viewer__filters" role="group" aria-label="표시 종류">
        {CATEGORY_ORDER.map((key) => (
          <button
            key={key}
            type="button"
            className="floor-plan-viewer__chip"
            data-category={key}
            aria-pressed={enabled.has(key)}
            onClick={() => toggle(key)}
          >
            {FILTER_LABEL[key]}
          </button>
        ))}
      </div>

      <div className="floor-plan-viewer__canvas">
        {/* 서명 URL(외부 오리진) — next/image 도메인 등록이 불필요한 단순 표시. */}
        <img
          src={plan.imageUrl}
          alt={plan.unitTypeName ? `${plan.unitTypeName} 평면도` : "평면도"}
          className="floor-plan-viewer__image"
          width={plan.imageWidth}
          height={plan.imageHeight}
        />

        {visibleRooms.map((room) => (
          <span
            key={room.id}
            className="floor-plan-viewer__room-label"
            style={{
              left: `${toPercent(room.x, plan.imageWidth)}%`,
              top: `${toPercent(room.y, plan.imageHeight)}%`,
            }}
          >
            {room.label ?? room.room ?? ""}
          </span>
        ))}

        {markers.map((device) => {
          const rotation = dirRotation(device.dir);
          const isFound = highlighted.has(device.id);
          return (
            <button
              key={device.id}
              type="button"
              className="floor-plan-viewer__marker"
              data-category={deviceCategory(device.deviceType)}
              // 색 단독 전달 금지(WCAG 1.4.1) — 강조는 라벨에도 담는다.
              data-highlight={isFound || undefined}
              aria-label={isFound ? `${ariaLabel(device)} — 찾는 위치` : ariaLabel(device)}
              style={{
                left: `${toPercent(device.x, plan.imageWidth)}%`,
                top: `${toPercent(device.y, plan.imageHeight)}%`,
              }}
              onClick={() => setSelected(device)}
            >
              {rotation !== null ? (
                <span
                  className="floor-plan-viewer__arrow"
                  aria-hidden="true"
                  style={{ transform: `rotate(${rotation}deg)` }}
                >
                  ↑
                </span>
              ) : null}
            </button>
          );
        })}

        {selected ? (
          <DevicePopover
            device={selected}
            x={toPercent(selected.x, plan.imageWidth)}
            y={toPercent(selected.y, plan.imageHeight)}
            onClose={() => setSelected(null)}
          />
        ) : null}
      </div>

      {showListToggle ? (
        <>
          <button
            type="button"
            className="floor-plan-viewer__list-toggle"
            aria-expanded={showList}
            onClick={() => setShowList((v) => !v)}
          >
            {showList ? "목록 닫기" : "목록으로 보기"}
          </button>
          {showList ? <DeviceTable rows={rows} /> : null}
        </>
      ) : null}
    </div>
  );
}

function DevicePopover({
  device,
  x,
  y,
  onClose,
}: {
  device: FloorPlanViewerDevice;
  x: number;
  y: number;
  onClose: () => void;
}) {
  // 캡처 단계 + 전파 차단 — Escape 는 팝오버만 닫는다(뷰어를 감싼 모달까지 닫히지 않게).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      onClose();
    };
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  return (
    <div
      className="floor-plan-viewer__popover"
      role="dialog"
      aria-label={ariaLabel(device)}
      // 상단 30% 안쪽 마커는 팝오버를 아래로 펼쳐 컨테이너 밖 잘림을 막는다(도면 상단 다용도실 등).
      style={{ left: `${x}%`, top: `${y}%` }}
      data-flip={y < 30 || undefined}
    >
      <button
        type="button"
        className="floor-plan-viewer__popover-close"
        aria-label="닫기"
        onClick={onClose}
      >
        ×
      </button>
      <dl className="floor-plan-viewer__popover-body">
        <div>
          <dt>종류</dt>
          <dd>{device.deviceType}</dd>
        </div>
        {device.room ? (
          <div>
            <dt>방</dt>
            <dd>{device.room}</dd>
          </div>
        ) : null}
        {device.label ? (
          <div>
            <dt>이름</dt>
            <dd>{device.label}</dd>
          </div>
        ) : null}
        {device.memo ? (
          <div>
            <dt>비고</dt>
            <dd>{device.memo}</dd>
          </div>
        ) : null}
      </dl>
    </div>
  );
}

function DeviceTable({ rows }: { rows: ReturnType<typeof tableRows> }) {
  if (rows.length === 0) {
    return <p className="floor-plan-viewer__msg">등록된 시설 정보가 없습니다.</p>;
  }
  return (
    <table className="floor-plan-viewer__table">
      <thead>
        <tr>
          <th scope="col">방</th>
          <th scope="col">종류</th>
          <th scope="col">비고</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={`${row.room}-${row.type}-${i}`}>
            <td>{row.room}</td>
            <td>{row.type}</td>
            <td>{row.note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
