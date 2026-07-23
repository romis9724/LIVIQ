"use client";

import Link from "next/link";

import { NotificationListBody } from "./NotificationList";
import { hasMoreNotifications, summaryNotifications, unreadCount } from "./notifications";
import { useNotificationInbox } from "./useNotificationInbox";

/** 나 페이지 알림 요약 — 최근 몇 개만. 전체는 /notifications 전체 목록에서. */
export function NotificationInbox() {
  const { items, loading, loadError, handleRead, retry } = useNotificationInbox();
  const unread = unreadCount(items);
  const visible = summaryNotifications(items);
  const showMore = !loading && !loadError && hasMoreNotifications(items);

  return (
    <section className="me-section">
      <div className="me-section__head">
        <h2 className="me-section__title">
          알림{unread > 0 ? <span className="me-notif__count">{unread}</span> : null}
        </h2>
        {showMore ? (
          <Link href="/notifications" className="me-notif__more">
            더보기 →
          </Link>
        ) : null}
      </div>
      <NotificationListBody
        items={visible}
        loading={loading}
        loadError={loadError}
        onRead={handleRead}
        onRetry={retry}
      />
    </section>
  );
}
