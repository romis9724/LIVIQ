"use client";

import {
  Button,
  EmptyState,
  FilterChips,
  PageToolbar,
  Skeleton,
  StatCard,
  StatGrid,
  StatusPill,
  type StatTone,
} from "@liviq/ui";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  getDashboardStats,
  type DashboardActionQueue,
  type DashboardStats,
} from "@/lib/api";
import {
  FACILITY_STATUS_META,
  INQUIRY_STATUS_META,
  barWidth,
  budgetWidth,
  formatCount,
  formatPercent,
  formatTokens,
} from "./data";
import "./dashboard.css";

const PERIODS = [
  { id: "7", label: "최근 7일" },
  { id: "30", label: "최근 30일" },
] as const;

type PeriodId = (typeof PERIODS)[number]["id"];

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function Dashboard() {
  const [period, setPeriod] = useState<PeriodId>("7");
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async (days: number) => {
    setLoading(true);
    try {
      setStats(await getDashboardStats(days));
      setLoadError(null);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(Number(period));
  }, [period, load]);

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          대시보드
        </h1>
      </header>

      <main className="admin-page__main dash-main">
        <PageToolbar
          end={<FilterChips items={PERIODS} value={period} onChange={setPeriod} label="기간" />}
        />

        {loading ? (
          <DashboardSkeleton />
        ) : loadError ? (
          <EmptyState
            icon="⚠"
            title="대시보드를 불러오지 못했습니다"
            description={loadError}
            action={<Button onClick={() => void load(Number(period))}>다시 시도</Button>}
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
      <StatGrid>
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} height="5.5rem" />
        ))}
      </StatGrid>
      <div className="dash-charts">
        <Skeleton height="14rem" />
        <Skeleton height="14rem" />
      </div>
      <Skeleton height="10rem" />
    </>
  );
}

interface ActionItem {
  key: keyof DashboardActionQueue;
  label: string;
  href: string;
  /** 0이 아닐 때만 값 색으로 경고(docs/05 §5A — 강조는 값 색만). 미지정이면 기본색. */
  alertTone?: StatTone;
}

// 오늘 할 일 — open 카운트 → 담당 화면 딥링크(각 카드 클릭 이동).
const ACTION_ITEMS: readonly ActionItem[] = [
  { key: "approvalsPending", label: "가입 승인 대기", href: "/residents", alertTone: "warning" },
  { key: "inquiriesUnassigned", label: "미배정 민원", href: "/inquiries", alertTone: "danger" },
  { key: "inquiriesInProgress", label: "처리중 민원", href: "/inquiries" },
  { key: "noticesDraft", label: "임시저장 공지", href: "/notices" },
  { key: "noticesScheduled", label: "예약 발행 예정", href: "/notices" },
];

function ActionQueue({ actions }: { actions: DashboardActionQueue }) {
  return (
    <section aria-labelledby="dash-actions-title">
      <h2 id="dash-actions-title" className="dash-section__title">
        오늘 할 일
      </h2>
      <StatGrid>
        {ACTION_ITEMS.map((item) => {
          const count = actions[item.key];
          return (
            <Link key={item.key} href={item.href} className="dash-link">
              <StatCard
                label={item.label}
                value={formatCount(count)}
                unit="건"
                tone={count > 0 ? item.alertTone : undefined}
              />
            </Link>
          );
        })}
      </StatGrid>
    </section>
  );
}

function DashboardContent({ stats }: { stats: DashboardStats }) {
  const { actions, ai, cache, budget, inquiries, facilities } = stats;

  return (
    <>
      <ActionQueue actions={actions} />

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

      <section aria-labelledby="dash-ai-title" className="dash-ai">
        <h2 id="dash-ai-title" className="dash-section__title dash-section__title--flush">
          AI 도우미 현황
        </h2>

        <StatGrid>
          <StatCard label="AI 질의 수" value={formatCount(ai.queryCount)} unit="건" />
          <StatCard label="답변률" value={formatPercent(ai.answerRate)} />
          <StatCard label="폴백률" value={formatPercent(ai.fallbackRate)} />
          <StatCard label="질의당 평균 입력" value={formatTokens(ai.avgTokenInput)} unit="토큰" />
          <StatCard label="질의당 평균 출력" value={formatTokens(ai.avgTokenOutput)} unit="토큰" />
          <StatCard label="캐시 적중률" value={formatPercent(cache.hitRate)} />
        </StatGrid>

        <p className="dash-note">
          캐시 적중 {formatCount(cache.hits)}건 · 미스 {formatCount(cache.misses)}건 — 적중한 질의는
          LLM 호출 없이 답변합니다.
        </p>

        {budget.enabled ? <TokenBudget budget={budget} /> : null}
      </section>
    </>
  );
}

function TokenBudget({ budget }: { budget: DashboardStats["budget"] }) {
  return (
    <section
      className={`surface-card${budget.exceeded ? " dash-budget--over" : ""}`}
      aria-labelledby="dash-budget-title"
    >
      <div className="dash-card__head">
        <h3 id="dash-budget-title" className="dash-card__title">
          일일 토큰 예산
        </h3>
        {budget.exceeded ? (
          <StatusPill status="fault" label="예산 초과" />
        ) : (
          <span className="dash-card__meta">경고 기준 — 질의 차단 없음</span>
        )}
      </div>
      <p className="dash-budget__value">
        {formatCount(budget.usedToday)}
        <span className="dash-budget__unit">/ {formatCount(budget.budget)} 토큰 (오늘)</span>
      </p>
      <div className="dash-track">
        <span
          className="dash-budget__fill"
          style={{ width: budgetWidth(budget.usedToday, budget.budget) }}
        />
      </div>
    </section>
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
      <h2 className="dash-section__title">{title}</h2>
      {total === 0 ? (
        <p className="dash-note">{emptyLabel}</p>
      ) : (
        <div className="dash-bars">
          {meta.map((m) => {
            const count = counts[m.key] ?? 0;
            return (
              <div key={m.key}>
                <div className="dash-bar__top">
                  <span className="dash-bar__label">
                    <span
                      className="dash-bar__dot"
                      style={{ background: m.color }}
                      aria-hidden="true"
                    />
                    {m.label}
                  </span>
                  <span className="dash-bar__count">{formatCount(count)}</span>
                </div>
                <div className="dash-track">
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
