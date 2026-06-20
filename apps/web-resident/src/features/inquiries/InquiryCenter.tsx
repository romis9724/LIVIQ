"use client";

import { useState } from "react";
import { Button, FormField, StatusPill, type StatusKind } from "@liviq/ui";
import "./inquiries.css";

type View = "list" | "submit" | "detail";

interface Complaint {
  id: string;
  cat: string;
  status: StatusKind;
  statusLabel: string;
  title: string;
  date: string;
}

const COMPLAINTS: readonly Complaint[] = [
  { id: "c1", cat: "승강기", status: "progress", statusLabel: "처리중", title: "1203동 엘리베이터 소음", date: "2일 전" },
  { id: "c2", cat: "누수", status: "done", statusLabel: "완료", title: "지하주차장 천장 누수", date: "1주 전" },
  { id: "c3", cat: "조경", status: "received", statusLabel: "접수됨", title: "놀이터 옆 가로등 점멸", date: "3주 전" },
];

interface TimelineEvent {
  title: string;
  desc: string;
  time: string;
  current?: boolean;
  last?: boolean;
}

const TIMELINE: readonly TimelineEvent[] = [
  {
    title: "시설팀 현장 점검 예정",
    desc: "6/14(금) 오전 방문 예정입니다. 부재 시 관리사무소로 연락 주세요.",
    time: "방금 · 김*수 소장",
    current: true,
  },
  { title: "담당자 배정", desc: "AI 분류 ‘승강기’로 시설팀에 자동 배정되었습니다.", time: "어제 14:20" },
  { title: "민원 접수됨", desc: "사진 1장과 함께 정상 접수되었습니다.", time: "2일 전 09:05", last: true },
];

const AI_CATEGORIES = ["🛗 승강기 · 92%", "소음", "기타"];

export function InquiryCenter() {
  const [view, setView] = useState<View>("list");
  const [selected, setSelected] = useState<Complaint | null>(null);
  const [category, setCategory] = useState(0);

  if (view === "detail" && selected) {
    return <InquiryDetail complaint={selected} onBack={() => setView("list")} />;
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
        <main className="inq__list">
          {COMPLAINTS.map((c) => (
            <button
              key={c.id}
              type="button"
              className="inq-card"
              onClick={() => {
                setSelected(c);
                setView("detail");
              }}
            >
              <div className="inq-card__top">
                <span className="inq-card__cat">{c.cat}</span>
                <StatusPill status={c.status} label={c.statusLabel} />
                <span className="inq-card__date">{c.date}</span>
              </div>
              <div className="inq-card__title">{c.title}</div>
            </button>
          ))}
        </main>
      ) : (
        <SubmitForm
          category={category}
          onCategory={setCategory}
          onSubmit={() => setView("list")}
        />
      )}
    </div>
  );
}

function SubmitForm({
  category,
  onCategory,
  onSubmit,
}: {
  category: number;
  onCategory: (i: number) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="inq-form"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <div className="inq-form__scroll">
        <div className="inq-field-label">사진 첨부</div>
        <div className="inq-photos">
          <div className="inq-photo">
            <span aria-hidden="true" className="inq-photo__ph">
              🛗
            </span>
            <button type="button" className="inq-photo__del" aria-label="사진 삭제">
              ×
            </button>
          </div>
          <button type="button" className="inq-photo-add">
            <span aria-hidden="true">＋</span>
            <span>사진</span>
          </button>
        </div>

        <div className="inq-ai">
          <div className="inq-ai__head">
            <span className="inq-ai__mark" aria-hidden="true">
              L
            </span>
            <span className="inq-ai__label">AI 추천 분류</span>
          </div>
          <div className="inq-ai__chips">
            {AI_CATEGORIES.map((c, i) => (
              <button
                key={c}
                type="button"
                className="inq-cat"
                aria-pressed={category === i}
                data-active={category === i || undefined}
                onClick={() => onCategory(i)}
              >
                {c}
              </button>
            ))}
          </div>
        </div>

        <FormField label="제목" defaultValue="1203동 엘리베이터 소음" wrapperClassName="inq-field" />

        <div className="inq-field">
          <label htmlFor="inq-body" className="inq-field-label">
            상세 내용
          </label>
          <textarea
            id="inq-body"
            className="inq-textarea"
            rows={4}
            aria-describedby="inq-body-help"
            defaultValue="최근 일주일째 저층 운행 시 ‘덜컹’ 소음이 납니다. 특히 야간에 심합니다."
          />
          <div id="inq-body-help" className="inq-field-help">
            <span aria-hidden="true">🔒</span> 이름·연락처는 자동 마스킹되어 담당자에게 전달됩니다.
          </div>
        </div>
      </div>

      <div className="inq-form__footer">
        <Button type="submit" variant="primary" className="inq-submit">
          접수하기
        </Button>
      </div>
    </form>
  );
}

function InquiryDetail({ complaint, onBack }: { complaint: Complaint; onBack: () => void }) {
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
          <span className="inq-card__cat">{complaint.cat}</span>
          <StatusPill status={complaint.status} label={complaint.statusLabel} />
        </div>
        <h1 className="inq-detail__title">{complaint.title}</h1>
        <div className="inq-detail__sub">접수번호 C-2026-0612 · 담당 시설팀</div>

        <ol className="inq-timeline">
          {TIMELINE.map((ev, i) => (
            <li key={i} className="inq-timeline__item">
              <div className="inq-timeline__rail">
                <span
                  className="inq-timeline__dot"
                  data-current={ev.current || undefined}
                  aria-hidden="true"
                />
                {!ev.last ? <span className="inq-timeline__line" aria-hidden="true" /> : null}
              </div>
              <div className="inq-timeline__body">
                <div className="inq-timeline__title" data-muted={!ev.current || undefined}>
                  {ev.title}
                </div>
                <div className="inq-timeline__desc">{ev.desc}</div>
                <div className="inq-timeline__time">{ev.time}</div>
              </div>
            </li>
          ))}
        </ol>
      </main>
    </div>
  );
}
