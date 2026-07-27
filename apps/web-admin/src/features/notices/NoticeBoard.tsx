"use client";

import {
  Button,
  EmptyState,
  FilterChips,
  PageToolbar,
  Pagination,
  SearchField,
  Skeleton,
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

import { ApiError, listCodeGroups, listNotices, type Notice } from "@/lib/api";
import { NOTICE_CATEGORY_GROUP, codeLabelMap } from "@/lib/codes";
import { usePaging } from "@/lib/paging";
import { STATUS_META, shortDate, shortDateTime, sortNotices } from "./data";
import "./notices.css";

const STATUS_FILTERS = [
  { id: "all", label: "전체" },
  { id: "draft", label: "임시저장" },
  { id: "scheduled", label: "예약" },
  { id: "published", label: "발행" },
] as const;

type StatusFilter = (typeof STATUS_FILTERS)[number]["id"];

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function NoticeBoard() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [categoryLabels, setCategoryLabels] = useState<Map<string, string>>(new Map());
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  // 검색은 문서 관리와 동일 UX — uncontrolled(한글 IME) + 검색 버튼/Enter 제출 시 적용.
  const searchRef = useRef<HTMLInputElement>(null);
  const [appliedQuery, setAppliedQuery] = useState("");

  const load = useCallback(async () => {
    try {
      setNotices(await listNotices());
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

  // 분류 코드 라벨(목록 배지용) — 실패 시 배지 생략.
  useEffect(() => {
    void (async () => {
      try {
        setCategoryLabels(codeLabelMap(await listCodeGroups(), NOTICE_CATEGORY_GROUP));
      } catch {
        // 무시 — 분류 배지 없이 목록 표시.
      }
    })();
  }, []);

  const rows = useMemo(() => sortNotices(notices), [notices]);
  const chips = useMemo(
    () =>
      STATUS_FILTERS.map((f) => ({
        ...f,
        count: f.id === "all" ? rows.length : rows.filter((n) => n.status === f.id).length,
      })),
    [rows],
  );
  const visibleRows = useMemo(() => {
    const q = appliedQuery.trim().toLowerCase();
    return rows.filter((n) => {
      if (statusFilter !== "all" && n.status !== statusFilter) return false;
      // 제목·공지 내용 모두 검색(민원 관리와 같은 패턴).
      if (q && !n.title.toLowerCase().includes(q) && !n.body.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [rows, statusFilter, appliedQuery]);

  // 전량 로드 후 클라이언트 페이징 — 필터·검색이 바뀌면 1페이지로 되돌린다.
  const paging = usePaging(visibleRows);
  const { reset: resetPage } = paging;

  const applySearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setAppliedQuery(searchRef.current?.value ?? "");
    resetPage();
  };

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          공지사항
        </h1>
      </header>

      <main className="admin-page__main">
        <PageToolbar
          start={
            <FilterChips
              items={chips}
              value={statusFilter}
              onChange={(id) => {
                setStatusFilter(id);
                resetPage();
              }}
              label="상태 필터"
            />
          }
          end={
            <>
              <form className="notice-searchform" onSubmit={applySearch}>
                <SearchField ref={searchRef} label="공지 검색" placeholder="제목·내용 검색" />
                <Button type="submit" variant="secondary">
                  검색
                </Button>
              </form>
              <Link href="/notices/new" className="btn btn--primary">
                새 공지 작성
              </Link>
            </>
          }
        />
        <NoticeBoardBody
          loading={loading}
          loadError={loadError}
          rows={paging.rows}
          filtered={statusFilter !== "all" || appliedQuery.trim() !== ""}
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
                totalCount={visibleRows.length}
                onPage={paging.setPage}
                label="공지 목록 페이지"
              />
            ) : null
          }
        />
      </main>
    </>
  );
}

interface BodyProps {
  loading: boolean;
  loadError: string | null;
  /** 현재 페이지 분량만 받는다(페이징은 부모가 계산). */
  rows: readonly Notice[];
  /** 상태 필터가 걸린 상태 — 빈 목록 문구를 구분한다(docs/05 §9). */
  filtered: boolean;
  categoryLabels: Map<string, string>;
  onRetry: () => void;
  /** 표 카드 하단 페이저 — 1페이지뿐이면 null. */
  pager: ReactNode;
}

function NoticeBoardBody({
  loading,
  loadError,
  rows,
  filtered,
  categoryLabels,
  onRetry,
  pager,
}: BodyProps) {
  if (loading) {
    return (
      <div className="surface-card notice-loading">
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
        title="공지를 불러오지 못했습니다"
        description={loadError}
        action={<Button onClick={onRetry}>다시 시도</Button>}
      />
    );
  }
  if (rows.length === 0) {
    return filtered ? (
      <EmptyState
        icon="📢"
        title="조건에 맞는 공지가 없습니다"
        description="다른 상태나 검색어로 다시 시도해 보세요."
      />
    ) : (
      <EmptyState
        icon="📢"
        title="등록된 공지가 없습니다"
        description="‘새 공지 작성’으로 첫 공지를 만들어 보세요."
      />
    );
  }
  return (
    <div className="surface-card admin-tablecard">
      <div className="admin-table__scroll">
        <table className="admin-table notice-table">
          <thead>
            <tr>
              <th scope="col">상태</th>
              <th scope="col">제목</th>
              <th scope="col">분류</th>
              <th scope="col">첨부</th>
              <th scope="col">작성일</th>
              <th scope="col">예약 시각</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((notice) => {
              const meta = STATUS_META[notice.status];
              return (
                <tr key={notice.id}>
                  <td className="notice-nowrap">
                    <span className={`notice-badge notice-badge--${meta.css}`}>
                      <span aria-hidden="true">{meta.icon}</span>
                      {meta.label}
                    </span>
                  </td>
                  <td>
                    <Link href={`/notices/${notice.id}`} className="notice-title-link">
                      {notice.pinned ? (
                        <span className="notice-pin" title="상단 고정" aria-label="상단 고정">
                          📌
                        </span>
                      ) : null}
                      <span className="notice-title-text">{notice.title}</span>
                    </Link>
                  </td>
                  <td className="notice-nowrap">
                    {notice.categoryCodeId && categoryLabels.has(notice.categoryCodeId) ? (
                      <span className="notice-cat">{categoryLabels.get(notice.categoryCodeId)}</span>
                    ) : (
                      <span className="notice-muted">—</span>
                    )}
                  </td>
                  <td className="notice-nowrap notice-muted">
                    {notice.attachments.length > 0 ? `📎 ${notice.attachments.length}` : "—"}
                  </td>
                  <td className="notice-nowrap notice-muted">{shortDate(notice.createdAt)}</td>
                  <td className="notice-nowrap notice-muted">
                    {notice.status === "scheduled" ? shortDateTime(notice.scheduledAt) : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {pager}
    </div>
  );
}
