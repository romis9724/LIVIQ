"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Skeleton, StatusPill } from "@liviq/ui";
import {
  getMe,
  listMyInquiries,
  listNotices,
  listNotifications,
  type Inquiry,
  type Notice,
} from "@/lib/api";
import { feeDelta, formatWon, getFees, type FeeData } from "../fees/api";
import { formatDate } from "../notices/data";
import { statusPill } from "../inquiries/data";
import {
  currentPeriod,
  greeting,
  periodLabel,
  recentInquiry,
  recentNotices,
  unreadCount,
} from "./logic";
import "./home.css";

/** 섹션별 독립 로딩 상태 — 한 섹션이 실패해도 나머지는 렌더한다. */
type Loadable<T> = { status: "loading" } | { status: "error" } | { status: "ready"; data: T };

const SHORTCUTS = [
  { href: "/fees", icon: "🧾", label: "관리비" },
  { href: "/inquiries", icon: "🛠", label: "민원접수" },
  { href: "/notices", icon: "📢", label: "공지" },
  { href: "/me", icon: "👤", label: "내 정보" },
] as const;

export function HomeView() {
  const period = currentPeriod();
  const [fee, setFee] = useState<Loadable<FeeData>>({ status: "loading" });
  const [notices, setNotices] = useState<Loadable<Notice[]>>({ status: "loading" });
  const [inquiry, setInquiry] = useState<Loadable<Inquiry | null>>({ status: "loading" });
  const [unread, setUnread] = useState<Loadable<number>>({ status: "loading" });
  // 인사말용 본인 실명·세대. 실패해도 "안녕하세요" 폴백이라 별도 오류 UI 없음.
  const [greetingText, setGreetingText] = useState("안녕하세요");

  useEffect(() => {
    let alive = true;
    // 4개 섹션을 독립 조회 — 하나 실패가 다른 섹션을 막지 않는다.
    const run = <T,>(
      promise: Promise<T>,
      set: (state: Loadable<T>) => void,
    ): void => {
      promise
        .then((data) => alive && set({ status: "ready", data }))
        .catch(() => alive && set({ status: "error" }));
    };

    run(getFees(period), setFee);
    run(listNotices().then((all) => recentNotices(all)), setNotices);
    run(listMyInquiries().then((all) => recentInquiry(all)), setInquiry);
    run(listNotifications().then(unreadCount), setUnread);
    getMe()
      .then((me) => alive && setGreetingText(greeting(me.displayName, me.unitLabel)))
      .catch(() => {}); // 실패 시 기본 인사말 유지

    return () => {
      alive = false;
    };
  }, [period]);

  return (
    <div className="home">
      <header className="home__header">
        <h1 className="home__greeting">{greetingText}</h1>
        {unread.status === "ready" && unread.data > 0 ? (
          <Link href="/me" className="home__unread">
            <span aria-hidden="true">🔔</span> 안 읽은 알림 {unread.data}건
          </Link>
        ) : null}
      </header>

      <main id="main" className="home__main">
        {/* AI 비서 진입 (hero) */}
        <Link href="/assistant" className="home-hero">
          <span className="home-hero__mark" aria-hidden="true">
            L
          </span>
          <span className="home-hero__text">
            <span className="home-hero__title">무엇이든 물어보세요</span>
            <span className="home-hero__sub">규약·관리비·시설을 출처와 함께</span>
          </span>
          <span className="home-hero__arrow" aria-hidden="true">
            →
          </span>
        </Link>

        <FeeSection period={period} state={fee} />
        <NoticeSection state={notices} />
        <InquirySection state={inquiry} />

        {/* 바로가기 */}
        <nav className="shortcut-grid" aria-label="바로가기">
          {SHORTCUTS.map((s) => (
            <Link key={s.label} href={s.href} className="shortcut">
              <span className="shortcut__icon" aria-hidden="true">
                {s.icon}
              </span>
              <span className="shortcut__label">{s.label}</span>
            </Link>
          ))}
        </nav>
      </main>
    </div>
  );
}

function FeeSection({ period, state }: { period: string; state: Loadable<FeeData> }) {
  return (
    <section className="surface-card fee-card" aria-labelledby="fee-heading">
      <div className="fee-card__top">
        <span id="fee-heading" className="fee-card__label">
          이번 달 관리비 · {periodLabel(period)}
        </span>
        <FeeDelta state={state} />
      </div>
      {state.status === "loading" ? (
        <Skeleton height="2.4rem" />
      ) : state.status === "error" || state.data.total === null ? (
        <div className="fee-card__amount fee-card__amount--muted">— 원</div>
      ) : (
        <div className="fee-card__amount">{formatWon(state.data.total)}</div>
      )}
      <div className="fee-card__note">
        <span>
          {state.status === "ready" && state.data.total === null
            ? "아직 이번 달 관리비가 확정되지 않았어요."
            : "항목별 내역과 AI 설명을 확인하세요."}
        </span>
        <Link href="/fees" className="fee-card__why">
          자세히 →
        </Link>
      </div>
    </section>
  );
}

function FeeDelta({ state }: { state: Loadable<FeeData> }) {
  if (state.status !== "ready") return null;
  const delta = feeDelta(state.data.total, state.data.prevTotal);
  if (!delta || delta.direction === "flat") return null;
  return (
    <span className="fee-card__delta" data-down={delta.direction === "down" || undefined}>
      <span aria-hidden="true">{delta.direction === "up" ? "▲" : "▼"}</span>{" "}
      {formatWon(Math.abs(delta.amount))}
    </span>
  );
}

function NoticeSection({ state }: { state: Loadable<Notice[]> }) {
  return (
    <section className="surface-card notice-block" aria-labelledby="notice-heading">
      <div className="notice-block__head">
        <h2 id="notice-heading">공지</h2>
        <Link href="/notices" className="notice-block__all">
          전체 보기 →
        </Link>
      </div>
      {state.status === "loading" ? (
        <Skeleton height="3rem" />
      ) : state.status === "error" ? (
        <p className="home-section__msg">공지를 불러오지 못했어요.</p>
      ) : state.data.length === 0 ? (
        <p className="home-section__msg">등록된 공지가 없습니다.</p>
      ) : (
        state.data.map((n, i) => (
          <Link
            key={n.id}
            href="/notices"
            className={i < state.data.length - 1 ? "notice-row notice-row--divider" : "notice-row"}
          >
            <span className="notice-row__body">
              <span className="notice-row__title">{n.title}</span>
              <span className="notice-row__meta">관리사무소 · {formatDate(n.publishedAt)}</span>
            </span>
          </Link>
        ))
      )}
    </section>
  );
}

function InquirySection({ state }: { state: Loadable<Inquiry | null> }) {
  return (
    <section className="surface-card inquiry-block" aria-labelledby="inquiry-heading">
      <h2 id="inquiry-heading">내 민원</h2>
      {state.status === "loading" ? (
        <Skeleton height="2.5rem" />
      ) : state.status === "error" ? (
        <p className="home-section__msg">민원을 불러오지 못했어요.</p>
      ) : state.data === null ? (
        <p className="home-section__msg">접수한 민원이 없습니다.</p>
      ) : (
        <Link href="/inquiries" className="inquiry-row">
          <span className="inquiry-row__body">
            <span className="inquiry-row__title">{state.data.title}</span>
            <span className="inquiry-row__meta">접수 {formatDate(state.data.createdAt)}</span>
          </span>
          <StatusPill {...statusPill(state.data.status)} />
        </Link>
      )}
    </section>
  );
}
