"use client";

import { Button, Dialog, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createNotice,
  deleteNotice,
  getNotice,
  patchNotice,
  type Notice,
  type NoticePatchInput,
} from "@/lib/api";
import { AttachmentPanel } from "./AttachmentPanel";
import { NoticeForm } from "./NoticeForm";
import {
  hasErrors,
  isoToLocalInput,
  localInputToIso,
  validateNoticeForm,
  type NoticeFormValues,
  type SaveMode,
} from "./data";
import "./notices.css";

const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

const SUBMIT_LABEL: Record<SaveMode, string> = {
  draft: "임시저장",
  published: "발행하기",
  scheduled: "예약 저장",
};

const EMPTY_FORM: NoticeFormValues = {
  title: "",
  body: "",
  pinned: false,
  saveMode: "draft",
  scheduledAt: "",
};

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

function saveErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "발행된 공지는 임시저장·예약 상태로 되돌릴 수 없습니다.";
    if (err.status === 422) return "입력값을 확인하세요. 예약 발행은 미래 시각이어야 합니다.";
  }
  return errorMessage(err);
}

interface NoticeEditorProps {
  mode: "create" | "edit";
  noticeId?: string;
}

export function NoticeEditor({ mode, noticeId }: NoticeEditorProps) {
  const router = useRouter();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [loading, setLoading] = useState(mode === "edit");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [values, setValues] = useState<NoticeFormValues>(EMPTY_FORM);
  const [attempted, setAttempted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async () => {
    if (mode !== "edit" || !noticeId) return;
    try {
      const loaded = await getNotice(noticeId);
      setNotice(loaded);
      setValues({
        title: loaded.title,
        body: loaded.body,
        pinned: loaded.pinned,
        // 발행 공지는 역행 불가 — 편집 시 선택지를 draft 로 초기화(발행됨 표기는 폼이 담당).
        saveMode: loaded.status === "published" ? "draft" : loaded.status,
        scheduledAt: isoToLocalInput(loaded.scheduledAt),
      });
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [mode, noticeId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const publishedLock = mode === "edit" && notice?.status === "published";
  const errors = validateNoticeForm(values);
  const showErrors = attempted;

  const handleChange = useCallback((patch: Partial<NoticeFormValues>) => {
    setValues((prev) => ({ ...prev, ...patch }));
  }, []);

  async function handleSubmit() {
    setAttempted(true);
    if (hasErrors(errors)) return;
    const title = values.title.trim();
    const body = values.body.trim();
    const scheduledAt = values.saveMode === "scheduled" ? localInputToIso(values.scheduledAt) : null;

    setSaving(true);
    try {
      if (mode === "create") {
        const created = await createNotice({
          title,
          body,
          pinned: values.pinned,
          status: values.saveMode,
          scheduledAt,
        });
        showToast("공지를 저장했습니다. 첨부 파일을 추가할 수 있습니다.");
        router.push(`/notices/${created.id}`);
        return;
      }
      if (!noticeId) return;
      const patch: NoticePatchInput = { title, body, pinned: values.pinned };
      if (!publishedLock) {
        patch.status = values.saveMode;
        patch.scheduledAt = scheduledAt;
      }
      const updated = await patchNotice(noticeId, patch);
      setNotice(updated);
      showToast("변경 사항을 저장했습니다.");
    } catch (err) {
      showToast(saveErrorMessage(err), "danger");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!noticeId) return;
    setSaving(true);
    try {
      await deleteNotice(noticeId);
      setConfirmDelete(false);
      router.push("/notices");
    } catch (err) {
      setConfirmDelete(false);
      showToast(errorMessage(err), "danger");
    } finally {
      setSaving(false);
    }
  }

  const title = mode === "create" ? "새 공지 작성" : "공지 수정";

  return (
    <>
      <header className="admin-page__header notice-head">
        <div className="notice-head__text">
          <Link href="/notices" className="notice-back">
            ← 공지 목록
          </Link>
          <h1 id="main" className="admin-page__title">
            {title}
          </h1>
        </div>
      </header>

      <main className="admin-page__main notice-editor">
        {loading ? (
          <div className="surface-card notice-loading">
            <Skeleton height="1.5rem" />
            <Skeleton height="8rem" />
          </div>
        ) : loadError ? (
          <EmptyState
            icon="⚠"
            title="공지를 불러오지 못했습니다"
            description={loadError}
            action={
              <Button
                onClick={() => {
                  setLoading(true);
                  void load();
                }}
              >
                다시 시도
              </Button>
            }
          />
        ) : (
          <>
            <NoticeForm
              values={values}
              errors={showErrors ? errors : {}}
              disabled={saving}
              submitting={saving}
              submitLabel={publishedLock ? "변경 저장" : SUBMIT_LABEL[values.saveMode]}
              publishedLock={Boolean(publishedLock)}
              onChange={handleChange}
              onSubmit={() => void handleSubmit()}
            />

            {mode === "create" ? (
              <p className="notice-muted notice-editor__hint">
                첨부 파일은 저장 후 상세 화면에서 추가할 수 있습니다.
              </p>
            ) : notice ? (
              <>
                <AttachmentPanel
                  noticeId={notice.id}
                  status={notice.status}
                  attachments={notice.attachments}
                  onChanged={load}
                  showToast={showToast}
                />

                <section className="surface-card notice-danger" aria-label="공지 삭제">
                  <div className="notice-danger__text">
                    <span className="notice-danger__title">공지 삭제</span>
                    <span className="notice-muted">삭제하면 목록·입주민 화면에서 사라집니다.</span>
                  </div>
                  <Button variant="danger" disabled={saving} onClick={() => setConfirmDelete(true)}>
                    삭제
                  </Button>
                </section>
              </>
            ) : null}
          </>
        )}
      </main>

      <Dialog
        open={confirmDelete}
        title="공지를 삭제할까요?"
        description="삭제한 공지는 목록과 입주민 화면에서 사라집니다."
        confirmLabel="삭제"
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void handleDelete()}
      />

      {toast ? (
        <div className="notice-toast">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}
