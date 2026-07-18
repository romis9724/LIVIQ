"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button, EmptyState, FileDropzone, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  approveSignup,
  listApprovals,
  rejectSignup,
  uploadRoster,
  type Approval,
  type RosterUploadResult,
} from "@/lib/api";
import { ROSTER_ACCEPT, formatUnit, isValidRejectReason, validateRoster } from "./logic";
import "./approvals.css";

const ROSTER_MAX_MB = 10;
const TOAST_DURATION_MS = 3200;

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; fileName: string }
  | { phase: "error"; fileName: string; message: string }
  | { phase: "done"; fileName: string; result: RosterUploadResult };

type ToastState = { message: string; tone: ToastTone };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function Approvals() {
  const [signups, setSignups] = useState<Approval[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [upload, setUpload] = useState<UploadState>({ phase: "idle" });
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async () => {
    try {
      setSignups(await listApprovals());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
      setSignups([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  async function handleFile(file: File) {
    const invalid = validateRoster(file);
    if (invalid) {
      setUpload({ phase: "error", fileName: file.name, message: invalid });
      return;
    }
    setUpload({ phase: "uploading", fileName: file.name });
    try {
      const result = await uploadRoster(file);
      setUpload({ phase: "done", fileName: file.name, result });
      showToast(`명부 반영 완료 — 신규 ${result.applied} · 비활성 ${result.markedInactive}`);
    } catch (err) {
      setUpload({ phase: "error", fileName: file.name, message: errorMessage(err) });
    }
  }

  async function approve(userId: string) {
    setBusyId(userId);
    try {
      await approveSignup(userId);
      setSignups((prev) => (prev ? prev.filter((s) => s.userId !== userId) : prev));
      showToast("승인 완료 — 입주민에게 알림함으로 안내");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmReject(reason: string) {
    if (!rejectId) return;
    const userId = rejectId;
    setBusyId(userId);
    try {
      await rejectSignup(userId, reason);
      setSignups((prev) => (prev ? prev.filter((s) => s.userId !== userId) : prev));
      setRejectId(null);
      showToast("가입을 거절했습니다 — 사유는 신청자에게 전달됩니다.", "neutral");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  const waiting = signups?.length ?? 0;
  const rejectTarget = signups?.find((s) => s.userId === rejectId) ?? null;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          가입 승인
        </h1>
        <p className="admin-page__lede">
          입주민 가입 신청을 단지 명부와 대조해 승인·거절합니다. 명부 엑셀을 올리면 신규 세대만
          추가되고 기존 세대는 그대로 유지됩니다(diff 병합).
        </p>
      </header>

      <main className="admin-page__main">
        <RosterPanel upload={upload} onFile={handleFile} />

        <section className="apv-queue" aria-labelledby="apv-queue-h">
          <div className="apv-queue__head">
            <h2 id="apv-queue-h" className="apv-queue__title">
              가입 대기
            </h2>
            <span className="apv-count">{waiting}건 대기</span>
          </div>

          {loadError ? (
            <EmptyState icon="⚠" title="목록을 불러오지 못했습니다" description={loadError} />
          ) : signups === null ? (
            <div className="apv-list">
              <Skeleton height="96px" />
              <Skeleton height="96px" />
            </div>
          ) : waiting === 0 ? (
            <EmptyState
              icon="✓"
              title="대기 중인 가입 신청이 없습니다"
              description="새 신청이 접수되면 명부 대조 결과와 함께 이곳에 모입니다."
            />
          ) : (
            <ul className="apv-list">
              {signups.map((signup) => (
                <SignupCard
                  key={signup.userId}
                  signup={signup}
                  busy={busyId === signup.userId}
                  onApprove={approve}
                  onReject={setRejectId}
                />
              ))}
            </ul>
          )}
        </section>
      </main>

      {rejectTarget ? (
        <RejectDialog
          signup={rejectTarget}
          busy={busyId === rejectTarget.userId}
          onConfirm={confirmReject}
          onCancel={() => setRejectId(null)}
        />
      ) : null}

      {toast ? (
        <div className="apv-toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}

function RosterPanel({ upload, onFile }: { upload: UploadState; onFile: (file: File) => void }) {
  const fileName = "fileName" in upload ? upload.fileName : undefined;

  return (
    <details className="surface-card apv-upload" open>
      <summary className="apv-upload__summary">
        <span className="apv-upload__icon" aria-hidden="true">
          📇
        </span>
        <span className="apv-upload__heading">
          <span className="apv-upload__title">단지 명부 업로드</span>
          <span className="apv-upload__sub">
            사전등록 세대(성함·생년월일·동·층·호). 같은 세대는 덮어쓰지 않고 신규만 추가합니다.
          </span>
        </span>
        <span className="apv-upload__chevron" aria-hidden="true" />
      </summary>

      <div className="apv-upload__body">
        <FileDropzone
          label="단지 명부 엑셀 업로드"
          accept={ROSTER_ACCEPT}
          maxSizeMb={ROSTER_MAX_MB}
          onFile={onFile}
          state={upload.phase === "done" ? "selected" : upload.phase}
          fileName={fileName}
          errorMessage={upload.phase === "error" ? upload.message : undefined}
        />

        {upload.phase === "done" ? <RosterResult result={upload.result} /> : null}
      </div>
    </details>
  );
}

function RosterResult({ result }: { result: RosterUploadResult }) {
  return (
    <div className="apv-diff">
      <div className="apv-diff__badges">
        <span className="apv-badge apv-badge--new">신규 등록 {result.applied}</span>
        <span className="apv-badge apv-badge--out">비활성 처리 {result.markedInactive}</span>
        {result.errors.length > 0 ? (
          <span className="apv-badge apv-badge--kept">오류 {result.errors.length}행</span>
        ) : null}
      </div>

      {result.errors.length > 0 ? (
        <div className="apv-out">
          <p className="apv-out__title">반영하지 못한 행</p>
          <ul className="apv-out__list">
            {result.errors.map((err) => (
              <li key={err.row} className="apv-out__row">
                <span className="apv-out__unit">{err.row}행</span>
                <span className="apv-out__name">{err.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="apv-out__empty">모든 행을 반영했습니다.</p>
      )}
    </div>
  );
}

interface SignupCardProps {
  signup: Approval;
  busy: boolean;
  onApprove: (userId: string) => void;
  onReject: (userId: string) => void;
}

function SignupCard({ signup, busy, onApprove, onReject }: SignupCardProps) {
  return (
    <li className="apv-card">
      <div className="apv-card__body">
        <div className="apv-card__idline">
          <span className="apv-card__name">{signup.nameMasked}</span>
          <span className="apv-card__unit">{formatUnit(signup.buildingName, signup.unitNo)}</span>
          <RosterBadge match={signup.rosterMatched} />
        </div>
        <dl className="apv-card__meta">
          <div>
            <dt>신청일</dt>
            <dd>{signup.requestedAt.slice(0, 10)}</dd>
          </div>
        </dl>
      </div>

      <div className="apv-card__actions">
        <Button variant="primary" size="sm" disabled={busy} onClick={() => onApprove(signup.userId)}>
          승인
        </Button>
        <Button variant="danger" size="sm" disabled={busy} onClick={() => onReject(signup.userId)}>
          거절
        </Button>
      </div>
    </li>
  );
}

function RosterBadge({ match }: { match: boolean }) {
  if (match) {
    return (
      <span className="apv-match apv-match--ok">
        <span aria-hidden="true">✓</span> 명부 일치
      </span>
    );
  }
  return (
    <span className="apv-match apv-match--warn">
      <span aria-hidden="true">⚠</span> 명부 불일치 · 수동 확인
    </span>
  );
}

interface RejectDialogProps {
  signup: Approval;
  busy: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

function RejectDialog({ signup, busy, onConfirm, onCancel }: RejectDialogProps) {
  const [reason, setReason] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const titleId = useId();

  useEffect(() => {
    textareaRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const trimmed = reason.trim();
  const canSubmit = isValidRejectReason(reason) && !busy;

  return (
    <div className="apv-modal" onClick={onCancel}>
      <div
        className="apv-modal__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="apv-modal__title" id={titleId}>
          가입 거절 — {signup.nameMasked} ({formatUnit(signup.buildingName, signup.unitNo)})
        </h2>
        <label className="apv-modal__label" htmlFor="apv-reason">
          거절 사유 <span aria-hidden="true">*</span>
        </label>
        <textarea
          id="apv-reason"
          ref={textareaRef}
          className="apv-modal__textarea"
          rows={3}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          aria-required="true"
          placeholder="예: 명부에 없는 세대이며 본인 확인이 되지 않았습니다."
        />
        <p className="apv-modal__help">
          사유는 신청자에게 전달됩니다. 개인정보·민감정보는 적지 마세요.
        </p>
        <div className="apv-modal__actions">
          <Button variant="secondary" size="sm" onClick={onCancel}>
            취소
          </Button>
          <Button variant="danger" size="sm" disabled={!canSubmit} onClick={() => onConfirm(trimmed)}>
            거절 확정
          </Button>
        </div>
      </div>
    </div>
  );
}
