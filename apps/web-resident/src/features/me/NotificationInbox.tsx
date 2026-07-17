"use client";

import { Button, EmptyState, Skeleton } from "@liviq/ui";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  listNotifications,
  markNotificationRead,
  type AppNotification,
} from "@/lib/api";
import {
  isUnread,
  markReadInList,
  notificationDate,
  notificationIcon,
  unreadCount,
} from "./notifications";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function NotificationInbox() {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listNotifications());
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

  const handleRead = useCallback(async (notification: AppNotification) => {
    if (!isUnread(notification)) return;
    try {
      const updated = await markNotificationRead(notification.id);
      setItems((prev) => markReadInList(prev, updated.id, updated.readAt ?? updated.createdAt));
    } catch {
      // 읽음 실패는 조용히 무시 — 다음 조회 시 서버 상태로 재동기화(멱등).
    }
  }, []);

  const unread = unreadCount(items);

  return (
    <section className="me-section">
      <h2 className="me-section__title">
        알림{unread > 0 ? <span className="me-notif__count">{unread}</span> : null}
      </h2>
      <InboxBody
        items={items}
        loading={loading}
        loadError={loadError}
        onRead={handleRead}
        onRetry={() => {
          setLoading(true);
          void load();
        }}
      />
    </section>
  );
}

interface InboxBodyProps {
  items: readonly AppNotification[];
  loading: boolean;
  loadError: string | null;
  onRead: (notification: AppNotification) => void;
  onRetry: () => void;
}

function InboxBody({ items, loading, loadError, onRead, onRetry }: InboxBodyProps) {
  if (loading) {
    return (
      <div className="me-group">
        <Skeleton height="4rem" />
        <Skeleton height="4rem" />
      </div>
    );
  }
  if (loadError) {
    return (
      <EmptyState
        icon="⚠"
        title="알림을 불러오지 못했습니다"
        description={loadError}
        action={<Button onClick={onRetry}>다시 시도</Button>}
      />
    );
  }
  if (items.length === 0) {
    return (
      <EmptyState
        icon="🔔"
        title="새 알림이 없습니다"
        description="공지·민원 상태·검수 결과 알림이 여기에 표시됩니다."
      />
    );
  }
  return (
    <div className="me-group">
      {items.map((n) => (
        <NotificationRow key={n.id} notification={n} onRead={onRead} />
      ))}
    </div>
  );
}

function NotificationRow({
  notification,
  onRead,
}: {
  notification: AppNotification;
  onRead: (notification: AppNotification) => void;
}) {
  const unread = isUnread(notification);
  return (
    <button
      type="button"
      className="me-row me-notif-row"
      data-unread={unread || undefined}
      onClick={() => onRead(notification)}
    >
      <span className="me-row__icon" aria-hidden="true">
        {notificationIcon(notification.type)}
      </span>
      <span className="me-row__body">
        <span className="me-notif-row__title">
          {unread ? (
            <span className="me-notif-row__dot" aria-label="읽지 않음" />
          ) : null}
          {notification.title}
        </span>
        {notification.body ? (
          <span className="me-notif-row__desc">{notification.body}</span>
        ) : null}
        <span className="me-row__meta">{notificationDate(notification.createdAt)}</span>
      </span>
    </button>
  );
}
