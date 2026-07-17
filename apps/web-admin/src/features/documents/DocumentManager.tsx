"use client";

import { Button, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  listDocuments,
  patchDocument,
  reindexDocument,
  uploadDocument,
  type DocumentItem,
  type UploadInput,
  type Visibility,
} from "@/lib/api";
import { DocumentTable } from "./DocumentTable";
import { UploadPanel } from "./UploadPanel";
import {
  STATUS_FILTERS,
  filterDocs,
  hasActiveIndexing,
  summarize,
  type StatusFilter,
} from "./data";
import "./documents.css";

// ponytail: 폴링, 문서량 커지면 SSE/웹소켓
const POLL_INTERVAL_MS = 5000;
const SEARCH_DEBOUNCE_MS = 300;
const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function DocumentManager() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  // 전체 목록 1회 로드 후 클라이언트에서 필터·집계 — 집계를 필터 탭과 무관하게 유지(브리프 선택지).
  const load = useCallback(async () => {
    try {
      const items = await listDocuments();
      setDocs(items);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 검색어 디바운스(300ms) — 클라이언트 필터에만 사용.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  // pending·indexing 문서가 있으면 5초 폴링, 전부 완료/실패되면 중단.
  const polling = hasActiveIndexing(docs);
  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [polling, load]);

  useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const summary = useMemo(() => summarize(docs), [docs]);
  const visibleDocs = useMemo(
    () => filterDocs(docs, statusFilter, debouncedSearch),
    [docs, statusFilter, debouncedSearch],
  );

  async function handleUpload(input: UploadInput) {
    setUploading(true);
    try {
      const result = await uploadDocument(input);
      showToast(
        result.duplicate ? "이미 등록된 문서입니다." : "업로드했습니다. 색인을 시작합니다.",
        result.duplicate ? "neutral" : "success",
      );
      await load();
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setUploading(false);
    }
  }

  async function handleChangeVisibility(id: string, visibility: Visibility) {
    setBusyId(id);
    try {
      const updated = await patchDocument(id, { visibility });
      setDocs((prev) => prev.map((doc) => (doc.id === id ? updated : doc)));
      showToast("공개 범위를 변경했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReindex(id: string) {
    setBusyId(id);
    try {
      const updated = await reindexDocument(id);
      setDocs((prev) => prev.map((doc) => (doc.id === id ? updated : doc)));
      showToast("재색인을 요청했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          문서 관리
        </h1>
        <p className="admin-page__lede">
          업로드한 문서가 색인되면 AI가 출처로 인용합니다. 색인 실패 문서는 인용되지 않으니
          재색인하세요.
        </p>
      </header>

      <main className="admin-page__main doc-main">
        <UploadPanel uploading={uploading} onUpload={handleUpload} />

        <div className="doc-summary">
          <SummaryCard label="색인 완료" count={summary.indexed} color="var(--color-success)" />
          <SummaryCard label="색인 중" count={summary.indexing} color="var(--color-accent)" />
          <SummaryCard label="대기" count={summary.pending} color="var(--color-text-muted)" />
          <SummaryCard label="실패" count={summary.failed} color="var(--color-danger)" />
        </div>

        <div className="doc-toolbar">
          <div className="doc-filters" role="group" aria-label="색인 상태 필터">
            {STATUS_FILTERS.map((filter) => (
              <button
                key={filter.value}
                type="button"
                className="doc-filter"
                aria-pressed={statusFilter === filter.value}
                onClick={() => setStatusFilter(filter.value)}
              >
                {filter.label}
              </button>
            ))}
          </div>
          <input
            className="doc-input doc-search"
            type="search"
            value={search}
            placeholder="제목 검색"
            aria-label="문서 제목 검색"
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>

        <DocumentsBody
          loading={loading}
          loadError={loadError}
          docs={docs}
          visibleDocs={visibleDocs}
          busyId={busyId}
          onRetry={() => {
            setLoading(true);
            void load();
          }}
          onChangeVisibility={handleChangeVisibility}
          onReindex={handleReindex}
        />
      </main>

      {toast ? (
        <div className="doc-toast-slot">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}

function SummaryCard({ label, count, color }: { label: string; count: number; color: string }) {
  return (
    <div className="doc-summary__card">
      <span className="doc-summary__dot" style={{ background: color }} aria-hidden="true" />
      <span className="doc-summary__label">{label}</span>
      <span className="doc-summary__count">{count}</span>
    </div>
  );
}

interface DocumentsBodyProps {
  loading: boolean;
  loadError: string | null;
  docs: readonly DocumentItem[];
  visibleDocs: readonly DocumentItem[];
  busyId: string | null;
  onRetry: () => void;
  onChangeVisibility: (id: string, visibility: Visibility) => void;
  onReindex: (id: string) => void;
}

function DocumentsBody({
  loading,
  loadError,
  docs,
  visibleDocs,
  busyId,
  onRetry,
  onChangeVisibility,
  onReindex,
}: DocumentsBodyProps) {
  if (loading) {
    return (
      <div className="surface-card doc-tablecard doc-loading">
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
        title="문서를 불러오지 못했습니다"
        description={loadError}
        action={<Button onClick={onRetry}>다시 시도</Button>}
      />
    );
  }
  if (docs.length === 0) {
    return (
      <EmptyState
        icon="📄"
        title="등록된 문서가 없습니다"
        description="관리규약·공지·회의록을 업로드하면 AI가 출처로 인용합니다."
      />
    );
  }
  if (visibleDocs.length === 0) {
    return (
      <EmptyState
        icon="🔍"
        title="조건에 맞는 문서가 없습니다"
        description="필터나 검색어를 조정해 보세요."
      />
    );
  }
  return (
    <DocumentTable
      docs={visibleDocs}
      busyId={busyId}
      onChangeVisibility={onChangeVisibility}
      onReindex={onReindex}
    />
  );
}
