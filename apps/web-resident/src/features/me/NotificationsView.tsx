"use client";

import { Toast } from "@liviq/ui";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { NotificationListBody } from "./NotificationList";
import { unreadCount } from "./notifications";
import { useNotificationInbox } from "./useNotificationInbox";
import "./me.css";

// 전체 목록은 한 번에 넉넉히 로드 — 무한 스크롤은 수요 확인 후(YAGNI).
const FULL_LIMIT = 100;
const TOAST_DURATION_MS = 3200;

/** 알림 전체 목록 — 나 페이지 "더보기"로 진입. 개별 삭제는 여기서만. 뒤로가기로 온 곳(나)으로 복귀. */
export function NotificationsView() {
  const router = useRouter();
  const { items, loading, loadError, deleteError, handleRead, handleDelete, dismissDeleteError, retry } =
    useNotificationInbox(FULL_LIMIT);
  const unread = unreadCount(items);

  // 삭제 실패 토스트 자동 소멸.
  useEffect(() => {
    if (!deleteError) return;
    const timer = setTimeout(dismissDeleteError, TOAST_DURATION_MS);
    return () => clearTimeout(timer);
  }, [deleteError, dismissDeleteError]);

  return (
    <div className="me-notif-page">
      <header className="me-notif-page__bar">
        <button
          type="button"
          className="me-notif-page__back"
          aria-label="뒤로가기"
          onClick={() => router.back()}
        >
          ←
        </button>
        <h1 id="main" className="me-notif-page__title">
          알림{unread > 0 ? <span className="me-notif__count">{unread}</span> : null}
        </h1>
      </header>
      <main className="me-notif-page__main">
        <NotificationListBody
          items={items}
          loading={loading}
          loadError={loadError}
          onRead={handleRead}
          onRetry={retry}
          onDelete={handleDelete}
        />
      </main>
      {deleteError ? (
        <div className="me-notif-page__toast">
          <Toast message={deleteError} tone="danger" />
        </div>
      ) : null}
    </div>
  );
}
