"use client";

import { useState } from "react";
import "./fees.css";

interface Bar {
  month: string;
  value: number;
  current?: boolean;
}

const BARS: readonly Bar[] = [
  { month: "1월", value: 195 },
  { month: "2월", value: 221 },
  { month: "3월", value: 208 },
  { month: "4월", value: 199 },
  { month: "5월", value: 213 },
  { month: "6월", value: 238, current: true },
];
const BAR_MAX = 238;

interface FeeItem {
  name: string;
  amount: string;
  delta?: string;
}

const ITEMS: readonly FeeItem[] = [
  { name: "일반관리비", amount: "₩96,300" },
  { name: "난방비", amount: "₩52,400", delta: "▲ ₩18,200" },
  { name: "급탕비", amount: "₩21,700" },
  { name: "전기료(공용)", amount: "₩34,800" },
  { name: "수도료", amount: "₩18,200" },
  { name: "승강기 유지비", amount: "₩9,000" },
  { name: "기타(청소·경비)", amount: "₩6,000" },
];

export function FeesView() {
  const [explain, setExplain] = useState(true);

  return (
    <div className="fees">
      <header className="fees__header">
        <h1 id="main" className="fees__title">
          관리비
        </h1>
      </header>

      <main className="fees__main">
        <section className="surface-card">
          <div className="fees-month__top">
            <span className="fees-month__label">이번 달 · 2026년 6월</span>
            <span className="fees-month__delta">
              <span aria-hidden="true">▲</span> 전월 대비 12%
            </span>
          </div>
          <div className="fees-month__amount">₩238,400</div>
          <div className="fees-month__due">납부 기한 6/30 · 자동납부 등록됨</div>
          <button
            type="button"
            className="fees-explain-toggle"
            aria-expanded={explain}
            onClick={() => setExplain((v) => !v)}
          >
            <span aria-hidden="true">💬</span> 왜 올랐나요? AI에게 묻기
          </button>
        </section>

        {explain ? (
          <section className="fees-explain" aria-live="polite">
            <div className="fees-explain__head">
              <span className="fees-explain__mark" aria-hidden="true">
                L
              </span>
              <span className="fees-explain__label">AI 설명</span>
            </div>
            <p className="fees-explain__text">
              이번 달은 전월 대비 <strong>12% 높습니다.</strong> 난방비가 <strong>₩18,200</strong>{" "}
              늘어난 것이 주된 영향으로 보입니다. 6월 초 난방 사용량이 평소보다 많았던 점이 반영된
              것으로 추정됩니다.
            </p>
            <div className="fees-explain__basis">
              <span aria-hidden="true">🔎</span> 기준: <strong>2026-05 확정 관리비 데이터(업로드)</strong>. AI는
              확정 금액을 조회·설명만 하며 직접 계산하지 않습니다. 정확한 산출 내역은 관리사무소에서
              확인할 수 있습니다.
            </div>
          </section>
        ) : null}

        <section className="surface-card">
          <div className="fees-section__title">최근 6개월 추이</div>
          <div className="fees-chart__scroll">
            <div
              className="fees-chart"
              role="img"
              aria-label="최근 6개월 관리비 추이 막대그래프. 1월 19만5천원부터 점진 변동하여 6월 23만8천원."
            >
              {BARS.map((b) => (
                <div key={b.month} className="fees-bar">
                  <span className="fees-bar__value">₩{b.value}k</span>
                  <div
                    className="fees-bar__fill"
                    data-current={b.current || undefined}
                    style={{ height: `${Math.round((b.value / BAR_MAX) * 100)}%` }}
                  />
                  <span className="fees-bar__month" data-current={b.current || undefined}>
                    {b.month}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="surface-card">
          <div className="fees-section__title">항목별 내역</div>
          <ul className="fees-breakdown">
            {ITEMS.map((it) => (
              <li key={it.name} className="fees-breakdown__row">
                <span className="fees-breakdown__name">{it.name}</span>
                {it.delta ? <span className="fees-breakdown__delta">{it.delta}</span> : null}
                <span className="fees-breakdown__amount">{it.amount}</span>
              </li>
            ))}
            <li className="fees-breakdown__row fees-breakdown__row--total">
              <span className="fees-breakdown__name">합계</span>
              <span className="fees-breakdown__total">₩238,400</span>
            </li>
          </ul>
        </section>
      </main>
    </div>
  );
}
