"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, EmptyState, Skeleton, SurfaceCard } from "@liviq/ui";
import { ApiError, listAdminFees, type AdminFeeList } from "@/lib/api";
import { formatWon, monthLabel, unitLabel } from "./logic";

/** 이번 달(YYYY-MM). 현황 기본 조회 월. */
function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function StatusPanel() {
  const [period, setPeriod] = useState<string>(currentMonth());
  const [data, setData] = useState<AdminFeeList | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async (target: string) => {
    setLoading(true);
    try {
      const res = await listAdminFees(target);
      setData(res);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(period);
  }, [period, load]);

  const isEmpty = data !== null && data.householdCount === 0;

  return (
    <div className="fu-status">
      <div className="fu-filters">
        <div className="fu-filter">
          <label htmlFor="fu-status-month">대상 월</label>
          <input
            id="fu-status-month"
            type="month"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
        </div>
      </div>

      {loading ? (
        <div className="surface-card fu-tablecard fu-loading">
          <Skeleton height="1.5rem" />
          <Skeleton height="1.5rem" />
          <Skeleton height="1.5rem" />
        </div>
      ) : loadError ? (
        <EmptyState
          icon="⚠"
          title="부과 현황을 불러오지 못했습니다"
          description={loadError}
          action={<Button onClick={() => void load(period)}>다시 시도</Button>}
        />
      ) : isEmpty || data === null ? (
        <EmptyState
          icon="📄"
          title="해당 월 확정 데이터가 없습니다"
          description={`${monthLabel(period)} 관리비가 아직 확정되지 않았습니다. 업로드 탭에서 엑셀을 올려 확정하세요.`}
        />
      ) : (
        <>
          <div className="fu-summary">
            <SurfaceCard className="fu-stat">
              <div className="fu-stat__label">세대 수</div>
              <div className="fu-stat__value">{data.householdCount}세대</div>
            </SurfaceCard>
            <SurfaceCard className="fu-stat">
              <div className="fu-stat__label">합계</div>
              <div className="fu-stat__value">{formatWon(data.totalSum)}</div>
            </SurfaceCard>
          </div>

          <section aria-labelledby="fu-lookup-title">
            <h2 id="fu-lookup-title" className="fu-section__title">
              세대별 현황
            </h2>
            <div className="surface-card fu-tablecard">
              <table className="fu-table">
                <thead>
                  <tr>
                    <th scope="col">동</th>
                    <th scope="col">호</th>
                    <th scope="col" className="fu-num">
                      합계
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.households.map((h) => (
                    <tr key={h.householdId}>
                      <td>{h.buildingName}</td>
                      <td>{unitLabel(h.floor, h.unitNo)}</td>
                      <td className="fu-num">{formatWon(h.total)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
