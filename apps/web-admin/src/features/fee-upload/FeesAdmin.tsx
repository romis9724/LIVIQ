"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  EmptyState,
  PageToolbar,
  SearchField,
  Skeleton,
  StatCard,
  StatGrid,
} from "@liviq/ui";
import {
  ApiError,
  getAdminFeeDetail,
  listAdminFees,
  type AdminFeeDetail,
  type AdminFeeList,
} from "@/lib/api";
import { UploadWizard } from "./UploadWizard";
import { FeeInvoice } from "./FeeInvoice";
import { formatWon, monthLabel, unitLabel } from "./logic";
import "./fee-upload.css";

type View = "list" | "detail" | "upload";

/** 이번 달(YYYY-MM). 기본 조회 월. */
function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function FeesAdmin() {
  const [view, setView] = useState<View>("list");
  const [period, setPeriod] = useState<string>(currentMonth());
  // 동·호는 조회 버튼(제출) 때만 반영 — 입력은 uncontrolled(ref)로 둔다(IME·리렌더 방지).
  const buildingRef = useRef<HTMLInputElement>(null);
  const unitRef = useRef<HTMLInputElement>(null);
  const [building, setBuilding] = useState("");
  const [unit, setUnit] = useState("");
  const [data, setData] = useState<AdminFeeList | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [detail, setDetail] = useState<AdminFeeDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const unitNo = unit.trim() ? Number(unit.trim()) : undefined;
      const res = await listAdminFees(period, {
        building: building.trim() || undefined,
        unit: Number.isNaN(unitNo as number) ? undefined : unitNo,
      });
      setData(res);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [period, building, unit]);

  useEffect(() => {
    if (view === "list") void load();
  }, [view, load]);

  async function openDetail(householdId: string, label: string) {
    setDetail(null);
    setDetailError(null);
    setView("detail");
    try {
      setDetail(await getAdminFeeDetail(householdId, period));
    } catch (err) {
      setDetailError(`${label} 고지서를 불러오지 못했습니다 — ${errorMessage(err)}`);
    }
  }

  // 제출 때 ref 값을 조회 조건으로 승격 — 값이 바뀌면 load 이펙트가 다시 돈다.
  function onSearch(e: React.FormEvent) {
    e.preventDefault();
    const nextBuilding = buildingRef.current?.value.trim() ?? "";
    const nextUnit = unitRef.current?.value.trim() ?? "";
    setBuilding(nextBuilding);
    setUnit(nextUnit);
    if (nextBuilding === building && nextUnit === unit) void load();
  }

  const isEmpty = data !== null && data.householdCount === 0;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          관리비 관리
        </h1>
      </header>

      <main className="admin-page__main">
        <PageToolbar
          start={
            view === "list" ? (
              <form className="fu-filters" onSubmit={onSearch}>
                <label className="fu-filter" htmlFor="fu-month">
                  <span className="fu-filter__label">조회 월</span>
                  <input
                    id="fu-month"
                    type="month"
                    value={period}
                    onChange={(e) => setPeriod(e.target.value)}
                  />
                </label>
                <SearchField
                  ref={buildingRef}
                  label="동 검색"
                  placeholder="동 (예: 401)"
                  inputMode="numeric"
                  className="fu-filters__q"
                  defaultValue={building}
                />
                <SearchField
                  ref={unitRef}
                  label="호 검색"
                  placeholder="호 (예: 201)"
                  inputMode="numeric"
                  className="fu-filters__q"
                  defaultValue={unit}
                />
                <Button type="submit" variant="secondary">
                  조회
                </Button>
              </form>
            ) : null
          }
          end={
            view === "list" ? (
              <Button variant="primary" onClick={() => setView("upload")}>
                엑셀 등록
              </Button>
            ) : (
              <Button variant="secondary" onClick={() => setView("list")}>
                ← 목록으로
              </Button>
            )
          }
        />

        {view === "upload" ? (
          <UploadWizard onApplied={() => setView("list")} />
        ) : view === "detail" ? (
          detailError ? (
            <EmptyState icon="⚠" title="고지서를 불러오지 못했습니다" description={detailError} />
          ) : detail ? (
            <FeeInvoice
              breakdown={detail.breakdown}
              total={detail.total}
              caption={`${detail.buildingName}동 ${unitLabel(detail.floor, detail.unitNo)} · ${monthLabel(detail.period)}`}
            />
          ) : (
            <div className="surface-card fu-tablecard fu-loading">
              <Skeleton height="1.5rem" />
              <Skeleton height="1.5rem" />
              <Skeleton height="1.5rem" />
            </div>
          )
        ) : (
          <div className="fu-status">
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
                action={<Button onClick={() => void load()}>다시 시도</Button>}
              />
            ) : isEmpty || data === null ? (
              <EmptyState
                icon="📄"
                title="해당 조건의 관리비가 없습니다"
                description={`${monthLabel(period)} 관리비가 아직 없거나 검색 조건에 맞는 세대가 없습니다. 엑셀 등록으로 반영하세요.`}
              />
            ) : (
              <>
                <StatGrid>
                  <StatCard label="세대 수" value={data.householdCount} unit="세대" />
                  <StatCard label="합계" value={formatWon(data.totalSum)} />
                </StatGrid>

                <section aria-labelledby="fu-lookup-title">
                  <h2 id="fu-lookup-title" className="fu-section__title">
                    동/호별 관리비
                  </h2>
                  <div className="surface-card fu-tablecard">
                    <table className="fu-table">
                      <thead>
                        <tr>
                          <th scope="col">동</th>
                          <th scope="col">호</th>
                          <th scope="col" className="fu-num">
                            당월 고지금액
                          </th>
                          <th scope="col">
                            <span className="sr-only">고지서</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.households.map((h) => (
                          <tr key={h.householdId}>
                            <td>{h.buildingName}</td>
                            <td>{unitLabel(h.floor, h.unitNo)}</td>
                            <td className="fu-num">{formatWon(h.total)}</td>
                            <td className="fu-num">
                              <button
                                type="button"
                                className="fu-link"
                                onClick={() =>
                                  void openDetail(
                                    h.householdId,
                                    `${h.buildingName}동 ${unitLabel(h.floor, h.unitNo)}`,
                                  )
                                }
                              >
                                고지서 →
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </>
            )}
          </div>
        )}
      </main>
    </>
  );
}
