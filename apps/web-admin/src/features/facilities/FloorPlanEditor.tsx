"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { Button, Dialog, EmptyState, FormField, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  getFloorPlan,
  listFacilities,
  saveFloorPlanDevices,
  type AdminFloorPlanDevice,
  type AdminFloorPlanItem,
  type Facility,
  type FloorPlanDeviceInput,
} from "@/lib/api";
import {
  DIR_OPTIONS,
  categoryColorVar,
  deviceCategory,
  distinctNonEmpty,
  markerLabel,
  pixelFromClick,
  toPercent,
} from "./floor-plan-admin-data";
import "./facilities.css";

const TOAST_DURATION_MS = 3200;

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface EditableDevice {
  id: string;
  deviceType: string;
  x: number;
  y: number;
  room: string;
  dir: string;
  label: string;
  memo: string;
  facilityId: string;
}

function fromServerDevice(raw: AdminFloorPlanDevice): EditableDevice {
  return {
    id: raw.id,
    deviceType: raw.deviceType,
    x: raw.x,
    y: raw.y,
    room: raw.room ?? "",
    dir: raw.dir ?? "",
    label: raw.label ?? "",
    memo: raw.memo ?? "",
    facilityId: raw.facilityId ?? "",
  };
}

function toDeviceInput(device: EditableDevice): FloorPlanDeviceInput {
  return {
    deviceType: device.deviceType.trim(),
    x: device.x,
    y: device.y,
    room: device.room.trim() || undefined,
    dir: device.dir || undefined,
    label: device.label.trim() || undefined,
    memo: device.memo.trim() || undefined,
    facilityId: device.facilityId || undefined,
  };
}

let tempSeq = 0;
function nextTempId(): string {
  tempSeq += 1;
  return `new-${tempSeq}`;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; plan: AdminFloorPlanItem };

interface FloorPlanEditorProps {
  planId: string;
  onBack: () => void;
  onSaved: () => void;
}

/**
 * 도면 캔버스(클릭=마커 추가) + 우측 편집 폼. 저장은 명시적 버튼 → PUT 전체 교체(자동저장 아님).
 * 성공/실패 토스트는 이 컴포넌트가 직접 띄운다 — 부모(FloorPlanManager)의 토스트는 목록 화면에서만
 * 렌더되어 편집기가 떠 있는 동안엔 보이지 않는다.
 */
