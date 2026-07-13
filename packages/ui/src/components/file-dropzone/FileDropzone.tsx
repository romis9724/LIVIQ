"use client";

import { useRef, useState } from "react";
import type { ChangeEvent, DragEvent, KeyboardEvent } from "react";
import { cx } from "../../lib/cx";

export type FileDropzoneState = "idle" | "selected" | "uploading" | "error";

export interface FileDropzoneProps {
  /** 접근성·시각 라벨 (예: "명부 엑셀 업로드"). */
  label: string;
  /** 허용 확장자 안내 텍스트. 네이티브 input accept 로도 전달된다. 예: ".xlsx, .xls" */
  accept: string;
  /** 최대 용량 안내 표기(MB). 검증은 소비 측 책임. */
  maxSizeMb: number;
  /** 파일 선택·드롭 시 호출. */
  onFile: (file: File) => void;
  state?: FileDropzoneState;
  fileName?: string;
  /** 소비 측에서 포맷한 용량 문자열. 예: "2.4 MB" */
  fileSize?: string;
  /** 0~100. state="uploading"일 때 진행률 바. */
  progress?: number;
  /** state="error"일 때 danger 메시지. */
  errorMessage?: string;
  className?: string;
}

/**
 * 엑셀 업로드 등에 쓰는 드래그&드롭 + 클릭 파일 선택 영역.
 * 프레젠테이션 순수 — 파일 검증·업로드는 소비 측 책임이며 state prop 으로 반영한다.
 * 색만으로 상태를 전달하지 않는다(아이콘/텍스트 병기). 키보드 조작(Enter/Space) 지원.
 */
export function FileDropzone({
  label,
  accept,
  maxSizeMb,
  onFile,
  state = "idle",
  fileName,
  fileSize,
  progress,
  errorMessage,
  className,
}: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const isInteractive = state !== "uploading";

  function openPicker() {
    inputRef.current?.click();
  }

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openPicker();
    }
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) onFile(file);
    // 같은 파일 재선택을 허용하기 위해 값 초기화
    event.target.value = "";
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) onFile(file);
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(true);
  }

  return (
    <div className={cx("file-dropzone", className)}>
      <div
        role="button"
        tabIndex={isInteractive ? 0 : -1}
        aria-label={label}
        aria-disabled={isInteractive ? undefined : true}
        className={cx(
          "file-dropzone__zone",
          `file-dropzone__zone--${state}`,
          isDragging && "file-dropzone__zone--dragging",
        )}
        onClick={isInteractive ? openPicker : undefined}
        onKeyDown={isInteractive ? handleKeyDown : undefined}
        onDragOver={isInteractive ? handleDragOver : undefined}
        onDragLeave={isInteractive ? () => setIsDragging(false) : undefined}
        onDrop={isInteractive ? handleDrop : undefined}
      >
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          className="file-dropzone__input"
          tabIndex={-1}
          aria-hidden="true"
          onChange={handleChange}
        />
        <FileDropzoneBody
          state={state}
          accept={accept}
          maxSizeMb={maxSizeMb}
          fileName={fileName}
          fileSize={fileSize}
          progress={progress}
          errorMessage={errorMessage}
        />
      </div>
    </div>
  );
}

type BodyProps = Pick<
  FileDropzoneProps,
  "state" | "accept" | "maxSizeMb" | "fileName" | "fileSize" | "progress" | "errorMessage"
>;

function FileDropzoneBody({
  state,
  accept,
  maxSizeMb,
  fileName,
  fileSize,
  progress,
  errorMessage,
}: BodyProps) {
  switch (state) {
    case "selected":
      return (
        <>
          <span className="file-dropzone__icon" aria-hidden="true">
            📄
          </span>
          <span className="file-dropzone__title">{fileName ?? "선택한 파일"}</span>
          <span className="file-dropzone__hint">
            {fileSize ? `${fileSize} · ` : ""}다른 파일로 바꾸려면 클릭
          </span>
        </>
      );
    case "uploading": {
      const value = progress ?? 0;
      return (
        <>
          <span className="file-dropzone__title">{fileName ?? "업로드 중"}</span>
          <div
            className="file-dropzone__progress"
            role="progressbar"
            aria-label="업로드 진행률"
            aria-valuenow={value}
            aria-valuemin={0}
            aria-valuemax={100}
          >
            <span
              className="file-dropzone__progress-bar"
              style={{ width: `${value}%` }}
            />
          </div>
          <span className="file-dropzone__hint">업로드 중… {value}%</span>
        </>
      );
    }
    case "error":
      return (
        <>
          <span className="file-dropzone__icon" aria-hidden="true">
            ⚠
          </span>
          <span className="file-dropzone__title">{fileName ?? "업로드 실패"}</span>
          <span className="file-dropzone__error" role="alert">
            {errorMessage ?? "파일을 다시 확인해 주세요."}
          </span>
          <span className="file-dropzone__hint">다시 선택하려면 클릭</span>
        </>
      );
    default:
      return (
        <>
          <span className="file-dropzone__icon" aria-hidden="true">
            ⬆
          </span>
          <span className="file-dropzone__title">파일을 끌어다 놓거나 클릭해 선택</span>
          <span className="file-dropzone__hint">
            {accept} · 최대 {maxSizeMb}MB
          </span>
        </>
      );
  }
}
