"use client";

import { Button, Dialog, EmptyState, FileDropzone, Skeleton, Toast } from "@liviq/ui";
import type { FileDropzoneState, ToastTone } from "@liviq/ui";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  deleteDocument,
  documentDownloadUrl,
  getDocument,
  patchDocument,
  reindexDocument,
  uploadDocumentVersion,
  type DocumentDetail as DocumentDetailData,
  type SourceType,
  type Visibility,
} from "@/lib/api";
import {
  FILE_ACCEPT,
  INDEX_META,
  MAX_FILE_MB,
  SOURCE_TYPES,
  VISIBILITIES,
  VISIBILITY_META,
  documentErrorMessage,
  formatFileSize,
  shortDate,
  validateAttachment,
} from "./data";
import "./documents.css";

const POLL_INTERVAL_MS = 5000;
const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

export function DocumentDetail() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const router = useRouter();

  const [detail, setDetail] = useState<DocumentDetailData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 메타 편집 폼 — 상세 최초 로드 시 1회 하이드레이트(폴링이 편집 중 값을 덮지 않도록 분리).
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState<SourceType>("규약");
  const [visibility, setVisibility] = useState<Visibility>("ADMIN");
  const [body, setBody] = useState("");
  const [saving, setSaving] = useState(false);

  const [newFile, setNewFile] = useState<File | null>(null);
  const [newFileError, setNewFileError] = useState<string | null>(null);
  const [replacing, setReplacing] = useState(false);

  const [reindexing, setReindexing] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const loadDetail = useCallback(
    async (opts?: { hydrate?: boolean }) => {
      try {
        const data = await getDocument(id);
        setDetail(data);
        setLoadError(null);
        if (opts?.hydrate) {
          setTitle(data.title);
          setSourceType(data.sourceType);
          setVisibility(data.visibility);
          setBody(data.body ?? "");
        }
      } catch (err) {
        setLoadError(documentErrorMessage(err));
      } finally {
        setLoading(false);
      }
    },
    [id],
  );

  useEffect(() => {
    void loadDetail({ hydrate: true });
  }, [loadDetail]);

  // 색인 진행 중(pending·indexing)이면 5초 폴링으로 상태 갱신.
  const active = detail?.indexStatus === "pending" || detail?.indexStatus === "indexing";
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => void loadDetail(), POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [active, loadDetail]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const isDirty =
    detail !== null &&
    (title.trim() !== detail.title ||
      sourceType !== detail.sourceType ||
      visibility !== detail.visibility ||
      body !== (detail.body ?? ""));
  const canSave = detail !== null && title.trim().length > 0 && isDirty && !saving;

  async function handleSave() {
    if (!detail || !canSave) return;
    setSaving(true);
    try {
      const updated = await patchDocument(detail.id, {
        title: title.trim(),
        body,
        sourceType,
        visibility,
      });
      setDetail((prev) => (prev ? { ...prev, ...updated } : prev));
      showToast("변경 사항을 저장했습니다.");
    } catch (err) {
      showToast(documentErrorMessage(err), "danger");
    } finally {
      setSaving(false);
    }
  }

  function handlePickNewFile(picked: File) {
    setNewFileError(validateAttachment(picked));
    setNewFile(picked);
  }

  async function handleUploadNewVersion() {
    if (!detail || !newFile || newFileError) return;
    setReplacing(true);
    try {
      await uploadDocumentVersion(detail.id, newFile);
      setNewFile(null);
      setNewFileError(null);
      await loadDetail();
      showToast("새 버전을 업로드했습니다. 재색인을 시작합니다.");
    } catch (err) {
      showToast(documentErrorMessage(err), "danger");
    } finally {
      setReplacing(false);
    }
  }

  async function handleReindex() {
    if (!detail) return;
    setReindexing(true);
    try {
      await reindexDocument(detail.id);
      await loadDetail();
      showToast("재색인을 요청했습니다.");
    } catch (err) {
      showToast(documentErrorMessage(err), "danger");
    } finally {
      setReindexing(false);
    }
  }

  async function handleDelete() {
    if (!detail) return;
    setDeleting(true);
    try {
      await deleteDocument(detail.id);
      router.push("/documents");
    } catch (err) {
      setDialogOpen(false);
      setDeleting(false);
      showToast(documentErrorMessage(err), "danger");
    }
  }

  if (loading) {
    return (
      <main className="admin-page__main doc-detail">
        <Skeleton height="2rem" width="60%" />
        <Skeleton height="12rem" />
      </main>
    );
  }

  if (loadError || !detail) {
    return (
      <main className="admin-page__main">
        <EmptyState
          icon="⚠"
          title="문서를 불러오지 못했습니다"
          description={loadError ?? "문서를 찾을 수 없습니다."}
          action={
            <Link href="/documents" className="btn btn--secondary">
              목록으로
            </Link>
          }
        />
      </main>
    );
  }

  const ix = INDEX_META[detail.indexStatus];
  const current = detail.versions.find((v) => v.version === detail.version) ?? detail.versions[0];
  const newZoneState: FileDropzoneState = replacing
    ? "uploading"
    : newFileError
      ? "error"
      : newFile
        ? "selected"
        : "idle";

  return (
    <>
      <header className="admin-page__header doc-detail__head">
        <div>
          <Link href="/documents" className="doc-back">
            ← 문서 목록
          </Link>
          <h1 id="main" className="admin-page__title">
            {detail.title}
          </h1>
          <p className="doc-detail__submeta">
            {detail.sourceType} · v{detail.version} · 수정 {shortDate(detail.updatedAt)}
          </p>
        </div>
        <span className={`doc-idx doc-idx--${detail.indexStatus}`}>
          <span aria-hidden="true" className={ix.spin ? "doc-idx__spin" : undefined}>
            {ix.icon}
          </span>
          {ix.label}
        </span>
      </header>

      <main className="admin-page__main doc-detail">
        <section className="surface-card doc-form" aria-labelledby="doc-meta-h">
          <h2 id="doc-meta-h" className="doc-section__title">
            게시글 정보
          </h2>
          <label className="doc-field doc-field--block">
            <span className="doc-field__label">제목</span>
            <input
              className="doc-input"
              type="text"
              value={title}
              maxLength={200}
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>
          <div className="doc-form__row">
            <label className="doc-field">
              <span className="doc-field__label">카테고리</span>
              <select
                className="doc-select"
                value={sourceType}
                onChange={(event) => setSourceType(event.target.value as SourceType)}
              >
                {SOURCE_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
            <label className="doc-field">
              <span className="doc-field__label">공개 범위</span>
              <select
                className="doc-select"
                value={visibility}
                onChange={(event) => setVisibility(event.target.value as Visibility)}
              >
                {VISIBILITIES.map((v) => (
                  <option key={v} value={v}>
                    {VISIBILITY_META[v].label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label className="doc-field doc-field--block">
            <span className="doc-field__label">본문 (선택 · 설명용 · 색인 안 함)</span>
            <textarea
              className="doc-textarea"
              rows={5}
              value={body}
              maxLength={4000}
              onChange={(event) => setBody(event.target.value)}
            />
          </label>
          <div className="doc-form__actions">
            <Button type="button" variant="primary" disabled={!canSave} onClick={() => void handleSave()}>
              {saving ? "저장 중…" : "변경 저장"}
            </Button>
          </div>
        </section>

        <section className="surface-card doc-form" aria-labelledby="doc-file-h">
          <h2 id="doc-file-h" className="doc-section__title">
            첨부 파일
          </h2>
          {current ? (
            <div className="doc-currentfile">
              <span className="doc-name__icon" aria-hidden="true">
                📄
              </span>
              <div className="doc-currentfile__body">
                <div className="doc-currentfile__name">{current.filename}</div>
                <div className="doc-currentfile__meta">
                  v{current.version} · {formatFileSize(current.sizeBytes)} ·{" "}
                  <span className={`doc-idx doc-idx--${detail.indexStatus}`}>
                    <span aria-hidden="true" className={ix.spin ? "doc-idx__spin" : undefined}>
                      {ix.icon}
                    </span>
                    {ix.label}
                  </span>
                </div>
              </div>
              <div className="doc-currentfile__actions">
                <a
                  className="btn btn--secondary btn--sm"
                  href={documentDownloadUrl(detail.id, current.version)}
                  download
                >
                  다운로드
                </a>
                {detail.indexStatus === "failed" ? (
                  <Button
                    type="button"
                    variant="danger"
                    size="sm"
                    disabled={reindexing}
                    onClick={() => void handleReindex()}
                  >
                    {reindexing ? "재색인 중…" : "재색인"}
                  </Button>
                ) : null}
              </div>
            </div>
          ) : null}

          <div className="doc-newversion">
            <span className="doc-field__label">새 버전 업로드</span>
            <p className="doc-hint">
              새 파일을 올리면 v{detail.version + 1}로 저장되고 자동으로 재색인됩니다. 이전 파일은
              이력에 보존됩니다.
            </p>
            <FileDropzone
              label="새 버전 파일"
              accept={FILE_ACCEPT}
              maxSizeMb={MAX_FILE_MB}
              state={newZoneState}
              fileName={newFile?.name}
              fileSize={newFile ? formatFileSize(newFile.size) : undefined}
              errorMessage={newFileError ?? undefined}
              onFile={handlePickNewFile}
            />
            {newFile && !newFileError ? (
              <div className="doc-form__actions">
                <Button
                  type="button"
                  variant="primary"
                  disabled={replacing}
                  onClick={() => void handleUploadNewVersion()}
                >
                  {replacing ? "업로드 중…" : "이 파일로 새 버전 올리기"}
                </Button>
              </div>
            ) : null}
          </div>
        </section>

        <section className="surface-card doc-form" aria-labelledby="doc-versions-h">
          <h2 id="doc-versions-h" className="doc-section__title">
            버전 이력
          </h2>
          <ol className="doc-versions">
            {detail.versions.map((v) => (
              <li key={v.version} className="doc-versions__item">
                <span className="doc-versions__badge">
                  v{v.version}
                  {v.version === detail.version ? (
                    <span className="doc-versions__current">현재</span>
                  ) : null}
                </span>
                <div className="doc-versions__body">
                  <div className="doc-versions__name">{v.filename}</div>
                  <div className="doc-versions__meta">
                    {formatFileSize(v.sizeBytes)} · {shortDate(v.createdAt)}
                  </div>
                </div>
                <a
                  className="btn btn--ghost btn--sm"
                  href={documentDownloadUrl(detail.id, v.version)}
                  download
                >
                  다운로드
                </a>
              </li>
            ))}
          </ol>
        </section>

        <section className="doc-dangerzone">
          <div>
            <div className="doc-dangerzone__title">문서 삭제</div>
            <p className="doc-hint">
              삭제하면 AI 검색에서 즉시 제외됩니다. 파일 이력은 감사 목적으로 보존됩니다.
            </p>
          </div>
          <Button
            type="button"
            variant="danger"
            disabled={deleting}
            onClick={() => setDialogOpen(true)}
          >
            문서 삭제
          </Button>
        </section>
      </main>

      <Dialog
        open={dialogOpen}
        danger
        title="이 문서를 삭제할까요?"
        description="삭제 즉시 AI 검색에서 제외됩니다. 되돌릴 수 없습니다."
        confirmLabel={deleting ? "삭제 중…" : "삭제"}
        onCancel={() => setDialogOpen(false)}
        onConfirm={() => void handleDelete()}
      />

      {toast ? (
        <div className="doc-toast-slot">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}
