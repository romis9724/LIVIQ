"use client";

import { Button, EmptyState, Skeleton } from "@liviq/ui";

import type { AppNotification } from "@/lib/api";
import { isUnread, notificationDate, notificationIcon } from "./notifications";

interface NotificationListBodyProps {
  items: readonly AppNotification[];
  loading: boolean;
  loadError: string | null;
  onRead: (notification: AppNotification) => void;
  onRetry: () => void;
  // 삭제는 전체 목록에서만 — 요약(나 페이지)은 미전달해 버튼을 숨긴다.
  onDelete?: (notification: AppNotification) => void;
}

/** 알림 목록 본문 — 요약(나 페이지)·전체(/notifications)가 공유하는 로딩/오류/빈/목록 렌더. */
export function NotificationListBody({
  items,
  loading,
  loadError,
  onRead,
  onRetry,
  onDelete,
}: NotificationListBodyProps) {
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
        <NotificationRow key={n.id} notification={n} onRead={onRead} onDelete={onDelete} />
      ))}
    </div>
  );
}

function NotificationRow({
  notification,
  onRead,
  onDelete,
}: {
  notification: AppNotification;
  onRead: (notification: AppNotification) => void;
  onDelete?: (notification: AppNotification) => void;
}) {
  const unread = isUnread(notification);
  return (
    <div className="me-row me-notif-row" data-unread={unread || undefined}>
      <button
        type="button"
        className="me-notif-row__hit"
        onClick={() => onRead(notification)}
      >
        <span className="me-row__icon" aria-hidden="true">
          {notificationIcon(notification.type)}
        </span>
        <span className="me-row__body">
          <span className="me-notif-row__title">
            {unread ? <span className="me-notif-row__dot" aria-label="읽지 않음" /> : null}
            {notification.title}
          </span>
          {notification.body ? (
            <span className="me-notif-row__desc">{notification.body}</span>
          ) : null}
          <span className="me-row__meta">{notificationDate(notification.createdAt)}</span>
        </span>
      </button>
      {onDelete ? (
        <button
          type="button"
          className="me-notif-row__del"
          aria-label="알림 삭제"
          onClick={(e) => {
            e.stopPropagation();
            onDelete(notification);
          }}
        >
          ×
        </button>
      ) : null}
    </div>
  );
}
