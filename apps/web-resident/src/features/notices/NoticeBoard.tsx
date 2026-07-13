"use client";

import { useState } from "react";
import "./notices.css";

type NoticeKind = "important" | "life" | "work" | "event";

interface Notice {
  id: string;
  kind: NoticeKind;
  tag: string;
  title: string;
  author: string;
  date: string;
  unread?: boolean;
  body: string[];
  summary: string;
}

const NOTICES: readonly Notice[] = [
  {
    id: "n1",
    kind: "important",
    tag: "중요",
    title: "6/22(월) 03:00~05:00 단수 안내 (배관 교체)",
    author: "관리사무소",
    date: "2시간 전",
    unread: true,
    body: [
      "안녕하세요, 래미안 한강 1단지 관리사무소입니다.",
      "노후 배관 교체 공사로 인해 아래와 같이 단수가 예정되어 있어 안내드립니다.",
      "· 일시: 2026년 6월 22일(월) 03:00 ~ 05:00 (약 2시간)\n· 대상: 1203동 전 세대\n· 유의: 단수 시간 동안 수돗물을 미리 받아두시기 바랍니다.",
      "공사 진행 상황에 따라 종료 시각이 다소 변동될 수 있습니다. 양해 부탁드립니다.",
    ],
    summary:
      "6/22 새벽 2시간 동안 1203동 단수 예정. 물을 미리 받아두세요. 정확한 종료 시각은 관리사무소 확인이 필요합니다.",
  },
  {
    id: "n2",
    kind: "life",
    tag: "생활",
    title: "여름철 분리수거 배출 시간 변경 안내",
    author: "관리사무소",
    date: "어제",
    body: [
      "여름철 악취·위생 관리를 위해 분리수거 배출 시간이 변경됩니다.",
      "· 변경 후: 매일 18:00 ~ 22:00\n· 적용일: 2026년 7월 1일부터",
    ],
    summary: "7/1부터 분리수거 배출 시간이 매일 18~22시로 변경됩니다.",
  },
  {
    id: "n3",
    kind: "work",
    tag: "공사",
    title: "지하주차장 B2 바닥 보수 공사 (6/25~6/27)",
    author: "시설팀",
    date: "2일 전",
    body: [
      "지하주차장 B2 바닥 균열 보수 공사를 진행합니다.",
      "· 기간: 6/25(수) ~ 6/27(금)\n· 해당 구역 주차가 제한되니 B1·B3를 이용해 주세요.",
    ],
    summary: "6/25~27 지하 B2 바닥 보수로 해당 구역 주차가 제한됩니다.",
  },
  {
    id: "n4",
    kind: "event",
    tag: "행사",
    title: "단지 여름 벼룩시장 참가 신청 안내",
    author: "입주자대표회의",
    date: "3일 전",
    body: [
      "입주민 교류를 위한 여름 벼룩시장을 개최합니다.",
      "· 일시: 7/13(일) 10:00 ~ 15:00\n· 장소: 중앙광장\n· 참가 신청은 관리사무소 또는 앱에서 가능합니다.",
    ],
    summary: "7/13 중앙광장 벼룩시장. 참가 신청은 앱·관리사무소에서.",
  },
  {
    id: "n5",
    kind: "life",
    tag: "생활",
    title: "택배 보관함 이용 규칙 안내",
    author: "관리사무소",
    date: "5일 전",
    body: ["택배 보관함은 48시간 내 수령을 원칙으로 합니다. 장기 미수령 시 경비실로 이동됩니다."],
    summary: "택배 보관함은 48시간 내 수령해 주세요.",
  },
];

const FILTERS: { id: "all" | NoticeKind; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "important", label: "중요" },
  { id: "life", label: "생활" },
  { id: "work", label: "공사" },
  { id: "event", label: "행사" },
];

export function NoticeBoard() {
  const [filter, setFilter] = useState<"all" | NoticeKind>("all");
  const [openId, setOpenId] = useState<string | null>(null);

  const open = openId ? NOTICES.find((n) => n.id === openId) ?? null : null;
  if (open) {
    return <NoticeDetail notice={open} onBack={() => setOpenId(null)} />;
  }

  const visible = filter === "all" ? NOTICES : NOTICES.filter((n) => n.kind === filter);

  return (
    <div className="notices">
      <header className="notices__header">
        <h1 id="main" className="notices__title">
          공지
        </h1>
        <div className="notices__filters" role="tablist" aria-label="말머리 필터">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              role="tab"
              aria-selected={filter === f.id}
              className="notice-filter"
              data-active={filter === f.id || undefined}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
      </header>

      <main className="notices__list">
        {visible.map((n) => (
          <button key={n.id} type="button" className="notice-card" onClick={() => setOpenId(n.id)}>
            <div className="notice-card__top">
              <span className={`tag tag--${n.kind}`}>{n.tag}</span>
              {n.unread ? <span className="notice-card__dot" aria-label="안읽음" /> : null}
              <span className="notice-card__date">{n.date}</span>
            </div>
            <div className="notice-card__title" data-read={!n.unread || undefined}>
              {n.title}
            </div>
            <div className="notice-card__author">{n.author}</div>
          </button>
        ))}
      </main>
    </div>
  );
}

function NoticeDetail({ notice, onBack }: { notice: Notice; onBack: () => void }) {
  return (
    <div className="notices">
      <header className="notice-detail__bar">
        <button type="button" className="notice-detail__back" aria-label="목록으로" onClick={onBack}>
          ←
        </button>
        <span className="notice-detail__barlabel">공지 상세</span>
      </header>
      <main id="main" className="notice-detail">
        <div className="notice-detail__meta">
          <span className={`tag tag--${notice.kind}`}>{notice.tag}</span>
          <span className="notice-detail__metatext">
            {notice.author} · {notice.date}
          </span>
        </div>
        <h1 className="notice-detail__title">{notice.title}</h1>
        <div className="notice-detail__body">
          {notice.body.map((para, i) =>
            para.includes("·") ? (
              <div key={i} className="notice-detail__box">
                {para.split("\n").map((line, j) => (
                  <div key={j}>{line}</div>
                ))}
              </div>
            ) : (
              <p key={i}>{para}</p>
            ),
          )}
        </div>

        <div className="notice-summary">
          <div className="notice-summary__head">
            <span className="notice-summary__mark" aria-hidden="true">
              L
            </span>
            <span className="notice-summary__label">AI 요약</span>
          </div>
          <p className="notice-summary__text">{notice.summary}</p>
        </div>
      </main>
    </div>
  );
}
