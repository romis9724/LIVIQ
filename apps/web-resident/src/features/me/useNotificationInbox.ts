"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  deleteNotification,
  listNotifications,
  markNotificationRead,
  type AppNotification,
} from "@/lib/api";
import { isUnread, markReadInList, removeFromList } from "./notifications";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export interface NotificationInboxState {
  items: AppNotification[];
  loading: boolean;
  loadError: string | null;
  deleteError: string | null;
  handleRead: (notification: AppNotification) => void;
  handleDelete: (notification: AppNotification) => Promise<void>;
  dismissDeleteError: () => void;
  retry: () => void;
}

/** 알림 조회·읽음·삭제 상태 — 요약(나 페이지)·전체(/notifications)가 공유. limit 미지정 시 백엔드 기본. */
export function useNotificationInbox(limit?: number): NotificationInboxState {
  const [items, setItems] = useState<AppNotification[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

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

  // 낙관적 삭제 — 즉시 목록에서 제거, 실패 시 스냅샷 롤백 + 토스트. 삭제는 전체 목록에서만 호출.
  const handleDelete = useCallback(async (notification: AppNotification) => {
    setDeleteError(null);
    let snapshot: AppNotification[] = [];
    setItems((prev) => {
      snapshot = prev;
      return removeFromList(prev, notification.id);
    });
    try {
      await deleteNotification(notification.id);
    } catch {
      setItems(snapshot); // 롤백 — 서버 삭제 실패 시 원상 복구
      setDeleteError("알림을 삭제하지 못했습니다. 다시 시도해 주세요.");
    }
  }, []);

  const dismissDeleteError = useCallback(() => setDeleteError(null), []);

  const retry = useCallback(() => {
    setLoading(true);
    void load();
  }, [load]);

  return {
    items,
    loading,
    loadError,
    deleteError,
    handleRead,
    handleDelete,
    dismissDeleteError,
    retry,
  };
}
