import type { Metadata } from "next";
import Link from "next/link";
import { StatusPill } from "@liviq/ui";
import "./home.css";

export const metadata: Metadata = {
  title: "홈",
  description: "단지 요약 · 관리비 · 공지 · 바로가기",
};

const SHORTCUTS = [
  { href: "/fees", icon: "🧾", label: "관리비" },
  { href: "/inquiries", icon: "🛠", label: "민원접수" },
  { href: "/notices", icon: "📢", label: "공지" },
  { href: "/me", icon: "👤", label: "내 정보" },
] as const;

export default function HomePage() {
  return (
    <div className="home">
      <header className="home__header">
        <p className="home__place">
          <span aria-hidden="true">📍</span> 래미안 한강 1단지 · 1203동 1502호
        </p>
        <h1 className="home__greeting">홍*동님, 안녕하세요</h1>
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

        {/* 이번 달 관리비 */}
        <section className="surface-card fee-card" aria-labelledby="fee-heading">
          <div className="fee-card__top">
            <span id="fee-heading" className="fee-card__label">
              이번 달 관리비 · 2026.06
            </span>
            <span className="fee-card__delta">
              <span aria-hidden="true">▲</span> 12%
            </span>
          </div>
          <div className="fee-card__amount">₩238,400</div>
          <div className="fee-card__note">
            <span>난방비가 전월 대비 ₩18,200 늘었어요.</span>
            <Link href="/fees" className="fee-card__why">
              왜 올랐나요? →
            </Link>
          </div>
        </section>

        {/* 공지 */}
        <section className="surface-card notice-block" aria-labelledby="notice-heading">
          <div className="notice-block__head">
            <h2 id="notice-heading">공지</h2>
            <Link href="/notices" className="notice-block__all">
              전체 3건 →
            </Link>
          </div>
          <Link href="/notices" className="notice-row notice-row--divider">
            <span className="tag tag--important">
              <span aria-hidden="true">!</span> 중요
            </span>
            <span className="notice-row__body">
              <span className="notice-row__title">
                6/22(월) 03:00~05:00 단수 안내 (배관 교체)
              </span>
              <span className="notice-row__meta">관리사무소 · 2시간 전</span>
            </span>
          </Link>
          <Link href="/notices" className="notice-row">
            <span className="tag tag--plain">생활</span>
            <span className="notice-row__body">
              <span className="notice-row__title">여름철 분리수거 배출 시간 변경 안내</span>
              <span className="notice-row__meta">관리사무소 · 어제</span>
            </span>
          </Link>
        </section>

        {/* 내 민원 */}
        <section className="surface-card inquiry-block" aria-labelledby="inquiry-heading">
          <h2 id="inquiry-heading">내 민원</h2>
          <Link href="/inquiries" className="inquiry-row">
            <span className="inquiry-row__body">
              <span className="inquiry-row__title">1203동 엘리베이터 소음</span>
              <span className="inquiry-row__meta">접수 2일 전 · 시설팀 확인 중</span>
            </span>
            <StatusPill status="progress" />
          </Link>
        </section>

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
