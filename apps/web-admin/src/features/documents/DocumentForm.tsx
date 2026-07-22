"use client";

import { Button, FileDropzone } from "@liviq/ui";
import type { FileDropzoneState } from "@liviq/ui";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createDocument, listCodeGroups, type Visibility } from "@/lib/api";
import { DOC_CATEGORY_GROUP, codeOptions, type CodeOption } from "@/lib/codes";
import {
  FILE_ACCEPT,
  MAX_FILE_MB,
  VISIBILITIES,
  VISIBILITY_META,
  documentErrorMessage,
  formatFileSize,
  validateAttachment,
} from "./data";
import "./documents.css";

const TITLE_MAX = 200;

export function DocumentForm() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [categoryCodeId, setCategoryCodeId] = useState("");
  const [visibility, setVisibility] = useState<Visibility>("ADMIN");
  const [body, setBody] = useState("");
  const [categoryOptions, setCategoryOptions] = useState<CodeOption[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // 분류(DOC_CATEGORY) 선택지 로드 — 첫 코드를 기본 선택(분류 필수).
  useEffect(() => {
    void (async () => {
      try {
        const opts = codeOptions(await listCodeGroups(), DOC_CATEGORY_GROUP);
        setCategoryOptions(opts);
        setCategoryCodeId((prev) => prev || opts[0]?.id || "");
      } catch {
        // 무시 — 선택지 없으면 제출 불가(canSubmit)로 사용자에게 드러남.
      }
    })();
  }, []);

  const canSubmit =
    Boolean(file) && !fileError && title.trim().length > 0 && categoryCodeId !== "" && !submitting;

  function handleFile(picked: File) {
    const error = validateAttachment(picked);
    setFileError(error);
    setFile(picked);
    // 제목 미입력 시 파일명(확장자 제거)으로 초기 채움 — 수정 가능.
    if (!title.trim() && !error) setTitle(picked.name.replace(/\.[^.]+$/, ""));
  }

  async function handleSubmit() {
    if (!file || !canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      await createDocument({ file, title: title.trim(), categoryCodeId, visibility, body });
      router.push("/documents");
    } catch (err) {
      setSubmitError(documentErrorMessage(err));
      setSubmitting(false);
    }
  }

  const zoneState: FileDropzoneState = submitting
    ? "uploading"
    : fileError
      ? "error"
      : file
        ? "selected"
        : "idle";

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          새 문서
        </h1>
        <p className="admin-page__lede">
          첨부 문서가 색인되면 AI가 출처로 인용합니다. 본문(설명)은 색인되지 않으니 참고 메모로만
          쓰세요.
        </p>
      </header>

      <main className="admin-page__main">
        <form
          className="surface-card doc-form"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSubmit();
          }}
        >
          <FileDropzone
            label="문서 첨부"
            accept={FILE_ACCEPT}
            maxSizeMb={MAX_FILE_MB}
            state={zoneState}
            fileName={file?.name}
            fileSize={file ? formatFileSize(file.size) : undefined}
            errorMessage={fileError ?? undefined}
            onFile={handleFile}
          />

          <label className="doc-field doc-field--block">
            <span className="doc-field__label">제목</span>
            <input
              className="doc-input"
              type="text"
              value={title}
              maxLength={TITLE_MAX}
              placeholder="예: 공동주택 관리규약"
              onChange={(event) => setTitle(event.target.value)}
            />
          </label>

          <div className="doc-form__row">
            <label className="doc-field">
              <span className="doc-field__label">분류</span>
              <select
                className="doc-select"
                value={categoryCodeId}
                onChange={(event) => setCategoryCodeId(event.target.value)}
              >
                {categoryOptions.length === 0 ? <option value="">분류 없음</option> : null}
                {categoryOptions.map((opt) => (
                  <option key={opt.id} value={opt.id}>
                    {opt.label}
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
            <span className="doc-field__label">본문 (선택 · 설명용)</span>
            <textarea
              className="doc-textarea"
              rows={5}
              value={body}
              maxLength={4000}
              placeholder="문서에 대한 설명이나 참고 사항을 남기세요. (색인 대상 아님)"
              onChange={(event) => setBody(event.target.value)}
            />
          </label>

          {submitError ? (
            <p className="doc-error" role="alert">
              {submitError}
            </p>
          ) : null}

          <div className="doc-form__actions">
            <Link href="/documents" className="btn btn--secondary">
              취소
            </Link>
            <Button type="submit" variant="primary" disabled={!canSubmit}>
              {submitting ? "등록 중…" : "등록"}
            </Button>
          </div>
        </form>
      </main>
    </>
  );
}
