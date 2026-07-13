"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Button, Dialog, EmptyState, FileDropzone, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { PENDING_SIGNUPS, ROSTER_DIFF } from "./data";
import {
  decideSignup,
  deactivateCandidate,
  maskBirth,
  maskName,
  pendingCount,
  summarizeDiff,
  validateRoster,
  ROSTER_ACCEPT,
  type DiffSummary,
  type MoveOutCandidate,
  type PendingSignup,
} from "./logic";
import "./approvals.css";

const ROSTER_MAX_MB = 10;

type UploadState =
  | { phase: "idle" }
  | { phase: "uploading"; fileName: string; progress: number }
  | { phase: "error"; fileName: string; message: string }
  | { phase: "done"; fileName: string };

type ToastState = { message: string; tone: ToastTone };

export function Approvals() {
  const [signups, setSignups] = useState<PendingSignup[]>([...PENDING_SIGNUPS]);
  const [candidates, setCandidates] = useState<MoveOutCandidate[]>([
    ...ROSTER_DIFF.moveOutCandidates,
  ]);
  const [upload, setUpload] = useState<UploadState>({ phase: "idle" });
  const [deactivateId, setDeactivateId] = useState<string | null>(null);
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => () => window.clearInterval(timerRef.current ?? undefined), []);

  function handleFile(file: File) {
    const error = validateRoster(file);
    if (error) {
      setUpload({ phase: "error", fileName: file.name, message: error });
      return;
    }
    // 데모: 업로드 진행률 시뮬레이션 → diff 결과 표시.
    window.clearInterval(timerRef.current ?? undefined);
    let progress = 0;
    setUpload({ phase: "uploading", fileName: file.name, progress });
    timerRef.current = window.setInterval(() => {
      progress += 25;
      if (progress >= 100) {
        window.clearInterval(timerRef.current ?? undefined);
        setUpload({ phase: "done", fileName: file.name });
      } else {
        setUpload({ phase: "uploading", fileName: file.name, progress });
      }
    }, 220);
  }

  function approve(signup: PendingSignup) {
    setSignups((prev) => decideSignup(prev, signup.id, "approved"));
    setToast({ message: "승인 완료 — 입주민에게 알림함으로 안내", tone: "success" });
  }

  function confirmReject(reason: string) {
    if (!rejectId) return;
    setSignups((prev) => decideSignup(prev, rejectId, "rejected"));
    setRejectId(null);
    setToast({ message: `가입을 거절했습니다 — 사유: ${reason}`, tone: "neutral" });
  }

  function confirmDeactivate() {
    if (!deactivateId) return;
    const target = candidates.find((c) => c.id === deactivateId);
    setCandidates((prev) => deactivateCandidate(prev, deactivateId));
    setDeactivateId(null);
    setToast({
      message: `${target ? `${maskName(target.name)} 세대를 ` : ""}전출 처리(비활성화)했습니다.`,
      tone: "neutral",
    });
  }

  const waiting = pendingCount(signups);
  const summary = summarizeDiff({ ...ROSTER_DIFF, moveOutCandidates: candidates });
  const deactivateTarget = candidates.find((c) => c.id === deactivateId) ?? null;
  const rejectTarget = signups.find((s) => s.id === rejectId) ?? null;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          가입 승인
        </h1>
        <p className="admin-page__lede">
          입주민 가입 신청을 단지 명부와 대조해 승인·거절합니다. 명부 엑셀을 올리면 신규 세대만
          추가되고 기존 승인 세대는 그대로 유지됩니다(diff 병합).
        </p>
      </header>

      <main className="admin-page__main">
        <RosterPanel
          upload={upload}
          summary={summary}
          candidates={candidates}
          onFile={handleFile}
          onDeactivate={setDeactivateId}
        />

        <section className="apv-queue" aria-labelledby="apv-queue-h">
          <div className="apv-queue__head">
            <h2 id="apv-queue-h" className="apv-queue__title">
              가입 대기
            </h2>
            <span className="apv-count">{waiting}건 대기</span>
          </div>

          {waiting === 0 ? (
            <EmptyState
              icon="✓"
              title="대기 중인 가입 신청이 없습니다"
              description="새 신청이 접수되면 명부 대조 결과와 함께 이곳에 모입니다."
            />
          ) : (
            <ul className="apv-list">
              {signups.map((signup) => (
                <SignupCard
                  key={signup.id}
                  signup={signup}
                  onApprove={approve}
                  onReject={setRejectId}
                />
              ))}
            </ul>
          )}
        </section>
      </main>

      <Dialog
        open={Boolean(deactivateId)}
        title="전출 세대로 비활성화할까요?"
        description={
          deactivateTarget
            ? `${deactivateTarget.unit} · ${maskName(deactivateTarget.name)} 세대를 명부에서 제외하고 계정을 비활성화합니다. 다시 입주가 확인되면 재활성화할 수 있습니다.`
            : undefined
        }
        confirmLabel="비활성화"
        danger
        onCancel={() => setDeactivateId(null)}
        onConfirm={confirmDeactivate}
      />

      {rejectTarget ? (
        <RejectDialog
          signup={rejectTarget}
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

interface RosterPanelProps {
  upload: UploadState;
  summary: DiffSummary;
  candidates: readonly MoveOutCandidate[];
  onFile: (file: File) => void;
  onDeactivate: (id: string) => void;
}

function RosterPanel({ upload, summary, candidates, onFile, onDeactivate }: RosterPanelProps) {
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
            사전등록 세대(성함·생년월일·동·호). 같은 세대는 덮어쓰지 않고 신규만 추가합니다.
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
          progress={upload.phase === "uploading" ? upload.progress : undefined}
          errorMessage={upload.phase === "error" ? upload.message : undefined}
        />

        {upload.phase === "done" ? (
          <div className="apv-diff">
            <div className="apv-diff__badges">
              <span className="apv-badge apv-badge--new">신규 등록 {summary.newRegistered}</span>
              <span className="apv-badge apv-badge--kept">
                기존 매칭 유지 {summary.matchedKept}
              </span>
              <span className="apv-badge apv-badge--out">
                전출 후보 {summary.moveOutCandidates}
              </span>
            </div>

            {candidates.length > 0 ? (
              <div className="apv-out">
                <p className="apv-out__title">전출 후보 — 새 명부에서 빠진 세대</p>
                <ul className="apv-out__list">
                  {candidates.map((candidate) => (
                    <li key={candidate.id} className="apv-out__row">
                      <span className="apv-out__unit">{candidate.unit}</span>
                      <span className="apv-out__name">{maskName(candidate.name)}</span>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onDeactivate(candidate.id)}
                      >
                        비활성화
                      </Button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <p className="apv-out__empty">전출 후보를 모두 처리했습니다.</p>
            )}
          </div>
        ) : null}
      </div>
    </details>
  );
}

interface SignupCardProps {
  signup: PendingSignup;
  onApprove: (signup: PendingSignup) => void;
  onReject: (id: string) => void;
}

function SignupCard({ signup, onApprove, onReject }: SignupCardProps) {
  const processed = signup.status !== "pending";

  return (
    <li className="apv-card" data-status={signup.status}>
      <div className="apv-card__body">
        <div className="apv-card__idline">
          <span className="apv-card__name">{maskName(signup.name)}</span>
          <span className="apv-card__unit">{signup.unit}</span>
          <RosterBadge match={signup.rosterMatch} />
        </div>
        <dl className="apv-card__meta">
          <div>
            <dt>생년월일</dt>
            <dd>{maskBirth(signup.birth)}</dd>
          </div>
          <div>
            <dt>신청일</dt>
            <dd>{signup.appliedAt}</dd>
          </div>
          <div>
            <dt>동의 약관</dt>
            <dd>
              <span className="apv-policy">{signup.policyVersion}</span>
            </dd>
          </div>
        </dl>
      </div>

      <div className="apv-card__actions">
        {processed ? (
          <span
            className={`apv-result apv-result--${signup.status}`}
            role="status"
          >
            {signup.status === "approved" ? "승인됨" : "거절됨"}
          </span>
        ) : (
          <>
            <Button variant="primary" size="sm" onClick={() => onApprove(signup)}>
              승인
            </Button>
            <Button variant="danger" size="sm" onClick={() => onReject(signup.id)}>
              거절
            </Button>
          </>
        )}
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
  signup: PendingSignup;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

function RejectDialog({ signup, onConfirm, onCancel }: RejectDialogProps) {
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
  const canSubmit = trimmed.length > 0;

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
          가입 거절 — {maskName(signup.name)} ({signup.unit})
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
          <Button
            variant="danger"
            size="sm"
            disabled={!canSubmit}
            onClick={() => onConfirm(trimmed)}
          >
            거절 확정
          </Button>
        </div>
      </div>
    </div>
  );
}
