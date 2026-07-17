"use client";

import { Button, FormField } from "@liviq/ui";
import { useState } from "react";

import type {
  FacilityCreateInput,
  FacilityStatus,
  IncidentInput,
  MaintenanceInput,
} from "@/lib/api";
import { STATUS_META, STATUS_ORDER, validateFacilityName, validateRequiredText } from "./data";

interface DialogShellProps {
  title: string;
  desc?: string;
  busy: boolean;
  submitLabel: string;
  canSubmit: boolean;
  onCancel: () => void;
  onSubmit: () => void;
  children: React.ReactNode;
}

function DialogShell({
  title,
  desc,
  busy,
  submitLabel,
  canSubmit,
  onCancel,
  onSubmit,
  children,
}: DialogShellProps) {
  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <form
        className="dialog fac-dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit && !busy) onSubmit();
        }}
      >
        <div className="dialog__title">{title}</div>
        {desc ? <div className="dialog__desc">{desc}</div> : null}
        <div className="fac-dialog__body">{children}</div>
        <div className="dialog__actions">
          <button type="button" className="btn btn--secondary btn--sm" onClick={onCancel}>
            취소
          </button>
          <Button variant="primary" type="submit" disabled={!canSubmit || busy}>
            {submitLabel}
          </Button>
        </div>
      </form>
    </div>
  );
}

interface RegisterDialogProps {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: FacilityCreateInput) => void;
}

export function RegisterDialog({ busy, onCancel, onSubmit }: RegisterDialogProps) {
  const [name, setName] = useState("");
  const [location, setLocation] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState<FacilityStatus>("normal");
  const [touched, setTouched] = useState(false);

  const nameError = touched ? validateFacilityName(name) : null;
  const canSubmit = validateFacilityName(name) === null;

  return (
    <DialogShell
      title="설비 등록"
      desc="새 설비를 등록합니다. 상태 변경·이력은 등록 후 상세에서 관리합니다."
      busy={busy}
      submitLabel="등록"
      canSubmit={canSubmit}
      onCancel={onCancel}
      onSubmit={() => {
        setTouched(true);
        if (!canSubmit) return;
        onSubmit({
          name: name.trim(),
          location: location.trim() || undefined,
          type: type.trim() || undefined,
          status,
        });
      }}
    >
      <FormField
        label="설비 이름"
        value={name}
        error={nameError ?? undefined}
        onChange={(e) => setName(e.target.value)}
        onBlur={() => setTouched(true)}
        placeholder="예: 1203동 3호기 승강기"
      />
      <FormField
        label="위치 (선택)"
        value={location}
        onChange={(e) => setLocation(e.target.value)}
        placeholder="예: 1203동"
      />
      <FormField
        label="유형 (선택)"
        value={type}
        onChange={(e) => setType(e.target.value)}
        placeholder="예: elevator"
      />
      <label className="fac-field">
        <span className="form-field__label">초기 상태</span>
        <select
          className="fac-select"
          value={status}
          onChange={(e) => setStatus(e.target.value as FacilityStatus)}
        >
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {STATUS_META[s].label}
            </option>
          ))}
        </select>
      </label>
    </DialogShell>
  );
}

interface IncidentDialogProps {
  facilityName: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: IncidentInput) => void;
}

export function IncidentDialog({ facilityName, busy, onCancel, onSubmit }: IncidentDialogProps) {
  const [symptom, setSymptom] = useState("");
  const [resolution, setResolution] = useState("");
  const [touched, setTouched] = useState(false);

  const symptomError = touched ? validateRequiredText(symptom, "증상") : null;
  const canSubmit = validateRequiredText(symptom, "증상") === null;

  return (
    <DialogShell
      title="장애 기록"
      desc={`${facilityName} 의 장애를 기록합니다.`}
      busy={busy}
      submitLabel="기록"
      canSubmit={canSubmit}
      onCancel={onCancel}
      onSubmit={() => {
        setTouched(true);
        if (!canSubmit) return;
        onSubmit({ symptom: symptom.trim(), resolution: resolution.trim() || undefined });
      }}
    >
      <label className="fac-field">
        <span className="form-field__label">증상</span>
        <textarea
          className="fac-textarea"
          rows={3}
          value={symptom}
          onChange={(e) => setSymptom(e.target.value)}
          onBlur={() => setTouched(true)}
          placeholder="예: 운행 중 덜컹 소음 및 저층 정지 지연"
        />
        {symptomError ? <div className="form-field__error">{symptomError}</div> : null}
      </label>
      <label className="fac-field">
        <span className="form-field__label">조치 (선택)</span>
        <textarea
          className="fac-textarea"
          rows={2}
          value={resolution}
          onChange={(e) => setResolution(e.target.value)}
          placeholder="예: 가이드 롤러 교체"
        />
      </label>
    </DialogShell>
  );
}

interface MaintenanceDialogProps {
  facilityName: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: MaintenanceInput) => void;
}

export function MaintenanceDialog({
  facilityName,
  busy,
  onCancel,
  onSubmit,
}: MaintenanceDialogProps) {
  const [work, setWork] = useState("");
  const [performer, setPerformer] = useState("");
  const [touched, setTouched] = useState(false);

  const workError = touched ? validateRequiredText(work, "작업 내용") : null;
  const canSubmit = validateRequiredText(work, "작업 내용") === null;

  return (
    <DialogShell
      title="정비 기록"
      desc={`${facilityName} 의 정비를 기록합니다.`}
      busy={busy}
      submitLabel="기록"
      canSubmit={canSubmit}
      onCancel={onCancel}
      onSubmit={() => {
        setTouched(true);
        if (!canSubmit) return;
        onSubmit({ work: work.trim(), performer: performer.trim() || undefined });
      }}
    >
      <label className="fac-field">
        <span className="form-field__label">작업 내용</span>
        <textarea
          className="fac-textarea"
          rows={3}
          value={work}
          onChange={(e) => setWork(e.target.value)}
          onBlur={() => setTouched(true)}
          placeholder="예: 정기 점검 및 윤활유 보충"
        />
        {workError ? <div className="form-field__error">{workError}</div> : null}
      </label>
      <FormField
        label="작업자 (선택)"
        value={performer}
        onChange={(e) => setPerformer(e.target.value)}
        placeholder="예: 김기사"
      />
    </DialogShell>
  );
}
