"use client";

import { Button, EmptyState, Skeleton, StatusPill } from "@liviq/ui";
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
        <div className="dash-period" role="group" aria-label="기간">
          {PERIODS.map((p) => (
            <button
              key={p.days}
              type="button"
              className={`dash-period__btn${days === p.days ? " dash-period__btn--active" : ""}`}
              aria-pressed={days === p.days}
              onClick={() => setDays(p.days)}
            >
              {p.label}
            </button>
          ))}
        </div>
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
      <div className="dash-actions">
        {[0, 1, 2, 3, 4].map((i) => (
          <Skeleton key={i} height="8.5rem" />
        ))}
      </div>
      <div className="dash-charts">
        <Skeleton height="14rem" />
        <Skeleton height="14rem" />
      </div>
      <Skeleton height="16rem" />
    </>
  );
}

interface Kpi {
  label: string;
  value: string;
}

// tone — 카드별 의미색(관리자 팔레트 토큰). 도메인·긴급도에 맞춰 배정.
type ActionTone = "accent" | "warning" | "success" | "neutral";

interface ActionItem {
  key: keyof DashboardActionQueue;
  label: string;
  href: string;
  icon: string;
  tone: ActionTone;
}

// 오늘 할 일 — open 카운트 → 담당 화면 딥링크(각 카드 클릭 이동).
// icon은 사이드바 내비(roles.ts)와 동일 이모지를 재사용해 화면 간 일관성 유지.
const ACTION_ITEMS: readonly ActionItem[] = [
  { key: "approvalsPending", label: "가입 승인 대기", href: "/residents", icon: "🙋", tone: "accent" },
  { key: "inquiriesUnassigned", label: "미배정 민원", href: "/inquiries", icon: "🛠", tone: "warning" },
  { key: "inquiriesInProgress", label: "처리중 민원", href: "/inquiries", icon: "🛠", tone: "accent" },
  { key: "noticesDraft", label: "임시저장 공지", href: "/notices", icon: "📝", tone: "neutral" },
  { key: "noticesScheduled", label: "예약 발행 예정", href: "/notices", icon: "📢", tone: "success" },
];

function ActionQueue({ actions }: { actions: DashboardActionQueue }) {
  return (
    <section aria-labelledby="dash-actions-title">
      <h2 id="dash-actions-title" className="dash-section__title dash-section__title--hero">
        오늘 할 일
      </h2>
      <div className="dash-actions">
        {ACTION_ITEMS.map((item) => {
          const count = actions[item.key];
          const isEmpty = count === 0;
          return (
            <Link
              key={item.key}
              href={item.href}
              className={`surface-card dash-action dash-action--${item.tone}${isEmpty ? " dash-action--empty" : ""}`}
            >
              <span className="dash-action__head">
                <span className="dash-action__label">
                  <span className="dash-action__icon" aria-hidden="true">
                    {item.icon}
                  </span>
                  {item.label}
                </span>
                <span className="dash-action__arrow" aria-hidden="true">
                  →
                </span>
              </span>
              <span className="dash-action__count">{formatCount(count)}</span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

function DashboardContent({ stats }: { stats: DashboardStats }) {
  const { actions, ai, cache, budget, inquiries, facilities } = stats;
  const kpis: readonly Kpi[] = [
    { label: "AI 질의 수", value: formatCount(ai.queryCount) },
    { label: "답변률", value: formatPercent(ai.answerRate) },
    { label: "폴백률", value: formatPercent(ai.fallbackRate) },
  ];

  return (
    <>
      <ActionQueue actions={actions} />

      <div className="dash-charts">
        <StatusDistribution
          title="민원 현황"
          meta={INQUIRY_STATUS_META}
          counts={inquiries}
          emptyLabel="기간 내 접수된 민원이 없습니다."
          tone="accent"
        />
        <StatusDistribution
          title="시설 상태"
          meta={FACILITY_STATUS_META}
          counts={facilities}
          emptyLabel="등록된 시설이 없습니다."
          tone="success"
        />
      </div>

      <section aria-labelledby="dash-ai-title" className="dash-ai">
        <h2 id="dash-ai-title" className="dash-section__title dash-section__title--muted">
          AI 도우미 현황
        </h2>

        <div className="dash-kpis dash-kpis--3">
          {kpis.map((k) => (
            <div key={k.label} className="surface-card dash-kpi dash-tcard dash-tcard--muted">
              <div className="dash-kpi__label">{k.label}</div>
              <div className="dash-kpi__value">{k.value}</div>
            </div>
          ))}
        </div>

        {budget.enabled ? (
          <section
            className={`surface-card dash-tcard dash-tcard--muted dash-budget${budget.exceeded ? " dash-budget--over" : ""}`}
          >
            <div className="dash-card__head">
              <h3 className="dash-card__title">일일 토큰 예산</h3>
              {budget.exceeded ? (
                <StatusPill status="fault" label="예산 초과" />
              ) : (
                <span className="dash-card__meta">경고 기준 — 질의 차단 없음</span>
              )}
            </div>
            <div className="dash-token__big">
              <span className="dash-token__value">{formatCount(budget.usedToday)}</span>
              <span className="dash-token__unit">
                / {formatCount(budget.budget)} 토큰 (오늘)
              </span>
            </div>
            <div className="dash-complaint__track">
              <span
                className="dash-budget__fill"
                style={{ width: budgetWidth(budget.usedToday, budget.budget) }}
              />
            </div>
          </section>
        ) : null}

        <div className="dash-bottom">
          <section className="surface-card dash-tcard dash-tcard--muted">
            <div className="dash-card__head">
              <h3 className="dash-card__title">질의당 평균 토큰</h3>
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

          <section className="surface-card dash-tcard dash-tcard--muted">
            <div className="dash-card__head">
              <h3 className="dash-card__title">캐시 적중률</h3>
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
      </section>
    </>
  );
}

interface StatusDistributionProps {
  title: string;
  meta: readonly { key: string; label: string; color: string }[];
  counts: Record<string, number>;
  emptyLabel: string;
  tone: ActionTone;
}

function StatusDistribution({ title, meta, counts, emptyLabel, tone }: StatusDistributionProps) {
  const values = meta.map((m) => counts[m.key] ?? 0);
  const total = values.reduce((sum, n) => sum + n, 0);

  return (
    <section className={`surface-card dash-tcard dash-tcard--${tone}`}>
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
