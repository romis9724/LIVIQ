"use client";

import { Button, EmptyState, Skeleton } from "@liviq/ui";
import { useCallback, useEffect, useState } from "react";

import { ApiError, getDashboardStats, type DashboardStats } from "@/lib/api";
import {
  FACILITY_STATUS_META,
  INQUIRY_STATUS_META,
  barWidth,
  formatCount,
  formatPercent,
  formatTokens,
} from "./data";
import "./dashboard.css";

const PERIODS = [
  { days: 7, label: "최근 7일" },
  { days: 30, label: "최근 30일" },
] as const;

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function Dashboard() {
  const [days, setDays] = useState<number>(7);
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async (period: number) => {
    setLoading(true);
    try {
      setStats(await getDashboardStats(period));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(days);
  }, [days, load]);

  return (
    <>
      <header className="admin-page__header dash-head">
        <div>
          <h1 id="main" className="admin-page__title">
            대시보드
          </h1>
          <p className="admin-page__lede">
            래미안 한강 1단지 · 최근 {days}일 기준 운영 지표
          </p>
        </div>
        <select
          aria-label="기간"
          className="dash-period"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          {PERIODS.map((p) => (
            <option key={p.days} value={p.days}>
              {p.label}
            </option>
          ))}
        </select>
      </header>

      <main className="admin-page__main dash-main">
        {loading ? (
          <DashboardSkeleton />
        ) : loadError ? (
          <EmptyState
            icon="⚠"
            title="대시보드를 불러오지 못했습니다"
            description={loadError}
            action={<Button onClick={() => void load(days)}>다시 시도</Button>}
          />
        ) : stats ? (
          <DashboardContent stats={stats} />
        ) : null}
      </main>
    </>
  );
}

function DashboardSkeleton() {
  return (
    <>
      <div className="dash-kpis">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} height="6rem" />
        ))}
      </div>
      <div className="dash-charts">
        <Skeleton height="14rem" />
        <Skeleton height="14rem" />
      </div>
    </>
  );
}

interface Kpi {
  label: string;
  value: string;
}

function DashboardContent({ stats }: { stats: DashboardStats }) {
  const { ai, cache, inquiries, facilities } = stats;
  const kpis: readonly Kpi[] = [
    { label: "AI 질의 수", value: formatCount(ai.queryCount) },
    { label: "답변률", value: formatPercent(ai.answerRate) },
    { label: "폴백률", value: formatPercent(ai.fallbackRate) },
    { label: "검수 필요율", value: formatPercent(ai.needsReviewRate) },
  ];

  return (
    <>
      <div className="dash-kpis">
        {kpis.map((k) => (
          <div key={k.label} className="surface-card dash-kpi">
            <div className="dash-kpi__label">{k.label}</div>
            <div className="dash-kpi__value">{k.value}</div>
          </div>
        ))}
      </div>

      <div className="dash-charts">
        <StatusDistribution
          title="민원 현황"
          meta={INQUIRY_STATUS_META}
          counts={inquiries}
          emptyLabel="기간 내 접수된 민원이 없습니다."
        />
        <StatusDistribution
          title="시설 상태"
          meta={FACILITY_STATUS_META}
          counts={facilities}
          emptyLabel="등록된 시설이 없습니다."
        />
      </div>

      <div className="dash-bottom">
        <section className="surface-card">
          <div className="dash-card__head">
            <h2 className="dash-card__title">질의당 평균 토큰</h2>
            <span className="dash-card__meta">입력 / 출력</span>
          </div>
          <div className="dash-token__big">
            <span className="dash-token__value">{formatTokens(ai.avgTokenInput)}</span>
            <span className="dash-token__unit">입력</span>
          </div>
          <div className="dash-token__big">
            <span className="dash-token__value">{formatTokens(ai.avgTokenOutput)}</span>
            <span className="dash-token__unit">출력</span>
          </div>
        </section>

        <section className="surface-card">
          <div className="dash-card__head">
            <h2 className="dash-card__title">캐시 적중률</h2>
            <span className="dash-card__meta">
              적중 {formatCount(cache.hits)} · 미스 {formatCount(cache.misses)}
            </span>
          </div>
          <div className="dash-token__big">
            <span className="dash-token__value">{formatPercent(cache.hitRate)}</span>
            <span className="dash-token__unit">LLM 호출 절감</span>
          </div>
        </section>
      </div>
    </>
  );
}

interface StatusDistributionProps {
  title: string;
  meta: readonly { key: string; label: string; color: string }[];
  counts: Record<string, number>;
  emptyLabel: string;
}

function StatusDistribution({ title, meta, counts, emptyLabel }: StatusDistributionProps) {
  const values = meta.map((m) => counts[m.key] ?? 0);
  const total = values.reduce((sum, n) => sum + n, 0);

  return (
    <section className="surface-card">
      <h2 className="dash-card__title dash-card__title--mb">{title}</h2>
      {total === 0 ? (
        <p className="dash-complaint__label">{emptyLabel}</p>
      ) : (
        <div className="dash-complaints">
          {meta.map((m) => {
            const count = counts[m.key] ?? 0;
            return (
              <div key={m.key}>
                <div className="dash-complaint__top">
                  <span className="dash-complaint__label">
                    <span
                      className="dash-complaint__dot"
                      style={{ background: m.color }}
                      aria-hidden="true"
                    />
                    {m.label}
                  </span>
                  <span className="dash-complaint__count">{formatCount(count)}</span>
                </div>
                <div className="dash-complaint__track">
                  <span style={{ width: barWidth(count, values), background: m.color }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
