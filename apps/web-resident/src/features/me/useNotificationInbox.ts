"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  listNotifications,
  markNotificationRead,
  type AppNotification,
} from "@/lib/api";
import { isUnread, markReadInList } from "./notifications";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export interface NotificationInboxState {
  items: AppNotification[];
  loading: boolean;
  loadError: string | null;
  handleRead: (notification: AppNotification) => void;
  retry: () => void;
}

/** 알림 조회·읽음 상태 — 요약(나 페이지)·전체(/notifications)가 공유. limit 미지정 시 백엔드 기본. */
export function useNotificationInbox(limit?: number): NotificationInboxState {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await listNotifications(limit !== undefined ? { limit } : undefined));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [limit]);

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

  const retry = useCallback(() => {
    setLoading(true);
    void load();
  }, [load]);

  return { items, loading, loadError, handleRead, retry };
}
