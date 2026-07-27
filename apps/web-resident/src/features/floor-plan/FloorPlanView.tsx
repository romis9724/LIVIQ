"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { EmptyState, Skeleton } from "@liviq/ui";
import { getMyFloorPlan, type FloorPlanData, type FloorPlanDevice } from "./api";
import {
  CATEGORY_ORDER,
  FILTER_LABEL,
  ariaLabel,
  deviceCategory,
  dirRotation,
  tableRows,
  toPercent,
  type FilterKey,
} from "./floor-plan-data";
import "./floor-plan.css";

type LoadState = "loading" | "empty" | "error" | "ready";

export function FloorPlanView() {
  const router = useRouter();
  const [state, setState] = useState<LoadState>("loading");
  const [data, setData] = useState<FloorPlanData | null>(null);
  const [enabled, setEnabled] = useState<Set<FilterKey>>(() => new Set(CATEGORY_ORDER));
  const [selected, setSelected] = useState<FloorPlanDevice | null>(null);
  const [showList, setShowList] = useState(false);

  useEffect(() => {
    let alive = true;
    getMyFloorPlan()
      .then((result) => {
        if (!alive) return;
        setData(result);
        setState(result ? "ready" : "empty");
      })
      .catch(() => alive && setState("error"));
    return () => {
      alive = false;
    };
  }, []);

  const toggle = (key: FilterKey): void => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const rooms = useMemo(
    () => (data ? data.devices.filter((d) => d.deviceType === "room") : []),
    [data],
  );
  const markers = useMemo(
    () =>
      data
        ? data.devices.filter(
            (d) => d.deviceType !== "room" && enabled.has(deviceCategory(d.deviceType)),
          )
        : [],
    [data, enabled],
  );
  const visibleRooms = enabled.has("room") ? rooms : [];
  const rows = useMemo(() => (data ? tableRows(data.devices) : []), [data]);

  return (
    <div className="floor-plan">
      <header className="floor-plan__header">
        <button
          type="button"
          className="floor-plan__back"
          aria-label="뒤로가기"
          onClick={() => router.back()}
        >
          ←
        </button>
        <h1 id="main" className="floor-plan__title">
          우리집 평면도
        </h1>
      </header>

      <main className="floor-plan__main">
        {state === "loading" ? (
          <Skeleton height="18rem" />
        ) : state === "error" ? (
          <EmptyState
            icon="⚠"
            title="평면도를 불러오지 못했습니다"
            description="잠시 후 다시 시도해 주세요."
          />
        ) : state === "empty" || !data ? (
          <EmptyState
            icon="🏠"
            title="평면도가 아직 준비되지 않았습니다"
            description="세대 평면도 등록 문의는 관리사무소로 연락해 주세요."
          />
        ) : (
          <>
            {data.plan.unitTypeName ? (
              <p className="floor-plan__unit-type">{data.plan.unitTypeName} 타입</p>
            ) : null}

            <div className="floor-plan__filters" role="group" aria-label="표시 종류">
              {CATEGORY_ORDER.map((key) => (
                <button
                  key={key}
                  type="button"
                  className="floor-plan-chip"
                  data-category={key}
                  aria-pressed={enabled.has(key)}
                  onClick={() => toggle(key)}
                >
                  {FILTER_LABEL[key]}
                </button>
              ))}
            </div>

            <div className="floor-plan__canvas">
              {/* eslint-disable-next-line @next/next/no-img-element -- 서명 URL(외부 오리진) — next/image 도메인 등록 불필요한 단순 표시 */}
              <img
                src={data.plan.imageUrl}
                alt={data.plan.unitTypeName ? `${data.plan.unitTypeName} 평면도` : "평면도"}
                className="floor-plan__image"
                width={data.plan.imageWidth}
                height={data.plan.imageHeight}
              />

              {visibleRooms.map((room) => (
                <span
                  key={room.id}
                  className="floor-plan-room-label"
                  style={{
                    left: `${toPercent(room.x, data.plan.imageWidth)}%`,
                    top: `${toPercent(room.y, data.plan.imageHeight)}%`,
                  }}
                >
                  {room.label ?? room.room ?? ""}
                </span>
              ))}

              {markers.map((device) => {
                const rotation = dirRotation(device.dir);
                return (
                  <button
                    key={device.id}
                    type="button"
                    className="floor-plan-marker"
                    data-category={deviceCategory(device.deviceType)}
                    aria-label={ariaLabel(device)}
                    style={{
                      left: `${toPercent(device.x, data.plan.imageWidth)}%`,
                      top: `${toPercent(device.y, data.plan.imageHeight)}%`,
                    }}
                    onClick={() => setSelected(device)}
                  >
                    {rotation !== null ? (
                      <span
                        className="floor-plan-marker__arrow"
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
                  x={toPercent(selected.x, data.plan.imageWidth)}
                  y={toPercent(selected.y, data.plan.imageHeight)}
                  onClose={() => setSelected(null)}
                />
              ) : null}
            </div>

            <button
              type="button"
              className="floor-plan__list-toggle"
              aria-expanded={showList}
              onClick={() => setShowList((v) => !v)}
            >
              {showList ? "목록 닫기" : "목록으로 보기"}
            </button>

            {showList ? <DeviceTable rows={rows} /> : null}
          </>
        )}
      </main>
    </div>
  );
}

function DevicePopover({
  device,
  x,
  y,
  onClose,
}: {
  device: FloorPlanDevice;
  x: number;
  y: number;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="floor-plan-popover"
      role="dialog"
      aria-label={ariaLabel(device)}
      // 상단 30% 안쪽 마커는 팝오버를 아래로 펼쳐 컨테이너 밖 잘림을 막는다(도면 상단 다용도실 등).
      style={{ left: `${x}%`, top: `${y}%` }}
      data-flip={y < 30 || undefined}
    >
      <button
        type="button"
        className="floor-plan-popover__close"
        aria-label="닫기"
        onClick={onClose}
      >
        ×
      </button>
      <dl className="floor-plan-popover__body">
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
    return <p className="floor-plan__msg">등록된 시설 정보가 없습니다.</p>;
  }
  return (
    <table className="floor-plan-table">
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
