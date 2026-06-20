import type { Metadata } from "next";
import Link from "next/link";
import { ADMIN_SCREENS, priorityColor, RESIDENT_SCREENS, type ScreenItem } from "@/lib/screens";
import "./page.css";

export const metadata: Metadata = {
  title: "전체 화면",
  description:
    "아파트 관리의 AI 검색·응대·요약 계층. 입주민 모바일 앱 6화면, 관리자 데스크톱 콘솔 7화면.",
};

function ScreenCard({ screen }: { screen: ScreenItem }) {
  return (
    <Link className="screen-card" href={screen.href}>
      <span className="screen-card__icon" aria-hidden="true">
        {screen.icon}
      </span>
      <span className="screen-card__title">{screen.title}</span>
      <span className="screen-card__desc">{screen.desc}</span>
      <span className="screen-card__priority" style={{ color: priorityColor(screen.priority) }}>
        {screen.priority}
      </span>
    </Link>
  );
}

export default function OverviewPage() {
  return (
    <main id="main" className="overview">
      <header className="overview__header">
        <div className="overview__brand">
          <span className="overview__logo" aria-hidden="true">
            L
          </span>
          <span className="overview__wordmark">LIVIQ</span>
        </div>
        <h1 className="overview__title">전체 화면</h1>
        <p className="overview__lede">
          아파트 관리의 AI 검색·응대·요약 계층. 입주민 모바일 앱 6화면, 관리자 데스크톱 콘솔
          7화면. 각 카드를 눌러 해당 화면으로 이동하세요.
        </p>
      </header>

      <section className="overview__section" aria-labelledby="resident-heading">
        <div className="overview__section-head">
          <h2 id="resident-heading" className="overview__section-title">
            입주민 앱
          </h2>
          <span className="overview__section-meta">모바일 우선 · 하단 탭 5</span>
        </div>
        <div className="screen-grid">
          {RESIDENT_SCREENS.map((screen) => (
            <ScreenCard key={screen.href} screen={screen} />
          ))}
        </div>
      </section>

      <section className="overview__section" aria-labelledby="admin-heading">
        <div className="overview__section-head">
          <h2 id="admin-heading" className="overview__section-title">
            관리자 콘솔
          </h2>
          <span className="overview__section-meta">데스크톱 우선 · 좌측 사이드바</span>
        </div>
        <div className="screen-grid">
          {ADMIN_SCREENS.map((screen) => (
            <ScreenCard key={screen.href} screen={screen} />
          ))}
        </div>
      </section>

      <footer className="overview__footer">
        토큰 정의·핵심 컴포넌트는{" "}
        <Link className="overview__footer-link" href="/foundation">
          파운데이션
        </Link>
        에서 확인할 수 있습니다.
      </footer>
    </main>
  );
}
