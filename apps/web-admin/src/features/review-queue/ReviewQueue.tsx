"use client";

import { Button, CitationCard, ConfidenceBadge, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  decideReview,
  listReviewQueue,
  type ReviewItem,
  type ReviewStatus,
} from "@/lib/api";
import {
  REVIEW_TABS,
  confidenceLook,
  confidencePercent,
  displayableCitations,
  reviewTime,
} from "./data";
import "./review-queue.css";

const TOAST_DURATION_MS = 3200;

interface ToastState {
  message: string;
  tone: ToastTone;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function ReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tab, setTab] = useState<ReviewStatus>("needs_review");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rejecting, setRejecting] = useState<ReviewItem | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async (status: ReviewStatus) => {
    setLoading(true);
    try {
      const result = await listReviewQueue(status);
      setItems(result.items);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(tab);
  }, [load, tab]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  async function handleApprove(item: ReviewItem) {
    setBusyId(item.messageId);
    try {
      await decideReview(item.messageId, "approve");
      setItems((prev) => prev.filter((i) => i.messageId !== item.messageId));
      showToast("승인 처리했습니다. 골든셋 후보로 축적됩니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  async function handleReject(item: ReviewItem, note: string) {
    setBusyId(item.messageId);
    try {
      await decideReview(item.messageId, "reject", note);
      setItems((prev) => prev.filter((i) => i.messageId !== item.messageId));
      setRejecting(null);
      showToast("반려 처리했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setBusyId(null);
    }
  }

  const isPending = tab === "needs_review";

  return (
    <>
      <header className="admin-page__header">
        <div className="rq-head">
          <div>
            <div className="rq-head__titlerow">
              <h1 id="main" className="admin-page__title">
                AI 검수 큐
              </h1>
              {isPending && !loading ? (
                <span className="rq-head__count">{items.length}건 대기</span>
              ) : null}
            </div>
            <p className="admin-page__lede">
              신뢰도가 낮거나 출처가 약한 답변을 사후 검토합니다. 승인·반려는 골든셋·FAQ 개선에
              반영되며, 이미 전달된 답변을 회수하지 않습니다.
            </p>
          </div>
        </div>
        <div className="rq-tabs" role="tablist" aria-label="검수 상태 필터">
          {REVIEW_TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={tab === t.id}
              className="rq-tab"
              data-active={tab === t.id || undefined}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <main className="admin-page__main">
        <ReviewBody
          loading={loading}
          loadError={loadError}
          items={items}
          tab={tab}
          busyId={busyId}
          onRetry={() => void load(tab)}
          onApprove={handleApprove}
          onReject={(item) => setRejecting(item)}
        />
      </main>

      {rejecting ? (
        <RejectDialog
          item={rejecting}
          busy={busyId === rejecting.messageId}
          onCancel={() => setRejecting(null)}
          onConfirm={(note) => void handleReject(rejecting, note)}
        />
      ) : null}

      {toast ? (
        <div className="rq-toast">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </>
  );
}

interface ReviewBodyProps {
  loading: boolean;
  loadError: string | null;
  items: readonly ReviewItem[];
  tab: ReviewStatus;
  busyId: string | null;
  onRetry: () => void;
  onApprove: (item: ReviewItem) => void;
  onReject: (item: ReviewItem) => void;
}

function ReviewBody({
  loading,
  loadError,
  items,
  tab,
  busyId,
  onRetry,
  onApprove,
  onReject,
}: ReviewBodyProps) {
  if (loading) {
    return (
      <div className="rq-list">
        <Skeleton height="8rem" />
        <Skeleton height="8rem" />
      </div>
    );
  }
  if (loadError) {
    return (
      <EmptyState
        icon="⚠"
        title="검수 큐를 불러오지 못했습니다"
        description={loadError}
        action={<Button onClick={onRetry}>다시 시도</Button>}
      />
    );
  }
  if (items.length === 0) {
    return tab === "needs_review" ? (
      <EmptyState
        icon="✓"
        title="검수 대기 항목이 없습니다"
        description="신뢰도가 낮은 새 답변이 생기면 이곳에 모입니다."
      />
    ) : (
      <EmptyState icon="📄" title="해당 상태의 항목이 없습니다" description="다른 탭을 확인해 보세요." />
    );
  }
  return (
    <div className="rq-list">
      {items.map((item) => (
        <ReviewCard
          key={item.messageId}
          item={item}
          busy={busyId === item.messageId}
          onApprove={onApprove}
          onReject={onReject}
        />
      ))}
    </div>
  );
}

interface ReviewCardProps {
  item: ReviewItem;
  busy: boolean;
  onApprove: (item: ReviewItem) => void;
  onReject: (item: ReviewItem) => void;
}

function ReviewCard({ item, busy, onApprove, onReject }: ReviewCardProps) {
  const pct = confidencePercent(item.confidence);
  const look = confidenceLook(item.confidence ?? 0);
  const sources = displayableCitations(item.citations);
  const isPending = item.reviewStatus === "needs_review";

  return (
    <article className="rq-card">
      <div className="rq-card__main">
        <div className="rq-card__meta">
          <span className="rq-card__asker">입주민 질문</span>
          <span aria-hidden="true">·</span>
          <span>{reviewTime(item.createdAt)}</span>
        </div>
        <h2 className="rq-card__question">{item.question ?? "(질문을 찾을 수 없음)"}</h2>

        <div className="rq-card__sublabel">AI 답변</div>
        <p className="rq-card__answer">{item.answer}</p>

        {sources.length > 0 ? (
          <div className="rq-list">
            {sources.map((c, idx) => (
              <CitationCard
                key={idx}
                title={c.documentTitle ?? "출처"}
                meta={c.quote ?? undefined}
                href="/documents"
              />
            ))}
          </div>
        ) : (
          <div className="rq-nosource" role="note">
            <div className="rq-nosource__head">
              <span aria-hidden="true">⚠</span> 근거 문서를 찾지 못함
            </div>
            <div className="rq-nosource__desc">
              출처 없는 답변입니다. ‘담당자 연결’ 폴백이 적절했는지 확인하세요.
            </div>
          </div>
        )}
      </div>

      <div className="rq-card__side">
        <div>
          <div className="rq-conf__top">
            <span className="rq-conf__label">신뢰도</span>
            <ConfidenceBadge status={isPending ? "review" : "answered"} label={look.label} />
          </div>
          <div
            className="rq-conf__meter"
            role="meter"
            aria-valuenow={pct ?? 0}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="AI 신뢰도"
          >
            <span style={{ width: `${pct ?? 0}%`, background: look.color }} />
          </div>
          <div className="rq-conf__score">
            {pct ?? "—"}
            <span className="rq-conf__denom">/100</span>
          </div>
        </div>

        {isPending ? (
          <div className="rq-actions">
            <Button variant="primary" disabled={busy} onClick={() => onApprove(item)}>
              승인
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => onReject(item)}>
              반려
            </Button>
          </div>
        ) : (
          <div className="rq-decided">
            <div className="rq-decided__status">
              {item.reviewStatus === "approved" ? "승인됨" : "반려됨"}
              {item.reviewedAt ? ` · ${reviewTime(item.reviewedAt)}` : ""}
            </div>
            {item.reviewNote ? <div className="rq-decided__note">{item.reviewNote}</div> : null}
          </div>
        )}
      </div>
    </article>
  );
}

interface RejectDialogProps {
  item: ReviewItem;
  busy: boolean;
  onCancel: () => void;
  onConfirm: (note: string) => void;
}

function RejectDialog({ item, busy, onCancel, onConfirm }: RejectDialogProps) {
  const [note, setNote] = useState("");
  const canSubmit = note.trim().length > 0 && !busy;

  return (
    <div className="dialog-backdrop" onClick={onCancel}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rq-reject-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dialog__title" id="rq-reject-title">
          답변 반려
        </div>
        <div className="dialog__desc">
          반려 사유를 남겨 주세요. 사유는 골든셋·FAQ 개선에 활용됩니다.
        </div>
        <label className="rq-reject__label" htmlFor="rq-reject-note">
          반려 사유
        </label>
        <textarea
          id="rq-reject-note"
          className="rq-reject__textarea"
          rows={3}
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={`예: "${(item.question ?? "").slice(0, 20)}" 에 대한 근거가 부정확함`}
        />
        <div className="dialog__actions">
          <button type="button" className="btn btn--secondary btn--sm" onClick={onCancel}>
            취소
          </button>
          <button
            type="button"
            className="btn btn--danger btn--sm"
            disabled={!canSubmit}
            onClick={() => onConfirm(note.trim())}
          >
            반려 확정
          </button>
        </div>
      </div>
    </div>
  );
}
