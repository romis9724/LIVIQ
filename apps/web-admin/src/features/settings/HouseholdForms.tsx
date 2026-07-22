"use client";

import { useEffect, useId, useState } from "react";
import { Button, FormField } from "@liviq/ui";
import type { Building } from "@/lib/api";
import { countCombos, previewLabels, validateRange } from "./households-data";

/** 폼 모달 셸 — 백드롭/Escape 처리(codes.css 패턴 재사용). */
function FormModal({
  title,
  onCancel,
  children,
}: {
  title: string;
  onCancel: () => void;
  children: React.ReactNode;
}) {
  const titleId = useId();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="hh-modal" onClick={onCancel}>
      <div
        className="hh-modal__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="hh-modal__title" id={titleId}>
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

export interface BuildingFormValues {
  name: string;
  floors: number | null;
}

interface BuildingFormDialogProps {
  mode: "create" | "edit";
  building: Building | null;
  busy: boolean;
  onSubmit: (values: BuildingFormValues) => void;
  onCancel: () => void;
}

export function BuildingFormDialog({
  mode,
  building,
  busy,
  onSubmit,
  onCancel,
}: BuildingFormDialogProps) {
  const [name, setName] = useState(building?.name ?? "");
  const [floors, setFloors] = useState(building?.floors != null ? String(building.floors) : "");
  const [nameError, setNameError] = useState<string | undefined>();

  function submit() {
    const trimmed = name.trim();
    if (!trimmed) {
      setNameError("동 이름을 입력해 주세요.");
      return;
    }
    const parsed = Number.parseInt(floors, 10);
    onSubmit({ name: trimmed, floors: Number.isFinite(parsed) ? parsed : null });
  }

  return (
    <FormModal title={mode === "create" ? "동 추가" : "동 수정"} onCancel={onCancel}>
      <form
        className="hh-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        noValidate
      >
        <FormField
          autoFocus
          label="동 이름"
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setNameError(undefined);
          }}
          error={nameError}
          placeholder="예: 101"
          autoComplete="off"
        />
        <FormField
          label="층수 (선택)"
          type="number"
          inputMode="numeric"
          value={floors}
          onChange={(e) => setFloors(e.target.value)}
          help="이 동의 총 층수. 비워 두면 미지정."
          placeholder="15"
        />
        <div className="hh-form__actions">
          <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
            취소
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={busy}>
            {busy ? "저장 중…" : "저장"}
          </Button>
        </div>
      </form>
    </FormModal>
  );
}

export interface BulkHouseholdValues {
  floorStart: number;
  floorEnd: number;
  unitStart: number;
  unitEnd: number;
}

interface BulkHouseholdDialogProps {
  buildingName: string;
  busy: boolean;
  onSubmit: (values: BulkHouseholdValues) => void;
  onCancel: () => void;
}

export function BulkHouseholdDialog({
  buildingName,
  busy,
  onSubmit,
  onCancel,
}: BulkHouseholdDialogProps) {
  const [floorStart, setFloorStart] = useState("1");
  const [floorEnd, setFloorEnd] = useState("1");
  const [unitStart, setUnitStart] = useState("1");
  const [unitEnd, setUnitEnd] = useState("1");

  const range = {
    floorStart: Number.parseInt(floorStart, 10),
    floorEnd: Number.parseInt(floorEnd, 10),
    unitStart: Number.parseInt(unitStart, 10),
    unitEnd: Number.parseInt(unitEnd, 10),
  };
  const error = validateRange(range);
  const total = countCombos(range);
  const preview = error ? [] : previewLabels(range);

  function submit() {
    if (error) return;
    onSubmit(range);
  }

  return (
    <FormModal title={`${buildingName} — 세대 일괄 생성`} onCancel={onCancel}>
      <form
        className="hh-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        noValidate
      >
        <div className="hh-range">
          <FormField
            autoFocus
            label="시작 층"
            type="number"
            inputMode="numeric"
            value={floorStart}
            onChange={(e) => setFloorStart(e.target.value)}
          />
          <span className="hh-range__sep" aria-hidden="true">
            ~
          </span>
          <FormField
            label="끝 층"
            type="number"
            inputMode="numeric"
            value={floorEnd}
            onChange={(e) => setFloorEnd(e.target.value)}
          />
        </div>
        <div className="hh-range">
          <FormField
            label="시작 호"
            type="number"
            inputMode="numeric"
            value={unitStart}
            onChange={(e) => setUnitStart(e.target.value)}
          />
          <span className="hh-range__sep" aria-hidden="true">
            ~
          </span>
          <FormField
            label="끝 호"
            type="number"
            inputMode="numeric"
            value={unitEnd}
            onChange={(e) => setUnitEnd(e.target.value)}
          />
        </div>

        {error ? (
          <p className="hh-form__error" role="alert">
            {error}
          </p>
        ) : (
          <div className="hh-preview" aria-live="polite">
            <span className="hh-preview__count">{total.toLocaleString()}세대</span>
            <span>생성:</span>
            {preview.map((label) => (
              <span key={label} className="hh-preview__chip">
                {label}
              </span>
            ))}
            {total > preview.length ? <span>…</span> : null}
          </div>
        )}

        <p className="hh-form__note" role="note">
          이미 있는 층·호는 건너뜁니다(중복 생성 없음).
        </p>

        <div className="hh-form__actions">
          <Button type="button" variant="secondary" size="sm" onClick={onCancel}>
            취소
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={busy || error !== null}>
            {busy ? "생성 중…" : "생성"}
          </Button>
        </div>
      </form>
    </FormModal>
  );
}
