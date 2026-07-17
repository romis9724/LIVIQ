"use client";

import { Button, EmptyState, Skeleton } from "@liviq/ui";
import { useCallback, useEffect, useState } from "react";

import { ApiError, listNotices, type Notice } from "@/lib/api";
import { formatDate, toParagraphs } from "./data";
import "./notices.css";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function NoticeBoard() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);

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

  const open = openId ? notices.find((n) => n.id === openId) ?? null : null;
  if (open) {
    return <NoticeDetail notice={open} onBack={() => setOpenId(null)} />;
  }

  return (
    <div className="notices">
      <header className="notices__header">
        <h1 id="main" className="notices__title">
          공지
        </h1>
      </header>

      <NoticeList
        notices={notices}
        loading={loading}
        loadError={loadError}
        onSelect={setOpenId}
        onRetry={() => {
          setLoading(true);
          void load();
        }}
      />
    </div>
  );
}

interface NoticeListProps {
  notices: readonly Notice[];
  loading: boolean;
  loadError: string | null;
  onSelect: (id: string) => void;
  onRetry: () => void;
}

function NoticeList({ notices, loading, loadError, onSelect, onRetry }: NoticeListProps) {
  if (loading) {
    return (
      <main className="notices__list">
        <Skeleton height="5rem" radius="var(--radius-md)" />
        <Skeleton height="5rem" radius="var(--radius-md)" />
        <Skeleton height="5rem" radius="var(--radius-md)" />
      </main>
    );
  }
  if (loadError) {
    return (
      <main className="notices__list">
        <EmptyState
          icon="⚠"
          title="공지를 불러오지 못했습니다"
          description={loadError}
          action={<Button onClick={onRetry}>다시 시도</Button>}
        />
      </main>
    );
  }
  if (notices.length === 0) {
    return (
      <main className="notices__list">
        <EmptyState
          icon="📢"
          title="등록된 공지가 없습니다"
          description="새 공지가 발행되면 여기에 표시됩니다."
        />
      </main>
    );
  }
  return (
    <main className="notices__list">
      {notices.map((n) => (
        <button key={n.id} type="button" className="notice-card" onClick={() => onSelect(n.id)}>
          <div className="notice-card__top">
            <span className="notice-card__date">{formatDate(n.publishedAt)}</span>
          </div>
          <div className="notice-card__title">{n.title}</div>
        </button>
      ))}
    </main>
  );
}

function NoticeDetail({ notice, onBack }: { notice: Notice; onBack: () => void }) {
  return (
    <div className="notices">
      <header className="notice-detail__bar">
        <button type="button" className="notice-detail__back" aria-label="목록으로" onClick={onBack}>
          ←
        </button>
        <span className="notice-detail__barlabel">공지 상세</span>
      </header>
      <main id="main" className="notice-detail">
        <div className="notice-detail__meta">
          <span className="notice-detail__metatext">관리사무소 · {formatDate(notice.publishedAt)}</span>
        </div>
        <h1 className="notice-detail__title">{notice.title}</h1>
        <div className="notice-detail__body">
          {toParagraphs(notice.body).map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>
      </main>
    </div>
  );
}
