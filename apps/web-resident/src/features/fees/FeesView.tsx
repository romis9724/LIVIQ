"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, CitationCard, ConfidenceBadge, EmptyState, Skeleton } from "@liviq/ui";
import type { ConfidenceStatus } from "@liviq/ui";
import { ApiError, feeDelta, formatWon, getFees, type FeeData } from "./api";
import { useFeeExplain } from "./useFeeExplain";
import "./fees.css";

/** 이번 달(YYYY-MM). 조회 기본 월. */
function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function monthLabel(period: string): string {
  const [year, mon] = period.split("-");
  return `${year}년 ${Number(mon)}월`;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "관리비를 불러오지 못했습니다.";
}

const STAGE_HINT: Record<string, string> = {
  searching: "확정 데이터 확인 중…",
  generating: "설명 작성 중…",
  verifying: "근거 확인 중…",
};

const FALLBACK_TEXT =
  "확정 데이터만으로는 정확히 설명하기 어려워요. 자세한 산출 내역은 관리사무소에서 확인해 주세요.";

export function FeesView() {
  const [period, setPeriod] = useState<string>(currentMonth());
  const [data, setData] = useState<FeeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const { state: explain, explain: runExplain, reset: resetExplain } = useFeeExplain();

  const load = useCallback(async (target: string) => {
    setLoading(true);
    try {
      const res = await getFees(target);
      setData(res);
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    resetExplain();
    void load(period);
  }, [period, load, resetExplain]);

  const hasData = data !== null && data.total !== null;
  const delta = hasData ? feeDelta(data.total, data.prevTotal) : null;
  const items = data?.breakdown ? Object.entries(data.breakdown) : [];

  return (
    <div className="fees">
      <header className="fees__header">
        <h1 id="main" className="fees__title">
          관리비
        </h1>
        <div className="fees__month-field">
          <label htmlFor="fees-month" className="sr-only">
            조회 월
          </label>
          <input
            id="fees-month"
            type="month"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
        </div>
      </header>

      <main className="fees__main">
        {loading ? (
          <section className="surface-card">
            <Skeleton height="2.4rem" />
            <Skeleton height="1.2rem" />
          </section>
        ) : loadError ? (
          <EmptyState
            icon="⚠"
            title="관리비를 불러오지 못했습니다"
            description={loadError}
            action={<Button onClick={() => void load(period)}>다시 시도</Button>}
          />
        ) : !hasData ? (
          <EmptyState
            icon="📄"
            title="해당 월 확정 데이터 없음"
            description={`${monthLabel(period)} 관리비가 아직 확정되지 않았습니다.`}
          />
        ) : (
          <>
            <section className="surface-card">
              <div className="fees-month__top">
                <span className="fees-month__label">{monthLabel(period)}</span>
                {delta && delta.direction !== "flat" ? (
                  <span
                    className="fees-month__delta"
                    data-down={delta.direction === "down" || undefined}
                  >
                    <span aria-hidden="true">{delta.direction === "up" ? "▲" : "▼"}</span> 전월 대비{" "}
                    {formatWon(Math.abs(delta.amount))}
                  </span>
                ) : null}
              </div>
              <div className="fees-month__amount">{formatWon(data!.total!)}</div>
              <button
                type="button"
                className="fees-explain-toggle"
                onClick={() => void runExplain(period)}
                disabled={explain.streaming}
              >
                <span aria-hidden="true">💬</span>{" "}
                {explain.streaming ? "AI가 설명 중…" : "왜 이런가요? AI에게 묻기"}
              </button>
            </section>

            {explain.active ? <ExplainPanel state={explain} /> : null}

            {delta ? (
              <section className="surface-card">
                <div className="fees-section__title">전월 대비</div>
                <div className="fees-compare">
                  <CompareBar
                    label="전월"
                    amount={data!.prevTotal!}
                    max={Math.max(data!.total!, data!.prevTotal!)}
                  />
                  <CompareBar
                    label={monthLabel(period).split(" ")[1] ?? "이번 달"}
                    amount={data!.total!}
                    max={Math.max(data!.total!, data!.prevTotal!)}
                    current
                  />
                </div>
                {/* ponytail: 추이 API는 수요 확인 후 — 현재는 전월·이번달 2개월 비교만 */}
              </section>
            ) : null}

            <section className="surface-card">
              <div className="fees-section__title">항목별 내역</div>
              <ul className="fees-breakdown">
                {items.map(([name, amount]) => (
                  <li key={name} className="fees-breakdown__row">
                    <span className="fees-breakdown__name">{name}</span>
                    <span className="fees-breakdown__amount">{formatWon(amount)}</span>
                  </li>
                ))}
                <li className="fees-breakdown__row fees-breakdown__row--total">
                  <span className="fees-breakdown__name">합계</span>
                  <span className="fees-breakdown__total">{formatWon(data!.total!)}</span>
                </li>
              </ul>
            </section>
          </>
        )}
      </main>
    </div>
  );
}

function CompareBar({
  label,
  amount,
  max,
  current,
}: {
  label: string;
  amount: number;
  max: number;
  current?: boolean;
}) {
  const height = max > 0 ? Math.max(8, Math.round((amount / max) * 100)) : 8;
  return (
    <div className="fees-bar">
      <span className="fees-bar__value">{formatWon(amount)}</span>
      <div className="fees-bar__fill" data-current={current || undefined} style={{ height: `${height}%` }} />
      <span className="fees-bar__month" data-current={current || undefined}>
        {label}
      </span>
    </div>
  );
}

function confidenceStatus(
  status: "answered" | "fallback",
  needsReview: boolean,
): ConfidenceStatus {
  if (status === "fallback") return "handoff";
  return needsReview ? "review" : "answered";
}

function ExplainPanel({ state }: { state: ReturnType<typeof useFeeExplain>["state"] }) {
  const done = state.result;
  const isFallback = done?.status === "fallback" || state.error;

  return (
    <section className="fees-explain" aria-live="polite">
      <div className="fees-explain__head">
        <span className="fees-explain__mark" aria-hidden="true">
          L
        </span>
        <span className="fees-explain__label">AI 설명</span>
        {done ? (
          <ConfidenceBadge status={confidenceStatus(done.status, done.needsReview)} />
        ) : null}
      </div>

      {state.streaming && !state.text ? (
        <p className="fees-explain__text">
          <span aria-hidden="true">🔎</span> {STAGE_HINT[state.stage] ?? "처리 중…"}
        </p>
      ) : (
        <p className="fees-explain__text">
          {state.error ? FALLBACK_TEXT : state.text}
          {state.streaming ? <span className="caret" aria-hidden="true" /> : null}
        </p>
      )}

      {state.citations.map((c, i) => (
        <CitationCard key={`${c.documentTitle}-${i}`} title={c.documentTitle} meta={c.quote} href="#" />
      ))}

      {done && isFallback ? (
        <div className="fees-explain__basis">
          <span aria-hidden="true">☎</span> 정확한 산출 내역은 관리사무소에서 확인해 주세요.
        </div>
      ) : (
        <div className="fees-explain__basis">
          <span aria-hidden="true">🔎</span> AI는 <strong>확정 관리비 데이터</strong>를 조회·설명만 하며
          직접 계산하지 않습니다.
        </div>
      )}
    </section>
  );
}
