"use client";

import { Button, FileDropzone } from "@liviq/ui";
import type { FileDropzoneState } from "@liviq/ui";
import { useState } from "react";

import type { SourceType, UploadInput, Visibility } from "@/lib/api";
import { SOURCE_TYPES, VISIBILITIES, VISIBILITY_META } from "./data";

// api ALLOWED_SUFFIXES 와 일치(.txt/.md/.markdown/.pdf). 안내는 대표 확장자만.
const ACCEPT = ".txt,.md,.markdown,.pdf";
const MAX_SIZE_MB = 20;

interface UploadPanelProps {
  uploading: boolean;
  onUpload: (input: UploadInput) => Promise<void>;
}

export function UploadPanel({ uploading, onUpload }: UploadPanelProps) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [sourceType, setSourceType] = useState<SourceType>("규약");
  const [visibility, setVisibility] = useState<Visibility>("ALL");

  const zoneState: FileDropzoneState = uploading ? "uploading" : file ? "selected" : "idle";
  const canSubmit = Boolean(file) && title.trim().length > 0 && !uploading;

  function handleFile(picked: File) {
    setFile(picked);
    // 제목 미입력 시 파일명(확장자 제거)으로 초기 채움 — 수정 가능.
    if (!title.trim()) setTitle(picked.name.replace(/\.[^.]+$/, ""));
  }

  async function handleSubmit() {
    if (!file || !canSubmit) return;
    await onUpload({ file, title: title.trim(), sourceType, visibility });
    setFile(null);
    setTitle("");
  }

  return (
    <section className="doc-upload-panel" aria-label="문서 업로드">
      <FileDropzone
        label="관리 문서 업로드"
        accept={ACCEPT}
        maxSizeMb={MAX_SIZE_MB}
        state={zoneState}
        fileName={file?.name}
        onFile={handleFile}
      />
      <div className="doc-upload-form">
        <label className="doc-field">
          <span className="doc-field__label">제목</span>
          <input
            className="doc-input"
            type="text"
            value={title}
            maxLength={200}
            placeholder="예: 공동주택 관리규약"
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label className="doc-field">
          <span className="doc-field__label">문서 유형</span>
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
        <Button disabled={!canSubmit} onClick={handleSubmit}>
          {uploading ? "업로드 중…" : "업로드"}
        </Button>
      </div>
    </section>
  );
}
