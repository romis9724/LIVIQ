"use client";

import { Button, EmptyState, Skeleton } from "@liviq/ui";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";

import { ApiError, listCodeGroups, listDocuments, type DocumentItem } from "@/lib/api";
import { DOC_CATEGORY_GROUP, codeLabelMap } from "@/lib/codes";
import { DocumentTable } from "./DocumentTable";
import {
  INDEX_META,
  STATUS_FILTERS,
  filterDocs,
  hasActiveIndexing,
  summarize,
  type StatusFilter,
} from "./data";
import "./documents.css";

// ponytail: 폴링, 문서량 커지면 SSE/웹소켓
const POLL_INTERVAL_MS = 5000;

type SummaryTone = "success" | "accent" | "neutral" | "danger";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function DocumentManager() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  // 검색 버튼/Enter 로만 적용 — 타이핑 중에는 목록이 바뀌지 않는다(한글 IME 조합 오작동 방지).
  const [appliedQuery, setAppliedQuery] = useState("");
  const [appliedCategory, setAppliedCategory] = useState("");
  const [categoryLabels, setCategoryLabels] = useState<Map<string, string>>(new Map());

  // 전체 목록 1회 로드 후 클라이언트에서 필터·집계 — 집계를 필터 탭과 무관하게 유지.
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

  // 분류 코드 라벨(목록 표시용) — 실패 시 "미분류"로 폴백.
  useEffect(() => {
    void (async () => {
      try {
        setCategoryLabels(codeLabelMap(await listCodeGroups(), DOC_CATEGORY_GROUP));
      } catch {
        // 무시 — 라벨 없이 "미분류" 표시.
      }
    })();
  }, []);

  // pending·indexing 문서가 있으면 5초 폴링, 전부 완료/실패되면 중단.
  const polling = hasActiveIndexing(docs);
  useEffect(() => {
    if (!polling) return;
    const timer = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [polling, load]);

  const summary = useMemo(() => summarize(docs), [docs]);
  const visibleDocs = useMemo(
    () => filterDocs(docs, statusFilter, appliedQuery, appliedCategory),
    [docs, statusFilter, appliedQuery, appliedCategory],
  );

  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAppliedQuery(search);
    setAppliedCategory(category);
  };

  return (
    <>
      <header className="admin-page__header doc-head">
        <div className="doc-head__text">
          <h1 id="main" className="admin-page__title">
            문서 관리
          </h1>
          <p className="admin-page__lede">
            관리규약·회의록·지침을 게시글로 관리합니다. 첨부 문서가 색인되면 AI가 출처로 인용하며,
            개정판을 올리면 최신본을 따라갑니다.
          </p>
        </div>
        <Link href="/documents/new" className="btn btn--primary">
          새 문서
        </Link>
      </header>

      <main className="admin-page__main doc-main">
        <div className="doc-summary">
          <SummaryCard
            icon={INDEX_META.indexed.icon}
            label="색인 완료"
            count={summary.indexed}
            tone="success"
          />
          <SummaryCard
            icon={INDEX_META.indexing.icon}
            label="색인 중"
            count={summary.indexing}
            tone="accent"
          />
          <SummaryCard
            icon={INDEX_META.pending.icon}
            label="대기"
            count={summary.pending}
            tone="neutral"
          />
          <SummaryCard
            icon={INDEX_META.failed.icon}
            label="실패"
            count={summary.failed}
            tone="danger"
          />
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
          <form className="doc-searchform" onSubmit={applySearch}>
            <select
              className="doc-select doc-searchform__category"
              value={category}
              aria-label="문서 분류 필터"
              onChange={(event) => setCategory(event.target.value)}
            >
              <option value="">전체 분류</option>
              {[...categoryLabels].map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
            <input
              className="doc-input doc-search"
              type="search"
              value={search}
              placeholder="제목 검색"
              aria-label="문서 제목 검색"
              onChange={(event) => setSearch(event.target.value)}
            />
            <Button type="submit" variant="secondary">
              검색
            </Button>
          </form>
        </div>

        <DocumentsBody
          loading={loading}
          loadError={loadError}
          docs={docs}
          visibleDocs={visibleDocs}
          categoryLabels={categoryLabels}
          onRetry={() => {
            setLoading(true);
            void load();
          }}
        />
      </main>
    </>
  );
}

function SummaryCard({
  icon,
  label,
  count,
  tone,
}: {
  icon: string;
  label: string;
  count: number;
  tone: SummaryTone;
}) {
  return (
    <div className={`surface-card doc-summary__card doc-summary__card--${tone}`}>
      <span className="doc-summary__icon" aria-hidden="true">
        {icon}
      </span>
      <span className="doc-summary__count">{count}</span>
      <span className="doc-summary__label">{label}</span>
    </div>
  );
}

interface DocumentsBodyProps {
  loading: boolean;
  loadError: string | null;
  docs: readonly DocumentItem[];
  visibleDocs: readonly DocumentItem[];
  categoryLabels: Map<string, string>;
  onRetry: () => void;
}

function DocumentsBody({
  loading,
  loadError,
  docs,
  visibleDocs,
  categoryLabels,
  onRetry,
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
        description="‘새 문서’로 관리규약·공지·회의록을 올리면 AI가 출처로 인용합니다."
        action={
          <Link href="/documents/new" className="btn btn--primary">
            새 문서
          </Link>
        }
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
  return <DocumentTable docs={visibleDocs} categoryLabels={categoryLabels} />;
}
