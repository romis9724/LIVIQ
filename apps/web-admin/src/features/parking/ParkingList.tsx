"use client";

import { useMemo } from "react";
import { elapsedText, type ParkedCar } from "./parking-sim";
import { EXTERNAL_GROUP } from "./ParkingMap";

interface ParkingListProps {
  bySpot: ReadonlyMap<string, ParkedCar>;
  /** 필터·강조 소속(동명 또는 "외부"). null=전체 — 지도 강조와 같은 상태를 공유한다. */
  group: string | null;
  dongs: readonly string[];
  nowMs: number;
  selectedNo: string | null;
  onGroupChange: (group: string | null) => void;
  onSelect: (spotNo: string) => void;
}

interface ParkedRow {
  spotNo: string;
  car: ParkedCar;
}

/**
 * 주차 차량 목록 — 면·번호판·소속·경과. 소속 select 로 필터하고 면 버튼으로 지도를 포커스한다.
 * 지도(SVG)는 포인터 전용이라 이 표가 키보드·스크린리더의 대안 경로다(WCAG 2.2 AA).
 */
export function ParkingList({
  bySpot,
  group,
  dongs,
  nowMs,
  selectedNo,
  onGroupChange,
  onSelect,
}: ParkingListProps) {
  const rows = useMemo(() => parkedRows(bySpot, group), [bySpot, group]);

  return (
    <section className="surface-card pk-panel" aria-labelledby="pk-list-title">
      <div className="pk-panel__head">
        <h2 id="pk-list-title" className="pk-panel__title">
          주차 차량 목록
        </h2>
        <span className="pk-panel__count">{rows.length}대</span>
      </div>

      <label className="pk-panel__filter">
        <span className="pk-panel__filter-label">소속</span>
        <select
          className="pk-select"
          value={group ?? ""}
          onChange={(event) => onGroupChange(event.currentTarget.value || null)}
        >
          <option value="">전체</option>
          {dongs.map((dong) => (
            <option key={dong} value={dong}>
              {dong}
            </option>
          ))}
          <option value={EXTERNAL_GROUP}>외부 차량</option>
        </select>
      </label>

      {rows.length === 0 ? (
        <p className="pk-panel__empty">해당 차량이 없습니다.</p>
      ) : (
        <div className="pk-table-scroll">
          <table className="pk-table">
            <thead>
              <tr>
                <th scope="col">면</th>
                <th scope="col">차량번호</th>
                <th scope="col">소속</th>
                <th scope="col">경과</th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ spotNo, car }) => (
                <tr key={spotNo} data-selected={spotNo === selectedNo || undefined}>
                  <td>
                    <button
                      type="button"
                      className="pk-table__spot"
                      aria-current={spotNo === selectedNo ? "true" : undefined}
                      aria-label={`${spotNo}면 ${affiliationText(car)} ${car.plate} — 배치도에서 보기`}
                      onClick={() => onSelect(spotNo)}
                    >
                      {spotNo}
                    </button>
                  </td>
                  <td className="pk-table__plate">{car.plate}</td>
                  <td data-external={car.external || undefined}>{affiliationText(car)}</td>
                  <td className="pk-table__elapsed">{elapsedText(car.entryMs, nowMs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** 주차 중인 차량 → 면 번호 오름차순 행. group 이 있으면 그 소속만. */
function parkedRows(bySpot: ReadonlyMap<string, ParkedCar>, group: string | null): ParkedRow[] {
  const rows: ParkedRow[] = [];
  for (const [spotNo, car] of bySpot) {
    if (group === EXTERNAL_GROUP && !car.external) continue;
    if (group !== null && group !== EXTERNAL_GROUP && car.dong !== group) continue;
    rows.push({ spotNo, car });
  }
  return rows.sort((a, b) => a.spotNo.localeCompare(b.spotNo));
}

/** 소속 표시 — 입주민은 "401동 1502호", 외부 차량은 "외부". */
function affiliationText(car: ParkedCar): string {
  return car.external ? EXTERNAL_GROUP : `${car.dong ?? ""} ${car.ho ?? ""}`.trim();
}
