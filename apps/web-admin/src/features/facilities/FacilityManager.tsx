"use client";

import { Button, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createFacility,
  createIncident,
  createMaintenance,
  getFacility,
  listFacilities,
  patchFacility,
  type Facility,
  type FacilityCreateInput,
  type FacilityDetail,
  type FacilityStatus,
  type IncidentInput,
  type MaintenanceInput,
} from "@/lib/api";
import { FacilityAssistantPanel } from "./FacilityAssistantPanel";
import { IncidentDialog, MaintenanceDialog, RegisterDialog } from "./FacilityDialogs";
import { FILTERS, STATUS_META, STATUS_ORDER, countByStatus, shortDate, type FilterId } from "./data";
import "./facilities.css";

const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

type DialogKind = "register" | "incident" | "maintenance" | null;

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function FacilityManager() {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterId>("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FacilityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [dialog, setDialog] = useState<DialogKind>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const loadList = useCallback(async (keepSelection?: string) => {
    setLoading(true);
    try {
      const items = await listFacilities();
      setFacilities(items);
      setLoadError(null);
      setSelectedId((prev) => keepSelection ?? prev ?? items[0]?.id ?? null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    try {
      setDetail(await getFacility(id));
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setDetailLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
    else setDetail(null);
  }, [selectedId, loadDetail]);

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const counts = countByStatus(facilities);
  const visible =
    filter === "all" ? facilities : facilities.filter((f) => f.status === filter);

  async function handleRegister(input: FacilityCreateInput) {
    setBusy(true);
    try {
      const created = await createFacility(input);
      setDialog(null);
      await loadList(created.id);
      showToast("설비를 등록했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function handleStatusChange(status: FacilityStatus) {
    if (!detail) return;
    setBusy(true);
    try {
      await patchFacility(detail.id, { status });
      await Promise.all([loadDetail(detail.id), loadList(detail.id)]);
      showToast(`상태를 '${STATUS_META[status].label}'(으)로 변경했습니다.`);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function handleIncident(input: IncidentInput) {
    if (!detail) return;
    setBusy(true);
    try {
      await createIncident(detail.id, input);
      setDialog(null);
      await loadDetail(detail.id);
      showToast("장애를 기록했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function handleMaintenance(input: MaintenanceInput) {
    if (!detail) return;
    setBusy(true);
    try {
      await createMaintenance(detail.id, input);
      setDialog(null);
      await loadDetail(detail.id);
      showToast("정비를 기록했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="admin-page__header fac-head">
        <div className="fac-head__text">
          <h1 id="main" className="admin-page__title">
            시설 관리
          </h1>
          <p className="admin-page__lede">
            단지 시설의 운영 상태와 장애·정비 이력을 관리합니다. 상태 변경·기록은 담당자가 직접
            수행합니다.
          </p>
        </div>
        <Button variant="primary" onClick={() => setDialog("register")}>
          설비 등록
        </Button>
      </header>

      <div className="fac-filters" role="tablist" aria-label="상태 필터">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            role="tab"
            aria-selected={filter === f.id}
            className="fac-filter"
            data-active={filter === f.id || undefined}
            onClick={() => setFilter(f.id)}
          >
            {f.label} <span className="fac-filter__count">{counts[f.id]}</span>
          </button>
        ))}
      </div>

      <main className="fac-main">
        <div className="fac-list">
          {loading ? (
            <>
              <Skeleton height="4.5rem" />
              <Skeleton height="4.5rem" />
            </>
          ) : loadError ? (
            <EmptyState
              icon="⚠"
              title="시설 목록을 불러오지 못했습니다"
              description={loadError}
              action={<Button onClick={() => void loadList()}>다시 시도</Button>}
            />
          ) : visible.length === 0 ? (
            <EmptyState
              icon="🏗"
              title="시설이 없습니다"
              description="‘설비 등록’으로 첫 시설을 추가하세요."
            />
          ) : (
            visible.map((f) => (
              <button
                key={f.id}
                type="button"
                className="fac-card"
                aria-pressed={selectedId === f.id}
                data-active={selectedId === f.id || undefined}
                onClick={() => setSelectedId(f.id)}
              >
                <span className="fac-card__icon" aria-hidden="true">
                  {STATUS_META[f.status].icon}
                </span>
                <span className="fac-card__body">
                  <span className="fac-card__name">{f.name}</span>
                  <span className="fac-card__meta">
                    {f.location ?? "위치 미지정"} · 다음 점검 {shortDate(f.nextCheckAt)}
                  </span>
                </span>
                <span className={`fac-pill fac-pill--${STATUS_META[f.status].css}`}>
                  <span
                    className={`fac-dot fac-dot--${STATUS_META[f.status].css}`}
                    aria-hidden="true"
                  />
                  {STATUS_META[f.status].label}
                </span>
              </button>
            ))
          )}
        </div>

        <FacilityDetailPanel
          detail={detail}
          loading={detailLoading}
          busy={busy}
          onStatusChange={handleStatusChange}
          onRecordIncident={() => setDialog("incident")}
          onRecordMaintenance={() => setDialog("maintenance")}
        />
      </main>

      <FacilityAssistantPanel />

      {dialog === "register" ? (
        <RegisterDialog busy={busy} onCancel={() => setDialog(null)} onSubmit={handleRegister} />
      ) : null}
      {dialog === "incident" && detail ? (
        <IncidentDialog
          facilityName={detail.name}
          busy={busy}
          onCancel={() => setDialog(null)}
          onSubmit={handleIncident}
        />
      ) : null}
      {dialog === "maintenance" && detail ? (
        <MaintenanceDialog
          facilityName={detail.name}
          busy={busy}
          onCancel={() => setDialog(null)}
          onSubmit={handleMaintenance}
        />
      ) : null}

      {toast ? (
        <div className="fac-toast">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}

interface DetailPanelProps {
  detail: FacilityDetail | null;
  loading: boolean;
  busy: boolean;
  onStatusChange: (status: FacilityStatus) => void;
  onRecordIncident: () => void;
  onRecordMaintenance: () => void;
}

function FacilityDetailPanel({
  detail,
  loading,
  busy,
  onStatusChange,
  onRecordIncident,
  onRecordMaintenance,
}: DetailPanelProps) {
  if (loading && !detail) {
    return (
      <aside className="fac-detail">
        <Skeleton height="6rem" />
        <Skeleton height="10rem" />
      </aside>
    );
  }
  if (!detail) {
    return (
      <aside className="fac-detail">
        <EmptyState icon="👈" title="시설을 선택하세요" description="왼쪽 목록에서 설비를 선택합니다." />
      </aside>
    );
  }

  const meta = STATUS_META[detail.status];

  return (
    <aside className="fac-detail">
      <div>
        <div className="fac-detail__head">
          <span className="fac-detail__icon" data-status={meta.css} aria-hidden="true">
            {meta.icon}
          </span>
          <div>
            <div className="fac-detail__name">{detail.name}</div>
            <span className={`fac-pill fac-pill--${meta.css}`}>
              <span className={`fac-dot fac-dot--${meta.css}`} aria-hidden="true" />
              {meta.label}
            </span>
          </div>
        </div>
        <p className="fac-detail__desc">
          {detail.type ? `${detail.type} · ` : ""}
          {detail.location ?? "위치 미지정"} · 다음 점검 {shortDate(detail.nextCheckAt)}
        </p>
      </div>

      <div className="fac-statusbar" role="group" aria-label="상태 변경">
        <span className="fac-statusbar__label">상태 변경</span>
        <div className="fac-statusbar__opts">
          {STATUS_ORDER.map((s) => (
            <button
              key={s}
              type="button"
              className="fac-statusbtn"
              data-active={detail.status === s || undefined}
              disabled={busy || detail.status === s}
              onClick={() => onStatusChange(s)}
            >
              {STATUS_META[s].label}
            </button>
          ))}
        </div>
      </div>

      <HistorySection
        title="장애 이력"
        empty="기록된 장애가 없습니다."
        items={detail.incidents.map((i) => ({
          id: i.id,
          date: shortDate(i.occurredAt),
          primary: i.symptom,
          secondary: i.resolution ? `조치: ${i.resolution}` : null,
        }))}
      />
      <HistorySection
        title="정비 이력"
        empty="기록된 정비가 없습니다."
        items={detail.maintenanceLogs.map((m) => ({
          id: m.id,
          date: shortDate(m.performedAt),
          primary: m.work,
          secondary: m.performer ? `작업자: ${m.performer}` : null,
        }))}
      />

      <div className="fac-detail__actions">
        <Button variant="primary" disabled={busy} onClick={onRecordIncident}>
          장애 기록
        </Button>
        <Button variant="secondary" disabled={busy} onClick={onRecordMaintenance}>
          정비 기록
        </Button>
      </div>
    </aside>
  );
}

interface HistoryItem {
  id: string;
  date: string;
  primary: string;
  secondary: string | null;
}

function HistorySection({
  title,
  empty,
  items,
}: {
  title: string;
  empty: string;
  items: HistoryItem[];
}) {
  return (
    <section className="fac-history">
      <div className="fac-history__title">{title}</div>
      {items.length === 0 ? (
        <p className="fac-history__empty">{empty}</p>
      ) : (
        <ol className="fac-history__list">
          {items.map((item) => (
            <li key={item.id} className="fac-history__item">
              <span className="fac-history__date">{item.date}</span>
              <div className="fac-history__body">
                <div className="fac-history__primary">{item.primary}</div>
                {item.secondary ? (
                  <div className="fac-history__secondary">{item.secondary}</div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
