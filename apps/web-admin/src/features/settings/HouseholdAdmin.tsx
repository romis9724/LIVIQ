"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Dialog, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  createBuilding,
  createHouseholds,
  deleteBuilding,
  deleteHousehold,
  listBuildings,
  listHouseholds,
  updateBuilding,
  type Building,
  type Household,
} from "@/lib/api";
import { unitLabel } from "./households-data";
import { BuildingFormDialog, BulkHouseholdDialog } from "./HouseholdForms";
import type { BuildingFormValues, BulkHouseholdValues } from "./HouseholdForms";
import { GeometryUploadPanel } from "./GeometryUploadPanel";
import "./households.css";

const TOAST_DURATION_MS = 3200;

type ToastState = { message: string; tone: ToastTone };
type BuildingDialog = { mode: "create" | "edit"; building: Building | null };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function HouseholdAdmin() {
  const [buildings, setBuildings] = useState<Building[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [households, setHouseholds] = useState<Household[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [buildingDialog, setBuildingDialog] = useState<BuildingDialog | null>(null);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [deleteBuildingTarget, setDeleteBuildingTarget] = useState<Building | null>(null);
  const [deleteHouseholdTarget, setDeleteHouseholdTarget] = useState<Household | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const loadBuildings = useCallback(async () => {
    try {
      const items = await listBuildings();
      setBuildings(items);
      setLoadError(null);
      setSelectedId((prev) =>
        prev && items.some((b) => b.id === prev) ? prev : (items[0]?.id ?? null),
      );
    } catch (err) {
      setLoadError(errorMessage(err));
      setBuildings([]);
    }
  }, []);

  const loadHouseholds = useCallback(async (buildingId: string) => {
    setHouseholds(null);
    try {
      const result = await listHouseholds(buildingId);
      setHouseholds(result.items);
    } catch {
      setHouseholds([]);
    }
  }, []);

  useEffect(() => {
    void loadBuildings();
  }, [loadBuildings]);

  useEffect(() => {
    if (selectedId) void loadHouseholds(selectedId);
    else setHouseholds(null);
  }, [selectedId, loadHouseholds]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const selectedBuilding = buildings?.find((b) => b.id === selectedId) ?? null;

  async function submitBuilding(values: BuildingFormValues) {
    if (!buildingDialog) return;
    setBusy(true);
    try {
      if (buildingDialog.mode === "create") {
        const created = await createBuilding(values);
        setSelectedId(created.id);
        showToast("동을 추가했습니다.");
      } else if (buildingDialog.building) {
        await updateBuilding(buildingDialog.building.id, values);
        showToast("동을 수정했습니다.");
      }
      setBuildingDialog(null);
      await loadBuildings();
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function submitBulk(values: BulkHouseholdValues) {
    if (!selectedBuilding) return;
    setBusy(true);
    try {
      const result = await createHouseholds(selectedBuilding.id, values);
      setBulkOpen(false);
      const msg =
        result.skipped > 0
          ? `세대 ${result.created}개를 추가했습니다. (${result.skipped}개는 이미 있어 건너뜀)`
          : `세대 ${result.created}개를 추가했습니다.`;
      showToast(msg);
      await Promise.all([loadBuildings(), loadHouseholds(selectedBuilding.id)]);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteBuilding() {
    if (!deleteBuildingTarget) return;
    setBusy(true);
    try {
      await deleteBuilding(deleteBuildingTarget.id);
      setDeleteBuildingTarget(null);
      showToast("동을 삭제했습니다.", "neutral");
      await loadBuildings();
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDeleteHousehold() {
    if (!deleteHouseholdTarget || !selectedBuilding) return;
    setBusy(true);
    try {
      await deleteHousehold(deleteHouseholdTarget.id);
      setDeleteHouseholdTarget(null);
      showToast("세대를 삭제했습니다.", "neutral");
      await Promise.all([loadBuildings(), loadHouseholds(selectedBuilding.id)]);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          동/호수 관리
        </h1>
        <p className="admin-page__lede">
          단지의 동과 세대를 관리합니다. 세대는 층·호 범위로 한 번에 만들 수 있고, 입주민·명부·민원·관리비가
          연결된 세대는 삭제할 수 없습니다.
        </p>
      </header>

      <main className="admin-page__main">
        {loadError ? (
          <EmptyState icon="⚠" title="동 목록을 불러오지 못했습니다" description={loadError} />
        ) : buildings === null ? (
          <div className="hh-layout">
            <Skeleton height="320px" />
            <Skeleton height="320px" />
          </div>
        ) : buildings.length === 0 ? (
          <section className="surface-card hh-empty">
            <EmptyState
              icon="🏠"
              title="등록된 동이 없습니다"
              description="동을 추가하면 세대를 층·호 범위로 만들 수 있습니다."
            />
            <Button variant="primary" onClick={() => setBuildingDialog({ mode: "create", building: null })}>
              동 추가
            </Button>
          </section>
        ) : (
          <div className="hh-layout">
            <BuildingList
              buildings={buildings}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onAdd={() => setBuildingDialog({ mode: "create", building: null })}
            />
            <HouseholdPanel
              building={selectedBuilding}
              households={households}
              busy={busy}
              onEditBuilding={(b) => setBuildingDialog({ mode: "edit", building: b })}
              onDeleteBuilding={setDeleteBuildingTarget}
              onBulkCreate={() => setBulkOpen(true)}
              onDeleteHousehold={setDeleteHouseholdTarget}
            />
          </div>
        )}

        <GeometryUploadPanel />
      </main>

      {buildingDialog ? (
        <BuildingFormDialog
          mode={buildingDialog.mode}
          building={buildingDialog.building}
          busy={busy}
          onSubmit={submitBuilding}
          onCancel={() => setBuildingDialog(null)}
        />
      ) : null}

      {bulkOpen && selectedBuilding ? (
        <BulkHouseholdDialog
          buildingName={selectedBuilding.name}
          busy={busy}
          onSubmit={submitBulk}
          onCancel={() => setBulkOpen(false)}
        />
      ) : null}

      <Dialog
        open={deleteBuildingTarget !== null}
        title="동을 삭제할까요?"
        description={`${deleteBuildingTarget?.name ?? "이 동"}을(를) 삭제합니다. 소속 세대가 있으면 삭제할 수 없습니다.`}
        confirmLabel="삭제"
        cancelLabel="취소"
        danger
        onConfirm={() => void confirmDeleteBuilding()}
        onCancel={() => setDeleteBuildingTarget(null)}
      />

      <Dialog
        open={deleteHouseholdTarget !== null}
        title="세대를 삭제할까요?"
        description={
          deleteHouseholdTarget
            ? `${unitLabel(deleteHouseholdTarget.floor, deleteHouseholdTarget.unitNo)} 세대를 삭제합니다. 입주민·명부·민원·관리비가 연결돼 있으면 삭제할 수 없습니다.`
            : ""
        }
        confirmLabel="삭제"
        cancelLabel="취소"
        danger
        onConfirm={() => void confirmDeleteHousehold()}
        onCancel={() => setDeleteHouseholdTarget(null)}
      />

      {toast ? (
        <div className="hh-toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}

interface BuildingListProps {
  buildings: Building[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onAdd: () => void;
}

function BuildingList({ buildings, selectedId, onSelect, onAdd }: BuildingListProps) {
  return (
    <section className="surface-card hh-buildings" aria-labelledby="hh-buildings-h">
      <div className="hh-buildings__head">
        <h2 id="hh-buildings-h" className="hh-panel__title">
          동
        </h2>
        <Button variant="secondary" size="sm" onClick={onAdd}>
          동 추가
        </Button>
      </div>
      <ul className="hh-buildings__list">
        {buildings.map((building) => (
          <li key={building.id}>
            <button
              type="button"
              className="hh-building"
              data-active={building.id === selectedId || undefined}
              aria-current={building.id === selectedId || undefined}
              onClick={() => onSelect(building.id)}
            >
              <span className="hh-building__name">{building.name}</span>
              <span className="hh-building__meta">
                {building.floors != null ? `${building.floors}층` : "층수 미지정"}
              </span>
              <span className="hh-building__count">{building.householdCount}세대</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

interface HouseholdPanelProps {
  building: Building | null;
  households: Household[] | null;
  busy: boolean;
  onEditBuilding: (building: Building) => void;
  onDeleteBuilding: (building: Building) => void;
  onBulkCreate: () => void;
  onDeleteHousehold: (household: Household) => void;
}

function HouseholdPanel({
  building,
  households,
  busy,
  onEditBuilding,
  onDeleteBuilding,
  onBulkCreate,
  onDeleteHousehold,
}: HouseholdPanelProps) {
  if (!building) {
    return (
      <section className="surface-card hh-households" aria-labelledby="hh-households-h">
        <h2 id="hh-households-h" className="hh-panel__title">
          세대
        </h2>
        <EmptyState icon="👈" title="동을 선택하세요" description="왼쪽에서 동을 선택하면 세대가 표시됩니다." />
      </section>
    );
  }

  return (
    <section className="surface-card hh-households" aria-labelledby="hh-households-h">
      <div className="hh-households__head">
        <h2 id="hh-households-h" className="hh-panel__title">
          {building.name} 세대
        </h2>
        <div className="hh-households__actions">
          <Button variant="primary" size="sm" onClick={onBulkCreate}>
            세대 추가
          </Button>
          <Button variant="ghost" size="sm" onClick={() => onEditBuilding(building)}>
            동 수정
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="hh-danger"
            disabled={busy}
            onClick={() => onDeleteBuilding(building)}
          >
            동 삭제
          </Button>
        </div>
      </div>

      {households === null ? (
        <Skeleton height="200px" />
      ) : households.length === 0 ? (
        <EmptyState icon="🏷" title="세대가 없습니다" description="‘세대 추가’로 층·호 범위를 한 번에 만드세요." />
      ) : (
        <ul className="hh-grid">
          {households.map((household) => (
            <li key={household.id} className="hh-cell" data-inactive={household.status !== "active" || undefined}>
              <span className="hh-cell__label">{unitLabel(household.floor, household.unitNo)}</span>
              <div className="hh-cell__actions">
                <Button
                  variant="ghost"
                  size="sm"
                  className="hh-danger"
                  disabled={busy}
                  onClick={() => onDeleteHousehold(household)}
                  aria-label={`${unitLabel(household.floor, household.unitNo)} 삭제`}
                >
                  삭제
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
