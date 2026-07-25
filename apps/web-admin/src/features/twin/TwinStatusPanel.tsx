"use client";

import { useEffect, useState } from "react";
import { Skeleton } from "@liviq/ui";
import {
  listAdminInquiries,
  listFacilities,
  type Facility,
  type FacilityStatus,
  type Inquiry,
  type TwinGeometryItem,
} from "@/lib/api";
import { occupancyMetrics } from "./twin-data";

// 현황판 라벨 — 서버 코드값을 사람이 읽는 문구로(폴백: 원문).
const INQUIRY_STATUS_LABELS: Record<string, string> = {
  received: "접수",
  assigned: "배정",
  in_progress: "처리중",
  done: "완료",
  reopened: "재접수",
};
const FACILITY_STATUS_LABELS: Record<FacilityStatus, string> = {
  normal: "정상",
  check: "점검",
  fault: "장애",
  risk: "위험",
};
// 심각도 정렬(문제 먼저) — 목록 상단에 이상 설비가 오게.
const FACILITY_SEVERITY: Record<FacilityStatus, number> = { risk: 3, fault: 2, check: 1, normal: 0 };
const RECENT_INQUIRY_LIMIT = 6;

function labelOf(map: Record<string, string>, key: string): string {
  return map[key] ?? key;
}

/** ISO → "MM-DD"(로케일 비의존). 잘못된 값은 원문 유지. */
function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${mm}-${dd}`;
}

interface TwinStatusPanelProps {
  geometry: TwinGeometryItem[];
  occupancy: Record<string, number>; // household_id → 세대원 수(입주율 계산)
}

// 민원·시설 목록은 기존 관리 API 재사용 — 트윈 전용 백엔드 없음(H9-4).
type ListState =
  | { kind: "loading" }
  | { kind: "error" }
  | { kind: "ready"; inquiries: Inquiry[]; facilities: Facility[] };

/**
 * 트윈 대시보드 현황판 — 타일(총세대·입주율·미처리민원·설비이상) + 최근민원 + 설비상태(H9-4).
 * 총세대·입주율은 트윈 geometry/occupancy 파생, 민원·설비는 listAdminInquiries·listFacilities 재사용.
 * 목록 로드 실패해도 타일(총세대·입주율)은 항상 보인다(비차단).
 */
export function TwinStatusPanel({ geometry, occupancy }: TwinStatusPanelProps) {
  const [state, setState] = useState<ListState>({ kind: "loading" });

  useEffect(() => {
    let alive = true;
    setState({ kind: "loading" });
    Promise.all([listAdminInquiries(), listFacilities()])
      .then(([inquiries, facilities]) => {
        if (alive) setState({ kind: "ready", inquiries, facilities });
      })
      .catch(() => {
        if (alive) setState({ kind: "error" });
      });
    return () => {
      alive = false;
    };
  }, []);

  const { total, occupancyRate } = occupancyMetrics(geometry, occupancy);

  const openInquiries =
    state.kind === "ready" ? state.inquiries.filter((i) => i.status !== "done").length : null;
  const facilityIssues =
    state.kind === "ready" ? state.facilities.filter((f) => f.status !== "normal").length : null;

  return (
    <aside className="twin-status" aria-label="단지 현황">
      <ul className="twin-tiles">
        <Tile label="총 세대" value={total} unit="세대" />
        <Tile label="입주율" value={occupancyRate} unit="%" />
        <Tile label="미처리 민원" value={openInquiries} unit="건" tone={openInquiries ? "warn" : undefined} />
        <Tile label="설비 이상" value={facilityIssues} unit="건" tone={facilityIssues ? "danger" : undefined} />
      </ul>

      <RecentInquiries state={state} />
      <FacilityStatusList state={state} />
    </aside>
  );
}

interface TileProps {
  label: string;
  value: number | null;
  unit: string;
  tone?: "warn" | "danger";
}

function Tile({ label, value, unit, tone }: TileProps) {
  return (
    <li className="twin-tile" data-tone={tone}>
      <span className="twin-tile__label">{label}</span>
      <span className="twin-tile__value">
        {value === null ? "–" : value}
        <span className="twin-tile__unit">{unit}</span>
      </span>
    </li>
  );
}

function RecentInquiries({ state }: { state: ListState }) {
  return (
    <section className="twin-status__section">
      <h3 className="twin-status__title">최근 민원</h3>
      {state.kind === "loading" ? (
        <Skeleton height="3.5rem" />
      ) : state.kind === "error" ? (
        <p className="twin-status__empty">민원을 불러오지 못했습니다.</p>
      ) : state.inquiries.length === 0 ? (
        <p className="twin-status__empty">접수된 민원이 없습니다.</p>
      ) : (
        <ul className="twin-status__list">
          {state.inquiries.slice(0, RECENT_INQUIRY_LIMIT).map((inq) => (
            <li key={inq.id} className="twin-status__row">
              <div className="twin-status__row-head">
                <span className="twin-pill" data-status={inq.status}>
                  {labelOf(INQUIRY_STATUS_LABELS, inq.status)}
                </span>
                <span className="twin-status__date">{shortDate(inq.createdAt)}</span>
              </div>
              <p className="twin-status__row-title">{inq.title}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FacilityStatusList({ state }: { state: ListState }) {
  return (
    <section className="twin-status__section">
      <h3 className="twin-status__title">설비 상태</h3>
      {state.kind === "loading" ? (
        <Skeleton height="3.5rem" />
      ) : state.kind === "error" ? (
        <p className="twin-status__empty">설비를 불러오지 못했습니다.</p>
      ) : state.facilities.length === 0 ? (
        <p className="twin-status__empty">등록된 설비가 없습니다.</p>
      ) : (
        <ul className="twin-status__facilities">
          {[...state.facilities]
            .sort((a, b) => FACILITY_SEVERITY[b.status] - FACILITY_SEVERITY[a.status])
            .map((f) => (
              <li key={f.id} className="twin-status__facility">
                <span className="twin-status-dot" data-status={f.status} aria-hidden="true" />
                <span className="twin-status__facility-name">{f.name}</span>
                <span className="twin-status__facility-state">
                  {labelOf(FACILITY_STATUS_LABELS, f.status)}
                </span>
              </li>
            ))}
        </ul>
      )}
    </section>
  );
}
