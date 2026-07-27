"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  Button,
  EmptyState,
  PageToolbar,
  Pagination,
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
import { usePaging } from "@/lib/paging";
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

  // 조회 결과 전량을 받아 클라이언트 페이징 — 조회 조건이 바뀌면 1페이지로 되돌린다.
  const paging = usePaging(data?.households ?? []);

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
    paging.reset();
    if (nextBuilding === building && nextUnit === unit) void load();
  }

  const isEmpty = data !== null && data.householdCount === 0;
  // 현황 → 조회 조건 → 목록 순서(docs/05 §5A) — 목록 뷰에서 결과가 있을 때만 현황을 얹는다.
  const showSummary = view === "list" && !loading && !loadError && data !== null && !isEmpty;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          관리비 관리
        </h1>
      </header>

      <main className="admin-page__main">
        {showSummary && data ? (
          <StatGrid className="fu-stats">
            <StatCard label="세대 수" value={data.householdCount} unit="세대" />
            <StatCard label="합계" value={formatWon(data.totalSum)} />
          </StatGrid>
        ) : null}

        <PageToolbar
          start={
            view === "list" ? (
              <form className="fu-filters" onSubmit={onSearch}>
                <input
                  id="fu-month"
                  type="month"
                  aria-label="조회 월"
                  value={period}
                  onChange={(e) => {
                    setPeriod(e.target.value);
                    paging.reset();
                  }}
                />
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
            <div className="surface-card admin-tablecard fu-loading">
              <Skeleton height="1.5rem" />
              <Skeleton height="1.5rem" />
              <Skeleton height="1.5rem" />
            </div>
          )
        ) : (
          <div className="fu-status">
            {loading ? (
              <div className="surface-card admin-tablecard fu-loading">
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
              <section aria-label="동/호별 관리비">
                <div className="surface-card admin-tablecard">
                  <table className="admin-table fu-table">
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
                      {paging.rows.map((h) => (
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
                  {paging.totalPages > 1 ? (
                    <Pagination
                      page={paging.page}
                      totalPages={paging.totalPages}
                      totalCount={data.households.length}
                      onPage={paging.setPage}
                      label="세대 목록 페이지"
                    />
                  ) : null}
                </div>
              </section>
            )}
          </div>
        )}
      </main>
    </>
  );
}
