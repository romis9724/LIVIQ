"use client";

import { useState } from "react";
import { EmptyState, SurfaceCard } from "@liviq/ui";
import {
  DONGS,
  STATUS_MONTHS,
  UPLOAD_HISTORY,
  formatWon,
  latestRecord,
  lookupHouseholds,
  monthLabel,
} from "./logic";

const UNIT_OPTIONS = [
  { value: "all", label: "전체" },
  { value: "01", label: "1호" },
  { value: "02", label: "2호" },
];

export function StatusPanel() {
  const [month, setMonth] = useState<string>(STATUS_MONTHS[0]);
  const [dong, setDong] = useState("all");
  const [unit, setUnit] = useState("all");

  const record = latestRecord(month);
  const rows = lookupHouseholds(dong, unit);

  return (
    <div className="fu-status">
      <div className="fu-filters">
        <div className="fu-filter">
          <label htmlFor="fu-status-month">대상 월</label>
          <select
            id="fu-status-month"
            value={month}
            onChange={(e) => setMonth(e.target.value)}
          >
            {STATUS_MONTHS.map((m) => (
              <option key={m} value={m}>
                {monthLabel(m)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {record ? (
        <>
          <div className="fu-summary">
            <SurfaceCard className="fu-stat">
              <div className="fu-stat__label">업로드 일시</div>
              <div className="fu-stat__value">{record.uploadedAt}</div>
            </SurfaceCard>
            <SurfaceCard className="fu-stat">
              <div className="fu-stat__label">세대 수</div>
              <div className="fu-stat__value">{record.householdCount}세대</div>
            </SurfaceCard>
            <SurfaceCard className="fu-stat">
              <div className="fu-stat__label">합계</div>
              <div className="fu-stat__value">{formatWon(record.total)}</div>
            </SurfaceCard>
          </div>

          <section aria-labelledby="fu-lookup-title">
            <h2 id="fu-lookup-title" className="fu-section__title">
              세대 조회
            </h2>
            <div className="fu-filters" style={{ marginBottom: "var(--space-4)" }}>
              <div className="fu-filter">
                <label htmlFor="fu-dong">동</label>
                <select id="fu-dong" value={dong} onChange={(e) => setDong(e.target.value)}>
                  <option value="all">전체</option>
                  {DONGS.map((d) => (
                    <option key={d} value={d}>
                      {d}동
                    </option>
                  ))}
                </select>
              </div>
              <div className="fu-filter">
                <label htmlFor="fu-unit">호</label>
                <select id="fu-unit" value={unit} onChange={(e) => setUnit(e.target.value)}>
                  {UNIT_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="surface-card fu-tablecard">
              <table className="fu-table">
                <thead>
                  <tr>
                    <th scope="col">동</th>
                    <th scope="col">호</th>
                    <th scope="col" className="fu-num">
                      일반관리비
                    </th>
                    <th scope="col" className="fu-num">
                      난방비
                    </th>
                    <th scope="col" className="fu-num">
                      합계
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((h) => (
                    <tr key={`${h.dong}-${h.ho}`}>
                      <td>{h.dong}</td>
                      <td>{h.ho}</td>
                      <td className="fu-num">{formatWon(h.items.general)}</td>
                      <td className="fu-num">{formatWon(h.items.heating)}</td>
                      <td className="fu-num">{formatWon(h.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section aria-labelledby="fu-history-title">
            <h2 id="fu-history-title" className="fu-section__title">
              업로드 이력
            </h2>
            <SurfaceCard className="fu-stat">
              <ul className="fu-history">
                {UPLOAD_HISTORY.map((r) => (
                  <li key={`${r.month}-${r.revision}`} className="fu-history__item">
                    <span className="fu-history__month">{monthLabel(r.month)}</span>
                    <span className="fu-history__rev">revision {r.revision}</span>
                    <span className="fu-history__at">{r.uploadedAt}</span>
                  </li>
                ))}
              </ul>
            </SurfaceCard>
          </section>
        </>
      ) : (
        <EmptyState
          icon="📄"
          title="해당 월 업로드 내역이 없습니다"
          description={`${monthLabel(month)} 관리비 엑셀이 아직 업로드되지 않았습니다. 업로드 탭에서 파일을 올려주세요.`}
        />
      )}
    </div>
  );
}
