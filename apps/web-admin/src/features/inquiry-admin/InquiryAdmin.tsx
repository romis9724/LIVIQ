"use client";

import { Button, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  assignInquiry,
  getMe,
  listAdminInquiries,
  updateInquiryStatus,
  type Inquiry,
  type InquiryStatus,
} from "@/lib/api";
import {
  FILTERS,
  PRIORITY_META,
  STATUS_META,
  countByStatus,
  nextStatuses,
  shortDate,
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

export function InquiryAdmin() {
  const [inquiries, setInquiries] = useState<Inquiry[]>([]);
  // 로그인 세션의 자기 user id — '나에게 배정' 대상. /me 로 취득(로드 전엔 null).
  const [myUserId, setMyUserId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterId>("all");
  const [search, setSearch] = useState("");
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
    // 자기 신원은 배정에만 필요 — 실패해도 목록 로드는 막지 않는다.
    void getMe()
      .then((me) => setMyUserId(me.userId))
      .catch(() => undefined);
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const counts = useMemo(() => countByStatus(inquiries), [inquiries]);
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return inquiries.filter((inquiry) => {
      if (filter !== "all" && inquiry.status !== filter) return false;
      if (q && !inquiry.title.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [inquiries, filter, search]);

  function patchLocal(updated: Inquiry) {
    setInquiries((prev) => prev.map((it) => (it.id === updated.id ? updated : it)));
  }

  async function handleStatus(id: string, status: InquiryStatus) {
    setBusyId(id);
    try {
      patchLocal(await updateInquiryStatus(id, status));
      showToast(`상태를 '${STATUS_META[status].label}'(으)로 변경했습니다.`);
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  async function handleAssign(id: string) {
    if (!myUserId) {
      showToast("로그인 정보를 확인할 수 없어 배정할 수 없습니다.", "danger");
      return;
    }
    setBusyId(id);
    try {
      patchLocal(await assignInquiry(id, myUserId));
      showToast("나에게 배정했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <header className="admin-page__header">
        <div className="ia-head">
          <div>
            <h1 id="main" className="admin-page__title">
              민원 관리
            </h1>
            <p className="admin-page__lede">
              AI가 분류·우선순위를 제안합니다. 담당자 배정은 직접 확정합니다.
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
          busyId={busyId}
          onRetry={() => {
            setLoading(true);
            void load();
          }}
          onStatus={handleStatus}
          onAssign={handleAssign}
        />
      </main>

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
  busyId: string | null;
  onRetry: () => void;
  onStatus: (id: string, status: InquiryStatus) => void;
  onAssign: (id: string) => void;
}

function InquiryBody({
  loading,
  loadError,
  inquiries,
  visible,
  busyId,
  onRetry,
  onStatus,
  onAssign,
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
              <th scope="col">AI 분류</th>
              <th scope="col">우선순위</th>
              <th scope="col">상태</th>
              <th scope="col">담당</th>
              <th scope="col">접수일</th>
              <th scope="col" className="ia-table__right">
                처리
              </th>
            </tr>
          </thead>
          <tbody>
            {visible.map((inquiry) => (
              <InquiryRow
                key={inquiry.id}
                inquiry={inquiry}
                busy={busyId === inquiry.id}
                onStatus={onStatus}
                onAssign={onAssign}
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
  busy: boolean;
  onStatus: (id: string, status: InquiryStatus) => void;
  onAssign: (id: string) => void;
}

function InquiryRow({ inquiry, busy, onStatus, onAssign }: InquiryRowProps) {
  const status = STATUS_META[inquiry.status];
  const priority = inquiry.aiPriority ? PRIORITY_META[inquiry.aiPriority] : null;
  const options = nextStatuses(inquiry.status);
  const assigned = inquiry.assigneeUserId !== null;

  return (
    <tr>
      <td className="ia-cell--id">{inquiry.id.slice(0, 8)}</td>
      <td>
        <div className="ia-cell__title">{inquiry.title}</div>
        {/* ponytail: 접수자 이름은 사용자 목록 api 도입 시 — 현재는 마스킹 정책상 미표시 */}
        <div className="ia-cell__asker">입주민</div>
      </td>
      <td className="ia-nowrap">
        {/* ponytail: 카테고리 이름 표시는 카테고리 api 도입 시 — 지금은 제안 유무만 */}
        <span className="ia-cat__name">
          {inquiry.aiSuggestedCategoryId ? "AI 제안" : "—"}
        </span>
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
      <td className="ia-nowrap" data-muted={!assigned || undefined}>
        {/* ponytail: 담당자 이름은 사용자 목록 api 도입 시 */}
        {assigned ? "배정됨" : "미배정"}
      </td>
      <td className="ia-nowrap ia-cell--date">{shortDate(inquiry.createdAt)}</td>
      <td className="ia-nowrap ia-table__right">
        <div className="ia-actions">
          {options.length > 0 ? (
            <select
              className="ia-status-select"
              aria-label="상태 변경"
              disabled={busy}
              value=""
              onChange={(e) => {
                if (e.target.value) onStatus(inquiry.id, e.target.value as InquiryStatus);
              }}
            >
              <option value="" disabled>
                상태 변경
              </option>
              {options.map((opt) => (
                <option key={opt} value={opt}>
                  {STATUS_META[opt].label}
                </option>
              ))}
            </select>
          ) : null}
          {!assigned ? (
            <button
              type="button"
              className="btn btn--primary btn--sm"
              disabled={busy}
              onClick={() => onAssign(inquiry.id)}
            >
              나에게 배정
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  );
}
