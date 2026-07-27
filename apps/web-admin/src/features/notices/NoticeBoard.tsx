"use client";

import { Button, EmptyState, FilterChips, PageToolbar, Skeleton } from "@liviq/ui";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, listCodeGroups, listNotices, type Notice } from "@/lib/api";
import { NOTICE_CATEGORY_GROUP, codeLabelMap } from "@/lib/codes";
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
  const visibleRows = useMemo(
    () => (statusFilter === "all" ? rows : rows.filter((n) => n.status === statusFilter)),
    [rows, statusFilter],
  );

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
              onChange={setStatusFilter}
              label="상태 필터"
            />
          }
          end={
            <Link href="/notices/new" className="btn btn--primary">
              새 공지 작성
            </Link>
          }
        />
        <NoticeBoardBody
          loading={loading}
          loadError={loadError}
          rows={visibleRows}
          filtered={statusFilter !== "all"}
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

interface BodyProps {
  loading: boolean;
  loadError: string | null;
  rows: readonly Notice[];
  /** 상태 필터가 걸린 상태 — 빈 목록 문구를 구분한다(docs/05 §9). */
  filtered: boolean;
  categoryLabels: Map<string, string>;
  onRetry: () => void;
}

function NoticeBoardBody({
  loading,
  loadError,
  rows,
  filtered,
  categoryLabels,
  onRetry,
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
        title="해당 상태의 공지가 없습니다"
        description="다른 상태를 선택해 보세요."
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
    <div className="surface-card notice-tablecard">
      <div className="notice-table__scroll">
        <table className="notice-table">
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
    </div>
  );
}
