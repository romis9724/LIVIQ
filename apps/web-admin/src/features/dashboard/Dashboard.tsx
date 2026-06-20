import Link from "next/link";
import "./dashboard.css";

interface Kpi {
  label: string;
  value: string;
  delta: string;
  up: boolean;
  /** 좋은 결과면 초록(화살표 방향과 무관). */
  good: boolean;
}

const KPIS: readonly Kpi[] = [
  { label: "AI 자동해결률", value: "78.4%", delta: "4.1%p", up: true, good: true },
  { label: "환각(오답) 발생률", value: "1.2%", delta: "0.3%p", up: false, good: true },
  { label: "질의당 토큰 비용", value: "₩11.4", delta: "8%", up: false, good: true },
  { label: "미처리 민원", value: "3건", delta: "2건", up: true, good: false },
];

// 14일 일별 질의량 / 자동해결 (결정적 고정값, max 80)
const DAILY: readonly { total: number; solved: number; day: number }[] = [
  { total: 42, solved: 31, day: 1 },
  { total: 55, solved: 41, day: 2 },
  { total: 48, solved: 36, day: 3 },
  { total: 61, solved: 45, day: 4 },
  { total: 70, solved: 52, day: 5 },
  { total: 58, solved: 43, day: 6 },
  { total: 33, solved: 24, day: 7 },
  { total: 29, solved: 21, day: 8 },
  { total: 64, solved: 47, day: 9 },
  { total: 72, solved: 54, day: 10 },
  { total: 68, solved: 50, day: 11 },
  { total: 75, solved: 56, day: 12 },
  { total: 59, solved: 44, day: 13 },
  { total: 80, solved: 60, day: 14 },
];
const DAILY_MAX = 80;

const COMPLAINTS = [
  { label: "접수됨", count: 5, color: "var(--color-text-muted)", pct: "30%" },
  { label: "처리중", count: 8, color: "var(--color-accent)", pct: "48%" },
  { label: "완료", count: 23, color: "var(--color-success)", pct: "100%" },
  { label: "지연", count: 2, color: "var(--color-danger)", pct: "12%" },
] as const;

const GREEN = "color-mix(in oklch, var(--color-success) 65%, var(--color-text))";

export function Dashboard() {
  return (
    <>
      <header className="admin-page__header dash-head">
        <div>
          <h1 id="main" className="admin-page__title">
            대시보드
          </h1>
          <p className="admin-page__lede">래미안 한강 1단지 · 최근 30일 기준</p>
        </div>
        <select aria-label="기간" className="dash-period">
          <option>최근 30일</option>
          <option>최근 7일</option>
          <option>이번 달</option>
        </select>
      </header>

      <main className="admin-page__main dash-main">
        <div className="dash-kpis">
          {KPIS.map((k) => (
            <div key={k.label} className="surface-card dash-kpi">
              <div className="dash-kpi__label">{k.label}</div>
              <div className="dash-kpi__value">{k.value}</div>
              <div className="dash-kpi__delta" style={{ color: k.good ? GREEN : "var(--color-danger)" }}>
                <span aria-hidden="true">{k.up ? "▲" : "▼"}</span>
                {k.delta}
                <span className="dash-kpi__vs">vs 전월</span>
              </div>
            </div>
          ))}
        </div>

        <div className="dash-charts">
          <section className="surface-card">
            <div className="dash-card__head">
              <h2 className="dash-card__title">일별 질의량 · 자동해결</h2>
              <div className="dash-legend">
                <span>
                  <span className="dash-legend__sw dash-legend__sw--total" aria-hidden="true" />총 질의
                </span>
                <span>
                  <span className="dash-legend__sw dash-legend__sw--solved" aria-hidden="true" />AI 자동해결
                </span>
              </div>
            </div>
            <div className="dash-chart__scroll">
              <div
                className="dash-bars"
                role="img"
                aria-label="일별 질의량과 AI 자동해결 추이 막대그래프"
              >
                {DAILY.map((d) => (
                  <div key={d.day} className="dash-bar">
                    <div className="dash-bar__col">
                      <div
                        className="dash-bar__total"
                        style={{ height: `${Math.round((d.total / DAILY_MAX) * 100)}%` }}
                      >
                        <div
                          className="dash-bar__solved"
                          style={{ height: `${Math.round((d.solved / d.total) * 100)}%` }}
                        />
                      </div>
                    </div>
                    <span className="dash-bar__label">{d.day % 2 === 1 ? d.day : ""}</span>
                  </div>
                ))}
              </div>
            </div>
          </section>

          <section className="surface-card">
            <h2 className="dash-card__title dash-card__title--mb">민원 현황</h2>
            <div className="dash-complaints">
              {COMPLAINTS.map((c) => (
                <div key={c.label}>
                  <div className="dash-complaint__top">
                    <span className="dash-complaint__label">
                      <span className="dash-complaint__dot" style={{ background: c.color }} aria-hidden="true" />
                      {c.label}
                    </span>
                    <span className="dash-complaint__count">{c.count}</span>
                  </div>
                  <div className="dash-complaint__track">
                    <span style={{ width: c.pct, background: c.color }} />
                  </div>
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="dash-bottom">
          <section className="surface-card">
            <div className="dash-card__head">
              <h2 className="dash-card__title">검수 대기 답변</h2>
              <Link href="/review-queue" className="dash-link">
                검수 큐 →
              </Link>
            </div>
            <div className="dash-review__big">
              <span className="dash-review__count">7건</span>
              <span className="dash-review__sub">신뢰도 낮음 · 검토 필요</span>
            </div>
            <ul className="dash-review__list">
              <li>
                <span className="dash-review__q">전기차 충전 요금 단가 문의</span>
                <span className="dash-review__score" style={{ color: "var(--color-danger)" }}>
                  34
                </span>
              </li>
              <li>
                <span className="dash-review__q">관리비 카드 자동납부 신청</span>
                <span
                  className="dash-review__score"
                  style={{ color: "color-mix(in oklch, var(--color-warning) 50%, var(--color-text))" }}
                >
                  62
                </span>
              </li>
            </ul>
          </section>

          <section className="surface-card">
            <div className="dash-card__head">
              <h2 className="dash-card__title">질의당 토큰 비용</h2>
              <span className="dash-card__meta">최근 30일</span>
            </div>
            <div className="dash-token__big">
              <span className="dash-token__value">₩11.4</span>
              <span className="dash-token__unit">/ 질의 평균</span>
            </div>
            <div className="dash-token__delta">
              <span aria-hidden="true">▼</span> 8% 절감
              <span className="dash-token__note">캐시 적중률 상승</span>
            </div>
            <div className="dash-token__total">
              <span>월 누적 비용</span>
              <span className="dash-token__amount">₩142,800</span>
            </div>
          </section>
        </div>
      </main>
    </>
  );
}
