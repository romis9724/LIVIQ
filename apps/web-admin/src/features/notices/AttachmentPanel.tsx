"use client";

import { Button, Dialog } from "@liviq/ui";
import { useRef, useState } from "react";
import type { ChangeEvent } from "react";

import {
  ApiError,
  deleteNoticeAttachment,
  noticeAttachmentDownloadUrl,
  uploadNoticeAttachment,
  type NoticeAttachment,
  type NoticeStatus,
} from "@/lib/api";
import { ATTACHMENT_ACCEPT, MAX_ATTACHMENTS, formatFileSize, validateAttachment } from "./data";

/** 첨부 API 오류를 사용자 친화 메시지로. 413=용량·422=개수/빈 파일. */
function attachmentError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 413) return "파일이 너무 큽니다. 파일당 최대 20MB까지 첨부할 수 있습니다.";
    if (err.status === 422) return "첨부할 수 없는 파일입니다. 형식·개수·용량을 확인하세요.";
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface AttachmentPanelProps {
  noticeId: string;
  status: NoticeStatus;
  attachments: readonly NoticeAttachment[];
  onChanged: () => Promise<void> | void;
  showToast: (message: string, tone?: "success" | "danger" | "neutral") => void;
}

export function AttachmentPanel({
  noticeId,
  status,
  attachments,
  onChanged,
  showToast,
}: AttachmentPanelProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<NoticeAttachment | null>(null);

  const atLimit = attachments.length >= MAX_ATTACHMENTS;
  const canDownload = status === "published";

  async function handleFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = ""; // 같은 파일 재선택 허용
    if (!file) return;

    const invalid = validateAttachment(file, attachments.length);
    if (invalid) {
      setValidationError(invalid);
      return;
    }
    setValidationError(null);
    setBusy(true);
    try {
      await uploadNoticeAttachment(noticeId, file);
      await onChanged();
      showToast("첨부를 추가했습니다.");
    } catch (err) {
      showToast(attachmentError(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    if (!pendingDelete) return;
    setBusy(true);
    try {
      await deleteNoticeAttachment(noticeId, pendingDelete.id);
      setPendingDelete(null);
      await onChanged();
      showToast("첨부를 삭제했습니다.");
    } catch (err) {
      setPendingDelete(null);
      showToast(attachmentError(err), "danger");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="surface-card notice-attach" aria-label="첨부 파일">
      <div className="notice-attach__head">
        <h2 className="notice-attach__title">첨부 파일</h2>
        <span className="notice-muted">
          {attachments.length}/{MAX_ATTACHMENTS}
        </span>
      </div>

      {attachments.length === 0 ? (
        <p className="notice-muted notice-attach__empty">첨부된 파일이 없습니다.</p>
      ) : (
        <ul className="notice-attach__list">
          {attachments.map((att) => (
            <li key={att.id} className="notice-attach__item">
              <span className="notice-attach__icon" aria-hidden="true">
                📎
              </span>
              <span className="notice-attach__meta">
                {canDownload ? (
                  <a
                    className="notice-attach__name"
                    href={noticeAttachmentDownloadUrl(noticeId, att.id)}
                    download={att.filename}
                  >
                    {att.filename}
                  </a>
                ) : (
                  <span className="notice-attach__name">{att.filename}</span>
                )}
                <span className="notice-attach__size">{formatFileSize(att.sizeBytes)}</span>
              </span>
              <button
                type="button"
                className="btn btn--secondary btn--sm"
                disabled={busy}
                onClick={() => setPendingDelete(att)}
              >
                삭제
              </button>
            </li>
          ))}
        </ul>
      )}

      {!canDownload ? (
        <p className="notice-muted notice-attach__note">
          발행 후에 첨부 파일을 다운로드할 수 있습니다.
        </p>
      ) : null}

      <div className="notice-attach__upload">
        <input
          ref={inputRef}
          type="file"
          accept={ATTACHMENT_ACCEPT}
          className="notice-attach__input"
          onChange={handleFile}
        />
        <Button
          type="button"
          variant="secondary"
          disabled={busy || atLimit}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "처리 중…" : "파일 추가"}
        </Button>
        <span className="notice-muted notice-attach__hint">
          {ATTACHMENT_ACCEPT} · 파일당 최대 20MB
        </span>
      </div>
      {atLimit ? (
        <p className="form-field__error">첨부는 공지당 최대 {MAX_ATTACHMENTS}개까지 가능합니다.</p>
      ) : null}
      {validationError ? (
        <p className="form-field__error" role="alert">
          {validationError}
        </p>
      ) : null}

      <Dialog
        open={pendingDelete !== null}
        title="첨부를 삭제할까요?"
        description={pendingDelete ? `‘${pendingDelete.filename}’을(를) 삭제합니다.` : undefined}
        confirmLabel="삭제"
        danger
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmDelete()}
      />
    </section>
  );
}
