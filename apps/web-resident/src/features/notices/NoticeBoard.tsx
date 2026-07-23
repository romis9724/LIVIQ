"use client";

import { Button, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, downloadAttachment, listNotices, type Attachment, type Notice } from "@/lib/api";
import { formatDate, formatFileSize, toParagraphs } from "./data";
import "./notices.css";

const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function NoticeBoard() {
  const [notices, setNotices] = useState<Notice[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // 열린 상세는 URL(?id=<공지>)이 단일 출처 — 선택 시 push로 히스토리 항목을 쌓고,
  // 뒤로가기는 router.back()으로 "온 곳"(홈이면 홈·목록이면 목록)으로 그대로 돌아간다.
  const router = useRouter();
  const openId = useSearchParams().get("id");
  const openNotice = useCallback((id: string) => router.push(`/notices?id=${id}`), [router]);
  const goBack = useCallback(() => router.back(), [router]);

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
    return <NoticeDetail notice={open} onBack={goBack} />;
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
        onSelect={openNotice}
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
            {n.pinned ? (
              <span className="notice-badge notice-badge--pinned">📌 고정</span>
            ) : null}
            <span className="notice-card__date">{formatDate(n.publishedAt)}</span>
            {n.attachments.length > 0 ? (
              <span className="notice-card__clip" aria-label={`첨부 ${n.attachments.length}개`}>
                📎 {n.attachments.length}
              </span>
            ) : null}
          </div>
          <div className="notice-card__title">{n.title}</div>
        </button>
      ))}
    </main>
  );
}

function NoticeDetail({ notice, onBack }: { notice: Notice; onBack: () => void }) {
  const [toast, setToast] = useState<ToastState | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone) => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const handleDownload = useCallback(
    async (attachment: Attachment) => {
      setDownloadingId(attachment.id);
      try {
        await downloadAttachment(notice.id, attachment);
      } catch (err) {
        showToast(`다운로드에 실패했습니다. ${errorMessage(err)}`, "danger");
      } finally {
        setDownloadingId(null);
      }
    },
    [notice.id, showToast],
  );

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
          {notice.pinned ? (
            <span className="notice-badge notice-badge--pinned">📌 고정</span>
          ) : null}
          <span className="notice-detail__metatext">
            관리사무소 · {formatDate(notice.publishedAt)}
          </span>
        </div>
        <h1 className="notice-detail__title">{notice.title}</h1>
        <div className="notice-detail__body">
          {toParagraphs(notice.body).map((para, i) => (
            <p key={i}>{para}</p>
          ))}
        </div>

        {notice.attachments.length > 0 ? (
          <section className="notice-attach" aria-labelledby="notice-attach-heading">
            <h2 id="notice-attach-heading" className="notice-attach__heading">
              첨부파일
            </h2>
            <ul className="notice-attach__list">
              {notice.attachments.map((att) => (
                <li key={att.id}>
                  <button
                    type="button"
                    className="notice-attach__item"
                    onClick={() => void handleDownload(att)}
                    disabled={downloadingId === att.id}
                  >
                    <span className="notice-attach__icon" aria-hidden="true">
                      📎
                    </span>
                    <span className="notice-attach__name">{att.filename}</span>
                    <span className="notice-attach__size">
                      {downloadingId === att.id ? "받는 중…" : formatFileSize(att.sizeBytes)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>

      {toast ? (
        <div className="notice-toast-slot">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </div>
  );
}
