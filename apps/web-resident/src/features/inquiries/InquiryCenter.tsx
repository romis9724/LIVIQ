"use client";

import { Button, EmptyState, Skeleton, StatusPill, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createInquiry,
  listInquiryCategories,
  listInquiryEvents,
  listMyInquiries,
  postInquiryFeedback,
  reopenInquiry,
  type Inquiry,
  type InquiryCategory,
  type InquiryEvent,
} from "@/lib/api";
import {
  commentBody,
  commentKind,
  eventLabel,
  formatStatusChange,
  sortEvents,
  statusPill,
} from "./data";
import "./inquiries.css";

const TOAST_DURATION_MS = 3200;

type View = "list" | "submit";

interface ToastState {
  message: string;
  tone: ToastTone;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function messageTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  return `${date.getMonth() + 1}/${date.getDate()} ${hh}:${mm}`;
}

// 카테고리 코드 id → 라벨. 미매칭/없음이면 null.
function categoryLabelOf(
  categories: readonly InquiryCategory[],
  id: string | null,
): string | null {
  if (!id) return null;
  return categories.find((c) => c.id === id)?.label ?? null;
}

export function InquiryCenter() {
  const [view, setView] = useState<View>("list");
  const [selected, setSelected] = useState<Inquiry | null>(null);
  const [inquiries, setInquiries] = useState<Inquiry[]>([]);
  const [categories, setCategories] = useState<InquiryCategory[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async () => {
    try {
      setInquiries(await listMyInquiries());
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 카테고리 라벨 매핑용 — 실패해도 화면 차단 없이 칩만 생략(비필수).
  useEffect(() => {
    let alive = true;
    listInquiryCategories()
      .then((items) => {
        if (alive) setCategories(items);
      })
      .catch(() => {
        // 카테고리 로드 실패는 무시 — 칩·select 옵션만 비워둔다
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  const handleSubmitted = useCallback(
    async (created: Inquiry) => {
      showToast("민원을 접수했습니다.");
      setView("list");
      setInquiries((prev) => [created, ...prev]);
      await load();
    },
    [load, showToast],
  );

  if (selected) {
    return (
      <>
        <InquiryDetail
          inquiry={selected}
          categories={categories}
          onBack={() => setSelected(null)}
          onToast={showToast}
        />
        {toast ? (
          <div className="inq-toast-slot">
            <Toast message={toast.message} tone={toast.tone} />
          </div>
        ) : null}
      </>
    );
  }

  return (
    <div className="inq">
      <header className="inq__header">
        <h1 id="main" className="inq__title">
          민원·하자
        </h1>
        <div className="inq__seg" role="tablist" aria-label="민원 보기">
          <button
            role="tab"
            aria-selected={view === "list"}
            className="inq-seg__btn"
            data-active={view === "list" || undefined}
            onClick={() => setView("list")}
          >
            내 민원
          </button>
          <button
            role="tab"
            aria-selected={view === "submit"}
            className="inq-seg__btn"
            data-active={view === "submit" || undefined}
            onClick={() => setView("submit")}
          >
            접수하기
          </button>
        </div>
      </header>

      {view === "list" ? (
        <InquiryList
          inquiries={inquiries}
          categories={categories}
          loading={loading}
          loadError={loadError}
          onSelect={setSelected}
          onRetry={() => {
            setLoading(true);
            void load();
          }}
          onSubmitCta={() => setView("submit")}
        />
      ) : (
        <SubmitForm
          categories={categories}
          onSubmitted={handleSubmitted}
          onError={(m) => showToast(m, "danger")}
        />
      )}

      {toast ? (
        <div className="inq-toast-slot">
          <Toast message={toast.message} tone={toast.tone} />
        </div>
      ) : null}
    </div>
  );
}

interface InquiryListProps {
  inquiries: readonly Inquiry[];
  categories: readonly InquiryCategory[];
  loading: boolean;
  loadError: string | null;
  onSelect: (inquiry: Inquiry) => void;
  onRetry: () => void;
  onSubmitCta: () => void;
}

function InquiryList({
  inquiries,
  categories,
  loading,
  loadError,
  onSelect,
  onRetry,
  onSubmitCta,
}: InquiryListProps) {
  if (loading) {
    return (
      <main className="inq__list">
        <Skeleton height="5rem" radius="var(--radius-md)" />
        <Skeleton height="5rem" radius="var(--radius-md)" />
        <Skeleton height="5rem" radius="var(--radius-md)" />
      </main>
    );
  }
  if (loadError) {
    return (
      <main className="inq__list">
        <EmptyState
          icon="⚠"
          title="민원을 불러오지 못했습니다"
          description={loadError}
          action={<Button onClick={onRetry}>다시 시도</Button>}
        />
      </main>
    );
  }
  if (inquiries.length === 0) {
    return (
      <main className="inq__list">
        <EmptyState
          icon="📝"
          title="접수한 민원이 없습니다"
          description="불편사항을 접수하면 처리 상황을 여기서 확인할 수 있습니다."
          action={<Button onClick={onSubmitCta}>민원 접수하기</Button>}
        />
      </main>
    );
  }
  return (
    <main className="inq__list">
      {inquiries.map((inquiry) => {
        const pill = statusPill(inquiry.status);
        const catLabel = categoryLabelOf(categories, inquiry.categoryCodeId);
        return (
          <button
            key={inquiry.id}
            type="button"
            className="inq-card"
            onClick={() => onSelect(inquiry)}
          >
            <div className="inq-card__top">
              {catLabel ? <span className="inq-card__tag">{catLabel}</span> : null}
              <StatusPill status={pill.status} label={pill.label} />
              <span className="inq-card__date">{shortDate(inquiry.createdAt)}</span>
            </div>
            <div className="inq-card__title">{inquiry.title}</div>
          </button>
        );
      })}
    </main>
  );
}

interface SubmitFormProps {
  categories: readonly InquiryCategory[];
  onSubmitted: (created: Inquiry) => void | Promise<void>;
  onError: (message: string) => void;
}

function SubmitForm({ categories, onSubmitted, onError }: SubmitFormProps) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [categoryCodeId, setCategoryCodeId] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !body.trim() || submitting) return;
    setSubmitting(true);
    try {
      const created = await createInquiry({
        title: title.trim(),
        body: body.trim(),
        categoryCodeId: categoryCodeId || null,
      });
      setTitle("");
      setBody("");
      setCategoryCodeId("");
      await onSubmitted(created);
    } catch (err) {
      onError(err instanceof ApiError || err instanceof Error ? err.message : "접수에 실패했습니다.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="inq-form" onSubmit={handleSubmit}>
      <div className="inq-form__scroll">
        <div className="inq-field">
          <div className="inq-field-label">사진 첨부</div>
          <div className="inq-photos" aria-disabled="true">
            <button type="button" className="inq-photo-add" disabled>
              <span aria-hidden="true">＋</span>
              <span>사진</span>
            </button>
          </div>
          <div className="inq-field-help">사진 첨부는 추후 지원될 예정입니다.</div>
        </div>

        <div className="inq-field">
          <label htmlFor="inq-category" className="inq-field-label">
            분류
          </label>
          <div className="inq-select">
            <select
              id="inq-category"
              className="inq-select__input"
              value={categoryCodeId}
              onChange={(e) => setCategoryCodeId(e.target.value)}
            >
              <option value="">분류 선택(선택 안 함)</option>
              {categories.map((cat) => (
                <option key={cat.id} value={cat.id}>
                  {cat.label}
                </option>
              ))}
            </select>
          </div>
          <div className="inq-field-help">
            분류를 고르면 담당 부서에 더 빨리 전달됩니다. 비워두어도 접수됩니다.
          </div>
        </div>

        <div className="inq-field">
          <label htmlFor="inq-title" className="inq-field-label">
            제목
          </label>
          <input
            id="inq-title"
            className="inq-input"
            value={title}
            maxLength={200}
            required
            onChange={(e) => setTitle(e.target.value)}
            placeholder="예: 1203동 엘리베이터 소음"
          />
        </div>

        <div className="inq-field">
          <label htmlFor="inq-body" className="inq-field-label">
            상세 내용
          </label>
          <textarea
            id="inq-body"
            className="inq-textarea"
            rows={4}
            maxLength={4000}
            required
            aria-describedby="inq-body-help"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="불편사항을 자세히 적어주세요."
          />
          <div id="inq-body-help" className="inq-field-help">
            <span aria-hidden="true">🔒</span> 이름·연락처는 자동 마스킹되어 담당자에게 전달됩니다.
          </div>
        </div>
      </div>

      <div className="inq-form__footer">
        <Button type="submit" variant="primary" className="inq-submit" disabled={submitting}>
          {submitting ? "접수 중…" : "접수하기"}
        </Button>
      </div>
    </form>
  );
}

interface InquiryDetailProps {
  inquiry: Inquiry;
  categories: readonly InquiryCategory[];
  onBack: () => void;
  onToast: (message: string, tone?: ToastTone) => void;
}

function InquiryDetail({ inquiry: initial, categories, onBack, onToast }: InquiryDetailProps) {
  const [inquiry, setInquiry] = useState<Inquiry>(initial);
  const [events, setEvents] = useState<InquiryEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const [reopening, setReopening] = useState(false);
  const pill = statusPill(inquiry.status);
  const catLabel = categoryLabelOf(categories, inquiry.categoryCodeId);
  // 피드백은 처리중·재확인 상태에서만 남길 수 있다(백엔드 계약과 동일).
  const canFeedback = inquiry.status === "in_progress" || inquiry.status === "reopened";
  const canReopen = inquiry.status === "done";

  const load = useCallback(async () => {
    try {
      setError(null);
      setEvents(sortEvents(await listInquiryEvents(inquiry.id)));
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [inquiry.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleSend = useCallback(async () => {
    const text = feedback.trim();
    if (!text || sending || !canFeedback) return;
    setSending(true);
    setSendError(null);
    try {
      await postInquiryFeedback(inquiry.id, text);
      setFeedback("");
      await load();
    } catch (err) {
      setSendError(errorMessage(err));
    } finally {
      setSending(false);
    }
  }, [feedback, sending, canFeedback, inquiry.id, load]);

  const handleReopen = useCallback(async () => {
    if (reopening) return;
    setReopening(true);
    try {
      setInquiry(await reopenInquiry(inquiry.id));
      await load();
      onToast("재확인을 요청했습니다.");
    } catch (err) {
      onToast(errorMessage(err), "danger");
    } finally {
      setReopening(false);
    }
  }, [reopening, inquiry.id, load, onToast]);

  return (
    <div className="inq">
      <header className="inq-detail__bar">
        <button type="button" className="inq-detail__back" aria-label="목록으로" onClick={onBack}>
          ←
        </button>
        <span className="inq-detail__barlabel">민원 상세</span>
      </header>

      <main id="main" className="inq-detail">
        <div className="inq-detail__head">
          <div className="inq-detail__meta">
            <StatusPill status={pill.status} label={pill.label} />
            {catLabel ? <span className="inq-card__tag">{catLabel}</span> : null}
            <span className="inq-detail__sub">접수 · {shortDate(inquiry.createdAt)}</span>
          </div>
          <h1 className="inq-detail__title">{inquiry.title}</h1>
        </div>

        <Thread inquiry={inquiry} events={events} error={error} onRetry={load} />
      </main>

      {canReopen ? (
        <div className="inq-composer">
          <p className="inq-composer__hint">
            처리 결과가 만족스럽지 않으면 재확인을 요청하세요.
          </p>
          <Button
            type="button"
            variant="primary"
            className="inq-submit"
            disabled={reopening}
            onClick={handleReopen}
          >
            {reopening ? "요청 중…" : "재확인 요청"}
          </Button>
        </div>
      ) : (
        <FeedbackComposer
          value={feedback}
          onChange={setFeedback}
          onSend={handleSend}
          sending={sending}
          error={sendError}
          enabled={canFeedback}
        />
      )}
    </div>
  );
}

// 대화 스레드 — 원 민원(작성자 최초 글)을 첫 항목으로, 이후 events 를 시스템/발신자별로 렌더.
function Thread({
  inquiry,
  events,
  error,
  onRetry,
}: {
  inquiry: Inquiry;
  events: InquiryEvent[] | null;
  error: string | null;
  onRetry: () => void;
}) {
  if (error) {
    return (
      <EmptyState
        icon="⚠"
        title="처리 내역을 불러오지 못했습니다"
        description={error}
        action={<Button onClick={onRetry}>다시 시도</Button>}
      />
    );
  }

  return (
    <div className="inq-thread">
      {/* 원 민원 — 내가 최초로 접수한 글 (우측 정렬) */}
      <article className="inq-msg" data-side="me">
        <div className="inq-msg__who">나</div>
        <div className="inq-msg__bubble">{inquiry.body}</div>
        <div className="inq-msg__time">{messageTime(inquiry.createdAt)}</div>
      </article>

      {events === null ? (
        <div className="inq-thread__loading">
          <Skeleton height="3rem" />
          <Skeleton height="3rem" />
        </div>
      ) : (
        events.map((ev) => <ThreadEntry key={ev.id} event={ev} />)
      )}
    </div>
  );
}

function ThreadEntry({ event: ev }: { event: InquiryEvent }) {
  if (ev.type === "comment") {
    const kind = commentKind(ev.payload);
    const text = commentBody(ev.payload);
    if (kind === "reply") {
      return (
        <article className="inq-msg" data-side="staff">
          <div className="inq-msg__who">관리사무소</div>
          <div className="inq-msg__bubble">{text}</div>
          <div className="inq-msg__time">{messageTime(ev.createdAt)}</div>
        </article>
      );
    }
    if (kind === "feedback") {
      return (
        <article className="inq-msg" data-side="me">
          <div className="inq-msg__who">나</div>
          <div className="inq-msg__bubble">{text}</div>
          <div className="inq-msg__time">{messageTime(ev.createdAt)}</div>
        </article>
      );
    }
    return null; // 알 수 없는 kind 는 표시하지 않음
  }

  // 시스템 이벤트 — 타임라인 레일에 muted 로 표시(말풍선 아님)
  const desc = ev.type === "status_changed" ? formatStatusChange(ev.payload) : null;
  return (
    <div className="inq-sysevent">
      <span className="inq-sysevent__dot" aria-hidden="true" />
      <span className="inq-sysevent__label">{eventLabel(ev.type)}</span>
      {desc ? <span className="inq-sysevent__desc">{desc}</span> : null}
      <span className="inq-sysevent__time">{messageTime(ev.createdAt)}</span>
    </div>
  );
}

interface FeedbackComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  sending: boolean;
  error: string | null;
  enabled: boolean;
}

function FeedbackComposer({
  value,
  onChange,
  onSend,
  sending,
  error,
  enabled,
}: FeedbackComposerProps) {
  return (
    <div className="inq-composer">
      {!enabled ? (
        <p className="inq-composer__hint">
          처리중일 때 처리 내용에 대해 피드백을 남길 수 있습니다.
        </p>
      ) : null}
      {error ? (
        <p className="inq-composer__error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="inq-composer__row">
        <label htmlFor="inq-feedback" className="sr-only">
          피드백 입력
        </label>
        <textarea
          id="inq-feedback"
          className="inq-composer__input"
          rows={1}
          maxLength={4000}
          disabled={!enabled || sending}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={enabled ? "처리 내용에 대한 피드백을 남겨주세요." : "피드백 비활성"}
        />
        <Button
          type="button"
          variant="primary"
          className="inq-composer__send"
          disabled={!enabled || sending || !value.trim()}
          onClick={onSend}
        >
          {sending ? "전송 중…" : "보내기"}
        </Button>
      </div>
    </div>
  );
}
