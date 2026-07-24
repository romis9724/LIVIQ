"use client";

import { useState } from "react";
import { FileDropzone, type FileDropzoneState } from "@liviq/ui";
import { ApiError, uploadTwinGeometry, type TwinUploadReport } from "@/lib/api";

const ACCEPT = ".json";
const MAX_SIZE_MB = 5;
const MAX_SAMPLES = 5; // 미매칭 표본 표시 상한(서버가 이미 잘라 보냄 — 방어적 캡)

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "업로드에 실패했습니다.";
}

/**
 * 단지 트윈 geometry(units.json) 업로드 패널 — 동/호수 관리 하단 접이식 섹션(H9-1).
 * 업로드하면 명부 세대와 매칭·미매칭 리포트를 보여준다. 트윈 메뉴는 다음 새로고침에 노출된다.
 */
export function GeometryUploadPanel() {
  const [state, setState] = useState<FileDropzoneState>("idle");
  const [fileName, setFileName] = useState<string | undefined>();
  const [error, setError] = useState<string | undefined>();
  const [report, setReport] = useState<TwinUploadReport | null>(null);

  async function handleFile(file: File) {
    setFileName(file.name);
    setState("uploading");
    setError(undefined);
    setReport(null);
    try {
      const result = await uploadTwinGeometry(file);
      setReport(result);
      setState("selected");
    } catch (err) {
      setError(errorMessage(err));
      setState("error");
    }
  }

  return (
    <details className="surface-card hh-geometry">
      <summary className="hh-geometry__summary">
        <span className="hh-geometry__title">단지 트윈 geometry 업로드</span>
        <span className="hh-geometry__hint">units.json · 세대 3D 폴리곤</span>
      </summary>

      <div className="hh-geometry__body">
        <p className="hh-geometry__lede">
          세대별 3D 폴리곤(units.json)을 업로드하면 명부 세대와 매칭해 단지 트윈에 반영합니다.
          업로드는 기존 geometry를 전량 교체합니다.
        </p>

        <FileDropzone
          label="단지 트윈 geometry 업로드"
          accept={ACCEPT}
          maxSizeMb={MAX_SIZE_MB}
          onFile={(file) => void handleFile(file)}
          state={state}
          fileName={fileName}
          errorMessage={error}
        />

        {report ? <GeometryReport report={report} /> : null}
      </div>
    </details>
  );
}

function GeometryReport({ report }: { report: TwinUploadReport }) {
  return (
    <div className="hh-geometry__report" role="status" aria-live="polite">
      <dl className="hh-geometry__stats">
        <div>
          <dt>총 세대</dt>
          <dd>{report.totalUnits.toLocaleString("ko-KR")}</dd>
        </div>
        <div>
          <dt>매칭</dt>
          <dd>{report.matched.toLocaleString("ko-KR")}</dd>
        </div>
        <div data-warn={report.unmatched > 0 || undefined}>
          <dt>미매칭</dt>
          <dd>{report.unmatched.toLocaleString("ko-KR")}</dd>
        </div>
      </dl>

      <p className="hh-geometry__note">
        {report.replaced ? "기존 geometry를 교체했습니다. " : ""}
        단지 트윈 메뉴는 다음 새로고침에 표시됩니다.
      </p>

      {report.unmatchedSamples.length > 0 ? (
        <div className="hh-geometry__unmatched">
          <span className="hh-geometry__unmatched-label">매칭 실패 세대(표본)</span>
          <ul>
            {report.unmatchedSamples.slice(0, MAX_SAMPLES).map((sample) => (
              <li key={sample}>{sample}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
