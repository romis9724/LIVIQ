"use client";

import { Button, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import {
  ApiError,
  assignInquiry,
  getMe,
  listAdminInquiries,
  listCodeGroups,
  listInquiryEvents,
  listStaff,
  replyInquiry,
  setInquiryPriority,
  updateInquiryStatus,
  type Inquiry,
  type InquiryEvent,
  type InquiryStatus,
  type Priority,
  type StaffMember,
} from "@/lib/api";
import { INQUIRY_CATEGORY_GROUP, codeLabelMap } from "@/lib/codes";
import {
  FILTERS,
  PRIORITY_META,
  PRIORITY_OPTIONS,
  STATUS_META,
  STATUS_ORDER,
  commentBody,
  commentKind,
  countByStatus,
  eventLabel,
  formatStatusChange,
  hasReply,
  nextStatuses,
  shortDate,
  sortEvents,
  type FilterId,
} from "./data";
import "./inquiry-admin.css";

const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

/** userId → 표시 라벨(email 우선, 없으면 축약 id). */
function staffLabel(map: Map<string, string>, userId: string | null): string | null {
  if (!userId) return null;
  return map.get(userId) ?? userId.slice(0, 8);
}

export function InquiryAdmin() {
  const [inquiries, setInquiries] = useState<Inquiry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterId>("all");
  const [search, setSearch] = useState("");
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // 배정 드롭다운·역행 권한·라벨용 보조 데이터 — 실패해도 목록은 막지 않는다(getMe 패턴).
  const [isManager, setIsManager] = useState(false);
  const [staff, setStaff] = useState<StaffMember[]>([]);
  const [categoryMap, setCategoryMap] = useState<Map<string, string>>(new Map());
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async () => {
    try {
      setInquiries(await listAdminInquiries());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    void getMe()
      .then((me) => setIsManager(me.roles.includes("MANAGER")))
      .catch(() => undefined);
    void listStaff()
      .then(setStaff)
      .catch(() => undefined);
    void listCodeGroups()
      .then((groups) => setCategoryMap(codeLabelMap(groups, INQUIRY_CATEGORY_GROUP)))
      .catch(() => undefined);
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const staffMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const member of staff) if (member.email) map.set(member.userId, member.email);
    return map;
  }, [staff]);

  const counts = useMemo(() => countByStatus(inquiries), [inquiries]);
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return inquiries.filter((inquiry) => {
      if (filter !== "all" && inquiry.status !== filter) return false;
      if (q && !inquiry.title.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [inquiries, filter, search]);

  const selected = useMemo(
    () => inquiries.find((it) => it.id === selectedId) ?? null,
    [inquiries, selectedId],
  );

  const patchLocal = useCallback((updated: Inquiry) => {
    setInquiries((prev) => prev.map((it) => (it.id === updated.id ? updated : it)));
  }, []);

  return (
    <>
      <header className="admin-page__header">
        <div className="ia-head">
          <div>
            <h1 id="main" className="admin-page__title">
              민원 관리
            </h1>
            <p className="admin-page__lede">
              접수된 민원을 담당자에게 배정하고 답변·처리 상태를 관리합니다.
            </p>
          </div>
          <input
            type="search"
            className="ia-search"
            placeholder="제목 검색"
            aria-label="민원 검색"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="ia-filters" role="tablist" aria-label="상태 필터">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              role="tab"
              aria-selected={filter === f.id}
              className="ia-filter"
              data-active={filter === f.id || undefined}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
              <span className="ia-filter__count">{counts[f.id]}</span>
            </button>
          ))}
        </div>
      </header>

      <main className="admin-page__main">
        <InquiryBody
          loading={loading}
          loadError={loadError}
          inquiries={inquiries}
          visible={visible}
          categoryMap={categoryMap}
          staffMap={staffMap}
          onRetry={() => {
            setLoading(true);
            void load();
          }}
          onOpen={setSelectedId}
        />
      </main>

      {selected ? (
        <InquiryDetail
          inquiry={selected}
          isManager={isManager}
          staff={staff}
          staffMap={staffMap}
          categoryMap={categoryMap}
          onClose={() => setSelectedId(null)}
          onUpdated={patchLocal}
          showToast={showToast}
        />
      ) : null}

      {toast ? (
        <div className="ia-toast-slot">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}

interface InquiryBodyProps {
  loading: boolean;
  loadError: string | null;
  inquiries: readonly Inquiry[];
  visible: readonly Inquiry[];
  categoryMap: Map<string, string>;
  staffMap: Map<string, string>;
  onRetry: () => void;
  onOpen: (id: string) => void;
}

function InquiryBody({
  loading,
  loadError,
  inquiries,
  visible,
  categoryMap,
  staffMap,
  onRetry,
  onOpen,
}: InquiryBodyProps) {
  if (loading) {
    return (
      <div className="surface-card ia-tablecard ia-loading">
        <Skeleton height="1.5rem" />
        <Skeleton height="1.5rem" />
        <Skeleton height="1.5rem" />
      </div>
    );
  }
  if (loadError) {
    return (
      <EmptyState
        icon="⚠"
        title="민원을 불러오지 못했습니다"
        description={loadError}
        action={<Button onClick={onRetry}>다시 시도</Button>}
      />
    );
  }
  if (inquiries.length === 0) {
    return (
      <EmptyState
        icon="📮"
        title="접수된 민원이 없습니다"
        description="입주민이 접수한 민원이 여기에 표시됩니다."
      />
    );
  }
  if (visible.length === 0) {
    return (
      <EmptyState
        icon="🔍"
        title="조건에 맞는 민원이 없습니다"
        description="필터나 검색어를 조정해 보세요."
      />
    );
  }
  return (
    <div className="surface-card ia-tablecard">
      <div className="ia-table__scroll">
        <table className="ia-table">
          <thead>
            <tr>
              <th scope="col">접수번호</th>
              <th scope="col">제목</th>
              <th scope="col">카테고리</th>
              <th scope="col">우선순위</th>
              <th scope="col">상태</th>
              <th scope="col">담당</th>
              <th scope="col">접수일</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((inquiry) => (
              <InquiryRow
                key={inquiry.id}
                inquiry={inquiry}
                categoryMap={categoryMap}
                staffMap={staffMap}
                onOpen={onOpen}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface InquiryRowProps {
  inquiry: Inquiry;
  categoryMap: Map<string, string>;
  staffMap: Map<string, string>;
  onOpen: (id: string) => void;
}

function InquiryRow({ inquiry, categoryMap, staffMap, onOpen }: InquiryRowProps) {
  const status = STATUS_META[inquiry.status];
  const priority = inquiry.priority ? PRIORITY_META[inquiry.priority] : null;
  const category = inquiry.categoryCodeId ? (categoryMap.get(inquiry.categoryCodeId) ?? null) : null;
  const assignee = staffLabel(staffMap, inquiry.assigneeUserId);

  return (
    <tr
      className="ia-row"
      role="button"
      tabIndex={0}
      aria-label={`민원 상세: ${inquiry.title}`}
      onClick={() => onOpen(inquiry.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(inquiry.id);
        }
      }}
    >
      <td className="ia-cell--id">{inquiry.id.slice(0, 8)}</td>
      <td>
        <div className="ia-cell__title">{inquiry.title}</div>
        <div className="ia-cell__asker">입주민</div>
      </td>
      <td className="ia-nowrap" data-muted={!category || undefined}>
        {category ?? "—"}
      </td>
      <td className="ia-nowrap">
        {priority ? (
          <span className={`ia-prio ia-prio--${priority.suffix}`}>
            <span aria-hidden="true">{priority.icon}</span>
            {priority.label}
          </span>
        ) : (
          "—"
        )}
      </td>
      <td className="ia-nowrap">
        <span className={`ia-status ia-status--${status.suffix}`}>
          <span className="ia-status__dot" aria-hidden="true" />
          {status.label}
        </span>
      </td>
      <td className="ia-nowrap" data-muted={!assignee || undefined}>
        {assignee ?? "미배정"}
      </td>
      <td className="ia-nowrap ia-cell--date">{shortDate(inquiry.createdAt)}</td>
    </tr>
  );
}

interface InquiryDetailProps {
  inquiry: Inquiry;
  isManager: boolean;
  staff: readonly StaffMember[];
  staffMap: Map<string, string>;
  categoryMap: Map<string, string>;
  onClose: () => void;
  onUpdated: (updated: Inquiry) => void;
  showToast: (message: string, tone?: ToastTone) => void;
}

function InquiryDetail({
  inquiry,
  isManager,
  staff,
  staffMap,
  categoryMap,
  onClose,
  onUpdated,
  showToast,
}: InquiryDetailProps) {
  const [events, setEvents] = useState<InquiryEvent[] | null>(null);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  const loadEvents = useCallback(async () => {
    try {
      setEventsError(null);
      setEvents(sortEvents(await listInquiryEvents(inquiry.id)));
    } catch (err) {
      setEventsError(errorMessage(err));
    }
  }, [inquiry.id]);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  // 열려 있는 동안 Escape 로 닫기 + 배경 스크롤 잠금.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const status = STATUS_META[inquiry.status];
  const priority = inquiry.priority ? PRIORITY_META[inquiry.priority] : null;
  const category = inquiry.categoryCodeId ? (categoryMap.get(inquiry.categoryCodeId) ?? null) : null;
  const assigned = inquiry.assigneeUserId !== null;
  const replyExists = events !== null && hasReply(events);

  // 상태 게이트 — 서버가 최종 방어(422/403). UI 는 명백한 불가만 비활성.
  function statusGate(target: InquiryStatus): string | null {
    if (target === "in_progress" && !assigned) return "담당자 배정 후 처리중 전환 가능";
    if (target === "done" && events !== null && !replyExists) return "답변 등록 후 완료 가능";
    return null;
  }

  async function run(action: () => Promise<Inquiry>, message: string, reloadThread = true) {
    setBusy(true);
    try {
      onUpdated(await action());
      if (reloadThread) await loadEvents();
      showToast(message);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  function handleAssign(value: string) {
    if (!value) return;
    void run(() => assignInquiry(inquiry.id, value), "담당자를 배정했습니다.");
  }

  function handlePriority(value: string) {
    const next = value === "" ? null : (value as Priority);
    void run(() => setInquiryPriority(inquiry.id, next), "우선순위를 변경했습니다.", false);
  }

  function handleStatus(target: InquiryStatus) {
    void run(
      () => updateInquiryStatus(inquiry.id, target),
      `상태를 '${STATUS_META[target].label}'(으)로 변경했습니다.`,
    );
  }

  async function handleReply(e: FormEvent) {
    e.preventDefault();
    const body = reply.trim();
    if (!body || busy) return;
    setBusy(true);
    try {
      onUpdated(await replyInquiry(inquiry.id, body));
      setReply("");
      await loadEvents();
      showToast("답변을 등록했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  const forward = nextStatuses(inquiry.status);
  const backward = isManager
    ? STATUS_ORDER.slice(0, STATUS_ORDER.indexOf(inquiry.status)).reverse()
    : [];

  const assignableStaff = staff.filter(
    (m) => m.email && (m.roles.includes("MANAGER") || m.roles.includes("STAFF")),
  );

  return (
    <div className="ia-overlay" onClick={onClose}>
      <aside
        className="ia-panel"
        role="dialog"
        aria-modal="true"
        aria-label="민원 상세"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="ia-panel__head">
          <div className="ia-panel__heading">
            <div className="ia-panel__chips">
              <span className={`ia-status ia-status--${status.suffix}`}>
                <span className="ia-status__dot" aria-hidden="true" />
                {status.label}
              </span>
              {priority ? (
                <span className={`ia-prio ia-prio--${priority.suffix}`}>
                  <span aria-hidden="true">{priority.icon}</span>
                  {priority.label}
                </span>
              ) : null}
              {category ? <span className="ia-chip">{category}</span> : null}
            </div>
            <h2 className="ia-panel__title">{inquiry.title}</h2>
            <div className="ia-panel__sub">
              접수번호 {inquiry.id.slice(0, 8)} · 접수 {shortDate(inquiry.createdAt)}
            </div>
          </div>
          <button
            type="button"
            className="ia-panel__close"
            aria-label="닫기"
            onClick={onClose}
          >
            ✕
          </button>
        </header>

        <div className="ia-panel__body">
          <p className="ia-panel__origin">{inquiry.body}</p>

          <div className="ia-controls">
            <label className="ia-control">
              <span className="ia-control__label">담당자</span>
              <select
                className="ia-select"
                disabled={busy}
                value={inquiry.assigneeUserId ?? ""}
                onChange={(e) => handleAssign(e.target.value)}
              >
                <option value="" disabled>
                  담당자 선택
                </option>
                {assignableStaff.map((m) => (
                  <option key={m.userId} value={m.userId}>
                    {m.email}
                  </option>
                ))}
              </select>
            </label>

            <label className="ia-control">
              <span className="ia-control__label">우선순위</span>
              <select
                className="ia-select"
                disabled={busy}
                value={inquiry.priority ?? ""}
                onChange={(e) => handlePriority(e.target.value)}
              >
                {PRIORITY_OPTIONS.map((opt) => (
                  <option key={opt.value || "none"} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="ia-control__label">상태 변경</div>
          <div className="ia-statusbtns">
            {forward.map((target, i) => {
              const gate = statusGate(target);
              return (
                <span key={target} className="ia-statusbtn__wrap">
                  <button
                    type="button"
                    className={i === 0 ? "btn btn--primary btn--sm" : "btn btn--secondary btn--sm"}
                    disabled={busy || gate !== null}
                    onClick={() => handleStatus(target)}
                  >
                    {STATUS_META[target].label}
                  </button>
                  {gate ? <span className="ia-hint">{gate}</span> : null}
                </span>
              );
            })}
            {backward.map((target) => (
              <button
                key={target}
                type="button"
                className="btn btn--ghost btn--sm"
                disabled={busy}
                onClick={() => handleStatus(target)}
              >
                ↩ {STATUS_META[target].label}
              </button>
            ))}
            {forward.length === 0 && backward.length === 0 ? (
              <span className="ia-hint">더 변경할 상태가 없습니다.</span>
            ) : null}
          </div>

          <div className="ia-control__label ia-thread__label">처리 내역</div>
          <Thread events={events} error={eventsError} staffMap={staffMap} onRetry={loadEvents} />

          <form className="ia-composer" onSubmit={handleReply}>
            <label className="ia-control__label" htmlFor="ia-reply">
              답변 작성
            </label>
            <textarea
              id="ia-reply"
              className="ia-composer__input"
              rows={3}
              placeholder="입주민에게 전달할 답변을 입력하세요."
              value={reply}
              disabled={busy}
              onChange={(e) => setReply(e.target.value)}
            />
            <div className="ia-composer__actions">
              <Button type="submit" variant="primary" disabled={busy || reply.trim().length === 0}>
                답변 등록
              </Button>
            </div>
          </form>
        </div>
      </aside>
    </div>
  );
}

interface ThreadProps {
  events: InquiryEvent[] | null;
  error: string | null;
  staffMap: Map<string, string>;
  onRetry: () => void;
}

function Thread({ events, error, staffMap, onRetry }: ThreadProps) {
  if (error) {
    return (
      <EmptyState
        icon="⚠"
        title="처리 내역을 불러오지 못했습니다"
        description={error}
        action={<Button onClick={onRetry}>다시 시도</Button>}
      />
    );
  }
  if (events === null) {
    return (
      <div className="ia-thread-loading">
        <Skeleton height="2.5rem" />
        <Skeleton height="2.5rem" />
      </div>
    );
  }
  if (events.length === 0) {
    return <p className="ia-thread__empty">아직 처리 내역이 없습니다.</p>;
  }
  return (
    <ol className="ia-thread">
      {events.map((ev) => {
        const kind = ev.type === "comment" ? commentKind(ev.payload) : null;
        if (kind === "reply" || kind === "feedback") {
          const sender = kind === "reply" ? staffLabel(staffMap, ev.actorUserId) : null;
          return (
            <li key={ev.id} className={`ia-msg ia-msg--${kind}`}>
              <div className="ia-msg__meta">
                <span className="ia-msg__from">
                  {kind === "reply" ? (sender ?? "관리사무소") : "입주민"}
                </span>
                <span className="ia-msg__time">{shortDate(ev.createdAt)}</span>
              </div>
              <p className="ia-msg__body">{commentBody(ev.payload)}</p>
            </li>
          );
        }
        const desc = ev.type === "status_changed" ? formatStatusChange(ev.payload) : null;
        return (
          <li key={ev.id} className="ia-sys">
            <span className="ia-sys__dot" aria-hidden="true" />
            <span className="ia-sys__label">{eventLabel(ev.type)}</span>
            {desc ? <span className="ia-sys__desc">{desc}</span> : null}
            <span className="ia-sys__time">{shortDate(ev.createdAt)}</span>
          </li>
        );
      })}
    </ol>
  );
}
