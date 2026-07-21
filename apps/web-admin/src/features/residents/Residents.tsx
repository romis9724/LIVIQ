"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button, Dialog, EmptyState, FileDropzone, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  ROSTER_TEMPLATE_URL,
  approveSignup,
  deleteRosterRow,
  listApprovals,
  listRoster,
  rejectSignup,
  updateRosterState,
  uploadRoster,
  type Approval,
  type RosterEntry,
  type RosterList,
  type RosterUploadResult,
} from "@/lib/api";
import { ROSTER_ACCEPT, formatUnit, isValidRejectReason, validateRoster } from "./logic";
import "./residents.css";

const ROSTER_MAX_MB = 10;
const TOAST_DURATION_MS = 3200;
const PAGE_SIZE = 50;

// 명부 상태·불일치 사유 라벨(H7-9) — 코드값은 서버 계약(schemas/roster·approvals).
const STATE_LABEL: Record<string, string> = {
  unregistered: "미가입",
  joined: "가입완료",
  moved_out: "전출 후보",
};
const MISMATCH_LABEL: Record<string, string> = {
  no_household_roster: "명부에 해당 세대 없음",
  person_mismatch: "성함·생년월일 불일치",
  all_consumed: "세대 명부 인원 모두 가입됨",
};

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

export function Residents() {
  const [signups, setSignups] = useState<Approval[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [upload, setUpload] = useState<UploadState>({ phase: "idle" });
  const [rejectId, setRejectId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 명부 목록(H7-9) — 검색은 제출 시 적용(appliedQuery), 필터·페이지는 즉시.
  const [roster, setRoster] = useState<RosterList | null>(null);
  const [rosterError, setRosterError] = useState<string | null>(null);
  const [queryInput, setQueryInput] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [stateFilter, setStateFilter] = useState("");
  const [page, setPage] = useState(1);
  // 업로드 패널 열림 — 최초 로드 때 한 번만 결정(명부 없으면 펼침), 이후엔 사용자 조작만 반영.
  // 리로드마다 counts로 다시 계산하면 업로드 직후 패널이 저절로 접혀 결과가 숨는다.
  const [uploadOpen, setUploadOpen] = useState<boolean | null>(null);
  const [rosterDeleteTarget, setRosterDeleteTarget] = useState<RosterEntry | null>(null);

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

  const loadRoster = useCallback(async () => {
    try {
      const next = await listRoster({
        q: appliedQuery,
        state: stateFilter,
        page,
        size: PAGE_SIZE,
      });
      setRoster(next);
      setRosterError(null);
      setUploadOpen((prev) => (prev === null ? next.counts.total === 0 : prev));
    } catch (err) {
      setRosterError(errorMessage(err));
      setRoster(null);
    }
  }, [appliedQuery, stateFilter, page]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void loadRoster();
  }, [loadRoster]);

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
      await loadRoster(); // 업로드 즉시 목록·총계 반영(쓰기 전용 프로세스 해소, H7-9)
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

  async function changeRosterState(entry: RosterEntry, state: string) {
    setBusyId(entry.userId);
    try {
      await updateRosterState(entry.userId, state);
      await loadRoster();
      showToast(state === "moved_out" ? "전출 후보로 표시했습니다." : "미가입으로 복원했습니다.", "neutral");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  async function confirmRosterDelete() {
    if (!rosterDeleteTarget) return;
    setBusyId(rosterDeleteTarget.userId);
    try {
      await deleteRosterRow(rosterDeleteTarget.userId);
      setRosterDeleteTarget(null);
      await loadRoster();
      showToast("명부에서 삭제했습니다.", "neutral");
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
  const counts = roster?.counts ?? null;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          주민 관리
        </h1>
        <p className="admin-page__lede">
          단지 명부를 관리하고 가입 신청을 명부와 대조해 승인·거절합니다. 명부 엑셀 재업로드는
          신규 세대만 추가합니다(diff 병합).
        </p>
      </header>

      <main className="admin-page__main">
        {counts ? (
          <div className="apv-stats" role="status" aria-label="명부 요약">
            <StatChip label="명부 전체" value={counts.total} />
            <StatChip label="미가입" value={counts.unregistered} tone="wait" />
            <StatChip label="가입완료" value={counts.joined} tone="ok" />
            <StatChip label="전출 후보" value={counts.movedOut} tone="warn" />
            <StatChip label="승인 대기" value={waiting} tone={waiting > 0 ? "action" : undefined} />
          </div>
        ) : null}

        <section className="apv-queue" aria-labelledby="apv-queue-h">
          <div className="apv-queue__head">
            <h2 id="apv-queue-h" className="apv-queue__title">
              회원 대기자 명단
            </h2>
            <span className="apv-count">{waiting}건 대기</span>
          </div>

          {loadError ? (
            <EmptyState icon="⚠" title="목록을 불러오지 못했습니다" description={loadError} />
          ) : signups === null ? (
            <div className="apv-list">
              <Skeleton height="96px" />
            </div>
          ) : waiting === 0 ? (
            <p className="apv-queue__empty">
              대기 중인 가입 신청이 없습니다. 새 신청이 접수되면 명부 대조 결과와 함께 이곳에
              모입니다.
            </p>
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

        <RosterTable
          roster={roster}
          error={rosterError}
          queryInput={queryInput}
          onQueryInput={setQueryInput}
          onSearch={() => {
            setPage(1);
            setAppliedQuery(queryInput.trim());
          }}
          stateFilter={stateFilter}
          onStateFilter={(next) => {
            setPage(1);
            setStateFilter(next);
          }}
          page={page}
          onPage={setPage}
          busyId={busyId}
          onChangeState={changeRosterState}
          onDelete={setRosterDeleteTarget}
        />

        <RosterPanel
          upload={upload}
          onFile={handleFile}
          lastUpload={roster?.lastUpload ?? null}
          open={uploadOpen ?? false}
          onToggle={setUploadOpen}
        />
      </main>

      {rejectTarget ? (
        <RejectDialog
          signup={rejectTarget}
          busy={busyId === rejectTarget.userId}
          onConfirm={confirmReject}
          onCancel={() => setRejectId(null)}
        />
      ) : null}

      <Dialog
        open={rosterDeleteTarget !== null}
        title="명부에서 삭제할까요?"
        description={`${rosterDeleteTarget?.nameMasked ?? ""} (${rosterDeleteTarget?.buildingName ?? ""}동 ${rosterDeleteTarget?.unitNo ?? ""}호) 행을 명부에서 완전히 삭제합니다. 저장된 개인정보도 함께 삭제되며 복구할 수 없습니다.`}
        confirmLabel="삭제"
        cancelLabel="취소"
        danger
        onConfirm={() => void confirmRosterDelete()}
        onCancel={() => setRosterDeleteTarget(null)}
      />

      {toast ? (
        <div className="apv-toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}

function StatChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "ok" | "warn" | "wait" | "action";
}) {
  return (
    <span className="apv-stat" data-tone={tone}>
      <span className="apv-stat__value">{value.toLocaleString()}</span>
      <span className="apv-stat__label">{label}</span>
    </span>
  );
}

interface RosterTableProps {
  roster: RosterList | null;
  error: string | null;
  queryInput: string;
  onQueryInput: (value: string) => void;
  onSearch: () => void;
  stateFilter: string;
  onStateFilter: (value: string) => void;
  page: number;
  onPage: (value: number) => void;
  busyId: string | null;
  onChangeState: (entry: RosterEntry, state: string) => void;
  onDelete: (entry: RosterEntry) => void;
}

const STATE_FILTERS = [
  { value: "", label: "전체" },
  { value: "unregistered", label: "미가입" },
  { value: "joined", label: "가입완료" },
  { value: "moved_out", label: "전출 후보" },
] as const;

function RosterTable({
  roster,
  error,
  queryInput,
  onQueryInput,
  onSearch,
  stateFilter,
  onStateFilter,
  page,
  onPage,
  busyId,
  onChangeState,
  onDelete,
}: RosterTableProps) {
  const totalPages = roster ? Math.max(1, Math.ceil(roster.total / PAGE_SIZE)) : 1;

  return (
    <section className="surface-card apv-roster" aria-labelledby="apv-roster-h">
      <h2 id="apv-roster-h" className="apv-queue__title">
        주민 명부
      </h2>

      {/* 상태 필터 + 검색 — 한 툴바로 묶음(운영자 피드백 6). */}
      <div className="apv-roster__toolbar">
        <div className="apv-roster__filters" role="tablist" aria-label="명부 상태 필터">
          {STATE_FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              role="tab"
              aria-selected={stateFilter === filter.value}
              className="apv-roster__filter"
              data-state={filter.value || "all"}
              data-active={stateFilter === filter.value || undefined}
              onClick={() => onStateFilter(filter.value)}
            >
              {filter.label}
            </button>
          ))}
        </div>
        <form
          className="apv-roster__search"
          onSubmit={(e) => {
            e.preventDefault();
            onSearch();
          }}
        >
          <input
            className="apv-roster__search-input"
            value={queryInput}
            onChange={(e) => onQueryInput(e.target.value)}
            placeholder="동 또는 호수 검색 (예: 401, 201)"
            aria-label="명부 검색"
            inputMode="numeric"
          />
          <Button type="submit" variant="secondary" size="sm">
            검색
          </Button>
        </form>
      </div>

      {error ? (
        <EmptyState icon="⚠" title="명부를 불러오지 못했습니다" description={error} />
      ) : roster === null ? (
        <Skeleton height="200px" />
      ) : roster.counts.total === 0 ? (
        <EmptyState
          icon="📇"
          title="등록된 명부가 없습니다"
          description="아래에서 명부 엑셀을 업로드하면 세대별 목록이 여기에 표시됩니다."
        />
      ) : roster.items.length === 0 ? (
        <EmptyState icon="🔍" title="조건에 맞는 세대가 없습니다" description="검색어·필터를 확인해 주세요." />
      ) : (
        <>
          <table className="apv-roster__table">
            <thead>
              <tr>
                <th scope="col">동</th>
                <th scope="col">호</th>
                <th scope="col">성함</th>
                <th scope="col">상태</th>
                <th scope="col" className="apv-roster__actions-col">
                  관리
                </th>
              </tr>
            </thead>
            <tbody>
              {roster.items.map((entry) => (
                <tr key={entry.userId}>
                  <td>{entry.buildingName ?? "—"}동</td>
                  <td>{entry.unitNo ?? "—"}호</td>
                  <td>{entry.nameMasked}</td>
                  <td>
                    <span className={`apv-state apv-state--${entry.state}`}>
                      {STATE_LABEL[entry.state] ?? entry.state}
                    </span>
                  </td>
                  <td className="apv-roster__actions">
                    {entry.state === "unregistered" ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busyId === entry.userId}
                        onClick={() => onChangeState(entry, "moved_out")}
                      >
                        전출 처리
                      </Button>
                    ) : null}
                    {entry.state === "moved_out" ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busyId === entry.userId}
                        onClick={() => onChangeState(entry, "unregistered")}
                      >
                        복원
                      </Button>
                    ) : null}
                    {entry.state !== "joined" ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        className="apv-roster__delete"
                        disabled={busyId === entry.userId}
                        onClick={() => onDelete(entry)}
                      >
                        삭제
                      </Button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="apv-roster__pager">
            <Button
              variant="ghost"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPage(page - 1)}
            >
              이전
            </Button>
            <span className="apv-roster__page">
              {page} / {totalPages} 페이지 · {roster.total.toLocaleString()}건
            </span>
            <Button
              variant="ghost"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => onPage(page + 1)}
            >
              다음
            </Button>
          </div>
        </>
      )}
    </section>
  );
}

function RosterPanel({
  upload,
  onFile,
  lastUpload,
  open,
  onToggle,
}: {
  upload: UploadState;
  onFile: (file: File) => void;
  lastUpload: RosterList["lastUpload"];
  open: boolean;
  onToggle: (open: boolean) => void;
}) {
  const fileName = "fileName" in upload ? upload.fileName : undefined;

  return (
    <details
      className="surface-card apv-upload"
      open={open}
      onToggle={(e) => onToggle(e.currentTarget.open)}
    >
      <summary className="apv-upload__summary">
        <span className="apv-upload__icon" aria-hidden="true">
          📇
        </span>
        <span className="apv-upload__heading">
          <span className="apv-upload__title">단지 명부 업로드</span>
          <span className="apv-upload__sub">
            {lastUpload
              ? `마지막 업로드 ${lastUpload.uploadedAt.slice(0, 16).replace("T", " ")} · ${lastUpload.rowCount}행 · 오류 ${lastUpload.errorCount}건`
              : "사전등록 세대(성함·생년월일·동·층·호). 같은 세대는 덮어쓰지 않고 신규만 추가합니다."}
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

        <p className="apv-upload__template">
          처음이신가요?{" "}
          <a className="apv-upload__template-link" href={ROSTER_TEMPLATE_URL} download>
            명부 양식 다운로드 (xlsx)
          </a>{" "}
          — 예시 행을 지우고 채워 업로드하세요.
        </p>

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
          <RosterBadge match={signup.rosterMatched} reason={signup.mismatchReason} />
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

function RosterBadge({ match, reason }: { match: boolean; reason: string | null }) {
  if (match) {
    return (
      <span className="apv-match apv-match--ok">
        <span aria-hidden="true">✓</span> 명부 일치
      </span>
    );
  }
  // 불일치 사유 구체화(H7-9) — 소장이 전화 확인 등 후속 판단을 할 근거.
  const label = (reason && MISMATCH_LABEL[reason]) || "수동 확인 필요";
  return (
    <span className="apv-match apv-match--warn">
      <span aria-hidden="true">⚠</span> 명부 불일치 · {label}
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
