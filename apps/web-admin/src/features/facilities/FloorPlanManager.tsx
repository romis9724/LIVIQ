"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, EmptyState, FileDropzone, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  listFloorPlans,
  uploadFloorPlan,
  type AdminFloorPlanItem,
} from "@/lib/api";
import { shortDate } from "./data";
import { FloorPlanEditor } from "./FloorPlanEditor";
import "./facilities.css";

const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

/** 평면도 목록 + 업로드 + (선택 시) 편집기 전환. FacilitiesScreen 세 번째 탭. */
export function FloorPlanManager() {
  const [plans, setPlans] = useState<AdminFloorPlanItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async (keepSelection?: string) => {
    setLoading(true);
    try {
      const items = await listFloorPlans();
      setPlans(items);
      setLoadError(null);
      if (keepSelection) setSelectedId(keepSelection);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  async function handleUpload(input: {
    unitTypeName: string;
    image: File;
    imageWidth: number;
    imageHeight: number;
  }) {
    setUploadBusy(true);
    try {
      const created = await uploadFloorPlan(input);
      setShowUpload(false);
      await load(created.id);
      showToast("도면을 업로드했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setUploadBusy(false);
    }
  }

  if (selectedId) {
    // 저장 성공/실패 토스트는 FloorPlanEditor가 직접 띄운다(이 화면의 토스트는 아래에서만 렌더됨).
    return (
      <FloorPlanEditor
        planId={selectedId}
        onBack={() => setSelectedId(null)}
        onSaved={() => void load(selectedId)}
      />
    );
  }

  return (
    <>
      <header className="admin-page__header fac-head">
        <div className="fac-head__text">
          <h1 id="main" className="admin-page__title">
            평면도
          </h1>
          <p className="admin-page__lede">
            세대 타입별 도면과 시설 마커를 편집합니다. 좌표는 원본 이미지 픽셀 기준입니다.
          </p>
        </div>
        <Button variant="primary" onClick={() => setShowUpload(true)}>
          도면 업로드
        </Button>
      </header>

      <main className="fp-list-main">
        {loading ? (
          <>
            <Skeleton height="6rem" />
            <Skeleton height="6rem" />
          </>
        ) : loadError ? (
          <EmptyState
            icon="⚠"
            title="평면도 목록을 불러오지 못했습니다"
            description={loadError}
            action={<Button onClick={() => void load()}>다시 시도</Button>}
          />
        ) : plans.length === 0 ? (
          <EmptyState
            icon="🗺"
            title="등록된 평면도가 없습니다"
            description="‘도면 업로드’로 첫 도면을 추가하세요."
          />
        ) : (
          <div className="fp-grid">
            {plans.map((plan) => (
              <button
                key={plan.id}
                type="button"
                className="fp-card"
                onClick={() => setSelectedId(plan.id)}
              >
                <span className="fp-card__thumb">
                  {/* eslint-disable-next-line @next/next/no-img-element -- 서명 URL(외부 오리진) — 목록 썸네일 */}
                  <img src={plan.imageUrl} alt="" />
                </span>
                <span className="fp-card__body">
                  <span className="fp-card__name">{plan.unitTypeName}</span>
                  <span className="fp-card__meta">
                    마커 {plan.deviceCount}개 · 수정 {shortDate(plan.updatedAt)}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}
      </main>

      {showUpload ? (
        <UploadDialog busy={uploadBusy} onCancel={() => setShowUpload(false)} onSubmit={handleUpload} />
      ) : null}

      {toast ? (
        <div className="fac-toast">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}

interface UploadDialogProps {
  busy: boolean;
  onCancel: () => void;
  onSubmit: (input: {
    unitTypeName: string;
    image: File;
    imageWidth: number;
    imageHeight: number;
  }) => void;
}

/** 도면 업로드 폼 — 파일에서 naturalWidth/Height를 읽어 함께 제출한다(서버 계약). */
function UploadDialog({ busy, onCancel, onSubmit }: UploadDialogProps) {
  const nameRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dims, setDims] = useState<{ width: number; height: number } | null>(null);
  const [error, setError] = useState<string | null>(null);

  function handleFile(picked: File) {
    setError(null);
    setDims(null);
    const url = URL.createObjectURL(picked);
    const img = new Image();
    img.onload = () => {
      setDims({ width: img.naturalWidth, height: img.naturalHeight });
      URL.revokeObjectURL(url);
    };
    img.onerror = () => {
      setError("이미지를 읽지 못했습니다. 다른 파일을 선택하세요.");
      URL.revokeObjectURL(url);
    };
    img.src = url;
    setFile(picked);
  }

  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <form
        className="dialog fac-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="도면 업로드"
        onClick={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          const unitTypeName = nameRef.current?.value.trim() ?? "";
          if (!unitTypeName) {
            setError("타입명을 입력하세요.");
            return;
          }
          if (!file || !dims) {
            setError("도면 이미지를 선택하세요.");
            return;
          }
          onSubmit({ unitTypeName, image: file, imageWidth: dims.width, imageHeight: dims.height });
        }}
      >
        <div className="dialog__title">도면 업로드</div>
        <div className="fac-dialog__body">
          <label className="fac-field">
            <span className="form-field__label">타입명</span>
            <input
              ref={nameRef}
              className="form-field__input"
              defaultValue=""
              placeholder="예: 84M"
            />
          </label>
          <FileDropzone
            label="도면 이미지"
            accept="image/*"
            maxSizeMb={20}
            onFile={handleFile}
            state={file ? "selected" : "idle"}
            fileName={file?.name}
          />
          {error ? <div className="form-field__error">{error}</div> : null}
        </div>
        <div className="dialog__actions">
          <button type="button" className="btn btn--secondary btn--sm" onClick={onCancel}>
            취소
          </button>
          <Button variant="primary" type="submit" disabled={busy}>
            업로드
          </Button>
        </div>
      </form>
    </div>
  );
}
