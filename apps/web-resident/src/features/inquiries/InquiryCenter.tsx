"use client";

import { Button, EmptyState, Skeleton, StatusPill, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  createInquiry,
  listInquiryEvents,
  listMyInquiries,
  type Inquiry,
  type InquiryEvent,
} from "@/lib/api";
import {
  PRIORITY_LABEL,
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

export function InquiryCenter() {
  const [view, setView] = useState<View>("list");
  const [selected, setSelected] = useState<Inquiry | null>(null);
  const [inquiries, setInquiries] = useState<Inquiry[]>([]);
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
    return <InquiryDetail inquiry={selected} onBack={() => setSelected(null)} />;
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
        <SubmitForm onSubmitted={handleSubmitted} onError={(m) => showToast(m, "danger")} />
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
  loading: boolean;
  loadError: string | null;
  onSelect: (inquiry: Inquiry) => void;
  onRetry: () => void;
  onSubmitCta: () => void;
}

function InquiryList({
  inquiries,
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
        return (
          <button
            key={inquiry.id}
            type="button"
            className="inq-card"
            onClick={() => onSelect(inquiry)}
          >
            <div className="inq-card__top">
              {inquiry.aiPriority ? (
                <span className="inq-card__cat">{PRIORITY_LABEL[inquiry.aiPriority]}</span>
              ) : null}
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
  onSubmitted: (created: Inquiry) => void | Promise<void>;
  onError: (message: string) => void;
}

function SubmitForm({ onSubmitted, onError }: SubmitFormProps) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !body.trim() || submitting) return;
    setSubmitting(true);
    try {
      const created = await createInquiry({ title: title.trim(), body: body.trim() });
      setTitle("");
      setBody("");
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

        <div className="inq-ai">
          <div className="inq-ai__head">
            <span className="inq-ai__mark" aria-hidden="true">
              L
            </span>
            <span className="inq-ai__label">AI가 분류합니다</span>
          </div>
          <p className="inq-field-help">
            접수하면 AI가 카테고리와 우선순위를 자동으로 분류해 담당자에게 전달합니다.
          </p>
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

function InquiryDetail({ inquiry, onBack }: { inquiry: Inquiry; onBack: () => void }) {
  const [events, setEvents] = useState<InquiryEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pill = statusPill(inquiry.status);

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

  return (
    <div className="inq">
      <header className="inq-detail__bar">
        <button type="button" className="inq-detail__back" aria-label="목록으로" onClick={onBack}>
          ←
        </button>
        <span className="inq-detail__barlabel">민원 상세</span>
      </header>
      <main id="main" className="inq-detail">
        <div className="inq-detail__meta">
          {inquiry.aiPriority ? (
            <span className="inq-card__cat">{PRIORITY_LABEL[inquiry.aiPriority]}</span>
          ) : null}
          <StatusPill status={pill.status} label={pill.label} />
        </div>
        <h1 className="inq-detail__title">{inquiry.title}</h1>
        <div className="inq-detail__sub">접수 · {shortDate(inquiry.createdAt)}</div>
        <p className="inq-detail__body">{inquiry.body}</p>

        <Timeline events={events} error={error} onRetry={load} />
      </main>
    </div>
  );
}

function Timeline({
  events,
  error,
  onRetry,
}: {
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
  if (events === null) {
    return (
      <div className="inq-timeline-loading">
        <Skeleton height="3rem" />
        <Skeleton height="3rem" />
      </div>
    );
  }
  return (
    <ol className="inq-timeline">
      {events.map((ev, i) => {
        const last = i === events.length - 1; // 시간순 오름차순 → 마지막이 최신
        const desc = ev.type === "status_changed" ? formatStatusChange(ev.payload) : null;
        return (
          <li key={ev.id} className="inq-timeline__item">
            <div className="inq-timeline__rail">
              <span
                className="inq-timeline__dot"
                data-current={last || undefined}
                aria-hidden="true"
              />
              {!last ? <span className="inq-timeline__line" aria-hidden="true" /> : null}
            </div>
            <div className="inq-timeline__body">
              <div className="inq-timeline__title" data-muted={!last || undefined}>
                {eventLabel(ev.type)}
              </div>
              {desc ? <div className="inq-timeline__desc">{desc}</div> : null}
              <div className="inq-timeline__time">{shortDate(ev.createdAt)}</div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
