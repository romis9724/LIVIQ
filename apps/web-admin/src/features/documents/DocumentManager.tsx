"use client";

import {
  Button,
  EmptyState,
  FilterChips,
  PageToolbar,
  Pagination,
  SearchField,
  Skeleton,
  StatCard,
  StatGrid,
} from "@liviq/ui";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";

import { ApiError, listCodeGroups, listDocuments, type DocumentItem } from "@/lib/api";
import { DOC_CATEGORY_GROUP, codeLabelMap } from "@/lib/codes";
import { usePaging } from "@/lib/paging";
import { DocumentTable } from "./DocumentTable";
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

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function DocumentManager() {
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [category, setCategory] = useState("");
  // 검색어 input은 uncontrolled(ref) — controlled value는 한글 IME 조합 중 리렌더로 조합이
  // 깨진다(마지막 자모 씹힘). 제출 시에만 ref 값을 읽어 적용한다.
  const searchRef = useRef<HTMLInputElement>(null);
  // 검색 버튼/Enter 로만 적용 — 타이핑 중에는 목록이 바뀌지 않는다.
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

  // 전량 로드 후 클라이언트 페이징 — 필터·검색이 바뀌면 1페이지로 되돌린다.
  const paging = usePaging(visibleDocs);
  const { reset: resetPage } = paging;

  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAppliedQuery(searchRef.current?.value ?? "");
    setAppliedCategory(category);
    resetPage();
  };

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          문서 관리
        </h1>
      </header>

      <main className="admin-page__main doc-main">
        {/* 값 색은 0건일 때 쓰지 않는다 — 없는 상태를 강조색으로 알리지 않기 위해(docs/05 §5A). */}
        <StatGrid>
          <StatCard
            label="색인 완료"
            value={summary.indexed}
            tone={summary.indexed > 0 ? "success" : "default"}
          />
          <StatCard label="색인 중" value={summary.indexing} />
          <StatCard label="대기" value={summary.pending} />
          <StatCard
            label="실패"
            value={summary.failed}
            tone={summary.failed > 0 ? "danger" : "default"}
          />
        </StatGrid>

        <PageToolbar
          start={
            <FilterChips
              items={STATUS_FILTERS}
              value={statusFilter}
              onChange={(id) => {
                setStatusFilter(id);
                resetPage();
              }}
              label="색인 상태 필터"
            />
          }
          end={
            <>
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
                <SearchField ref={searchRef} label="문서 제목 검색" defaultValue="" placeholder="제목 검색" />
                <Button type="submit" variant="secondary">
                  검색
                </Button>
              </form>
              <Link href="/documents/new" className="btn btn--primary">
                새 문서
              </Link>
            </>
          }
        />

        <DocumentsBody
          loading={loading}
          loadError={loadError}
          docs={docs}
          visibleDocs={paging.rows}
          categoryLabels={categoryLabels}
          onRetry={() => {
            setLoading(true);
            void load();
          }}
          pager={
            paging.totalPages > 1 ? (
              <Pagination
                page={paging.page}
                totalPages={paging.totalPages}
                totalCount={visibleDocs.length}
                onPage={paging.setPage}
                label="문서 목록 페이지"
              />
            ) : null
          }
        />
      </main>
    </>
  );
}

interface DocumentsBodyProps {
  loading: boolean;
  loadError: string | null;
  docs: readonly DocumentItem[];
  /** 현재 페이지 분량만 받는다(페이징은 부모가 계산). */
  visibleDocs: readonly DocumentItem[];
  categoryLabels: Map<string, string>;
  onRetry: () => void;
  /** 표 카드 하단 페이저 — 1페이지뿐이면 null. */
  pager: ReactNode;
}

function DocumentsBody({
  loading,
  loadError,
  docs,
  visibleDocs,
  categoryLabels,
  onRetry,
  pager,
}: DocumentsBodyProps) {
  if (loading) {
    return (
      <div className="surface-card admin-tablecard doc-loading">
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
  return <DocumentTable docs={visibleDocs} categoryLabels={categoryLabels} pager={pager} />;
}