export function FloorPlanEditor({ planId, onBack, onSaved }: FloorPlanEditorProps) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const [devices, setDevices] = useState<EditableDevice[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [confirmBack, setConfirmBack] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone: ToastTone } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const canvasRef = useRef<HTMLDivElement>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  useEffect(() => {
    let alive = true;
    setState({ kind: "loading" });
    getFloorPlan(planId)
      .then((detail) => {
        if (!alive) return;
        if (!detail) {
          setState({ kind: "error", message: "평면도를 찾을 수 없습니다." });
          return;
        }
        setState({ kind: "ready", plan: detail.plan });
        setDevices(detail.devices.map(fromServerDevice));
        setSelectedId(null);
        setDirty(false);
      })
      .catch((err) => alive && setState({ kind: "error", message: errorMessage(err) }));
    return () => {
      alive = false;
    };
  }, [planId]);

  useEffect(() => {
    listFacilities()
      .then(setFacilities)
      .catch(() => setFacilities([]));
  }, []);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const roomOptions = useMemo(() => distinctNonEmpty(devices.map((d) => d.room)), [devices]);
  const typeOptions = useMemo(() => distinctNonEmpty(devices.map((d) => d.deviceType)), [devices]);

  function handleCanvasClick(event: MouseEvent<HTMLDivElement>) {
    if (state.kind !== "ready") return;
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    const { x, y } = pixelFromClick(
      event.clientX - rect.left,
      event.clientY - rect.top,
      rect.width,
      rect.height,
      state.plan.imageWidth,
      state.plan.imageHeight,
    );
    const created: EditableDevice = {
      id: nextTempId(),
      deviceType: "",
      x,
      y,
      room: "",
      dir: "",
      label: "",
      memo: "",
      facilityId: "",
    };
    setDevices((prev) => [...prev, created]);
    setSelectedId(created.id);
    setDirty(true);
  }

  function updateSelected(patch: Partial<EditableDevice>) {
    setDevices((prev) => prev.map((d) => (d.id === selectedId ? { ...d, ...patch } : d)));
    setDirty(true);
  }

  function handleDelete() {
    setDevices((prev) => prev.filter((d) => d.id !== selectedId));
    setSelectedId(null);
    setDirty(true);
  }

  async function handleSave() {
    setSaving(true);
    try {
      await saveFloorPlanDevices(planId, devices.map(toDeviceInput));
      setDirty(false);
      showToast("저장했습니다.");
      onSaved();
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setSaving(false);
    }
  }

  function handleBackClick() {
    if (dirty) setConfirmBack(true);
    else onBack();
  }

  if (state.kind === "loading") {
    return (
      <>
        <Skeleton height="2rem" />
        <Skeleton height="24rem" />
      </>
    );
  }

  if (state.kind === "error") {
    return (
      <EmptyState
        icon="⚠"
        title="평면도를 불러오지 못했습니다"
        description={state.message}
        action={
          <Button variant="secondary" onClick={onBack}>
            목록으로
          </Button>
        }
      />
    );
  }

  const { plan } = state;
  const selected = devices.find((d) => d.id === selectedId) ?? null;
  const canSave = devices.every((d) => d.deviceType.trim() !== "");

  return (
    <>
      <header className="admin-page__header fp-editor-head">
        <div className="fac-head__text">
          <button type="button" className="btn btn--secondary btn--sm fp-back" onClick={handleBackClick}>
            ← 목록으로
          </button>
          <h1 id="main" className="admin-page__title">
            {plan.unitTypeName} 평면도 편집
          </h1>
          <p className="admin-page__lede">
            도면을 클릭해 마커를 추가하고, 마커를 클릭해 정보를 편집합니다.
          </p>
        </div>
        <div className="fp-editor-actions">
          {!canSave ? <span className="fp-editor-hint">모든 마커에 종류를 입력하세요.</span> : null}
          <Button variant="primary" disabled={!dirty || saving || !canSave} onClick={() => void handleSave()}>
            {saving ? "저장 중…" : "저장"}
          </Button>
        </div>
      </header>

      <div className="fp-editor">
        <div className="fp-canvas-wrap">
          <div
            className="fp-canvas"
            ref={canvasRef}
            onClick={handleCanvasClick}
            role="group"
            aria-label="평면도 편집 캔버스 — 클릭해 마커 추가"
          >
            {/* eslint-disable-next-line @next/next/no-img-element -- 서명 URL(외부 오리진) */}
            <img
              src={plan.imageUrl}
              alt={`${plan.unitTypeName} 평면도`}
              className="fp-canvas__image"
              width={plan.imageWidth}
              height={plan.imageHeight}
            />
            {devices.map((d) => (
              <button
                key={d.id}
                type="button"
                className="fp-marker"
                aria-label={markerLabel({
                  room: d.room || null,
                  deviceType: d.deviceType || "미지정",
                  label: d.label || null,
                })}
                aria-pressed={selectedId === d.id}
                data-selected={selectedId === d.id || undefined}
                style={{
                  left: `${toPercent(d.x, plan.imageWidth)}%`,
                  top: `${toPercent(d.y, plan.imageHeight)}%`,
                  backgroundColor: `var(${categoryColorVar(deviceCategory(d.deviceType))})`,
                }}
                onClick={(e) => {
                  e.stopPropagation();
                  setSelectedId(d.id);
                }}
              />
            ))}
          </div>
        </div>

        <DeviceForm
          key={selectedId ?? "none"}
          device={selected}
          typeOptions={typeOptions}
          roomOptions={roomOptions}
          facilities={facilities}
          onChange={updateSelected}
          onDelete={handleDelete}
        />
      </div>

      <Dialog
        open={confirmBack}
        title="저장하지 않고 나가시겠어요?"
        description="변경한 마커 정보가 저장되지 않습니다."
        confirmLabel="나가기"
        danger
        onConfirm={() => {
          setConfirmBack(false);
          onBack();
        }}
        onCancel={() => setConfirmBack(false)}
      />

      {toast ? (
        <div className="fac-toast">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}

const TYPE_LIST_ID = "fp-device-type-options";
const ROOM_LIST_ID = "fp-device-room-options";

interface DeviceFormProps {
  device: EditableDevice | null;
  typeOptions: readonly string[];
  roomOptions: readonly string[];
  facilities: readonly Facility[];
  onChange: (patch: Partial<EditableDevice>) => void;
  onDelete: () => void;
}

/** 우측 마커 편집 폼 — key={선택 id}로 부모가 리마운트해 defaultValue를 초기화한다(uncontrolled). */
function DeviceForm({ device, typeOptions, roomOptions, facilities, onChange, onDelete }: DeviceFormProps) {
  if (!device) {
    return (
      <aside className="fac-detail fp-form">
        <EmptyState
          icon="👈"
          title="마커를 선택하세요"
          description="도면을 클릭해 마커를 추가하거나 기존 마커를 클릭하세요."
        />
      </aside>
    );
  }

  return (
    <aside className="fac-detail fp-form">
      <FormField
        label="종류"
        defaultValue={device.deviceType}
        list={TYPE_LIST_ID}
        placeholder="예: 콘센트"
        onChange={(e) => onChange({ deviceType: e.target.value })}
      />
      <datalist id={TYPE_LIST_ID}>
        {typeOptions.map((t) => (
          <option key={t} value={t} />
        ))}
      </datalist>

      <FormField
        label="방 (선택)"
        defaultValue={device.room}
        list={ROOM_LIST_ID}
        placeholder="예: 거실"
        onChange={(e) => onChange({ room: e.target.value })}
      />
      <datalist id={ROOM_LIST_ID}>
        {roomOptions.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>

      <label className="fac-field">
        <span className="form-field__label">방향 (선택)</span>
        <select
          className="fac-select"
          defaultValue={device.dir}
          onChange={(e) => onChange({ dir: e.target.value })}
        >
          {DIR_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <FormField
        label="라벨 (선택)"
        defaultValue={device.label}
        placeholder="예: 냉장고용"
        onChange={(e) => onChange({ label: e.target.value })}
      />

      <label className="fac-field">
        <span className="form-field__label">비고 (선택)</span>
        <textarea
          className="fac-textarea"
          rows={2}
          defaultValue={device.memo}
          placeholder="예: 누전 주의"
          onChange={(e) => onChange({ memo: e.target.value })}
        />
      </label>

      <label className="fac-field">
        <span className="form-field__label">연결 설비 (선택)</span>
        <select
          className="fac-select"
          defaultValue={device.facilityId}
          onChange={(e) => onChange({ facilityId: e.target.value })}
        >
          <option value="">연결 안 함</option>
          {facilities.map((f) => (
            <option key={f.id} value={f.id}>
              {f.name}
            </option>
          ))}
        </select>
      </label>

      <div className="fac-detail__actions">
        <Button variant="secondary" onClick={onDelete}>
          마커 삭제
        </Button>
      </div>
    </aside>
  );
}
