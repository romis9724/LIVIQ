"use client";

import {
  Button,
  EmptyState,
  FilterChips,
  Skeleton,
  StatCard,
  StatGrid,
  StatusPill,
  type StatTone,
} from "@liviq/ui";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

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
} from "./data";
import "./inquiry-status.css";

const PERIODS = [
  { id: "7", label: "최근 7일" },
  { id: "30", label: "최근 30일" },
] as const;

type PeriodId = (typeof PERIODS)[number]["id"];

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function InquiryStatus() {
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
          민원현황
        </h1>
      </header>

      <main className="admin-page__main dash-main">
        {/* 기간 칩은 '오늘 할 일' 제목 줄 오른쪽에 붙인다 — 툴바 한 줄을 없애 세로 공간 절약. */}
        {loading ? (
          <InquiryStatusSkeleton />
        ) : loadError ? (
          <EmptyState
            icon="⚠"
            title="민원현황을 불러오지 못했습니다"
            description={loadError}
            action={<Button onClick={() => void load(Number(period))}>다시 시도</Button>}
          />
        ) : stats ? (
          <InquiryStatusContent
            stats={stats}
            periodChips={
              <FilterChips items={PERIODS} value={period} onChange={setPeriod} label="기간" />
            }
          />
        ) : null}
      </main>
    </>
  );
}

function InquiryStatusSkeleton() {
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

function ActionQueue({
  actions,
  periodChips,
}: {
  actions: DashboardActionQueue;
  periodChips: ReactNode;
}) {
  return (
    <section aria-labelledby="dash-actions-title">
      <div className="dash-section__head">
        <h2 id="dash-actions-title" className="dash-section__title dash-section__title--flush">
          오늘 할 일
        </h2>
        {periodChips}
      </div>
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

function InquiryStatusContent({
  stats,
  periodChips,
}: {
  stats: DashboardStats;
  periodChips: ReactNode;
}) {
  const { actions, budget, inquiries, facilities } = stats;

  return (
    <>
      <ActionQueue actions={actions} periodChips={periodChips} />

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

      {/* AI 도우미 현황(질의 수·답변률·폴백률·평균 토큰·캐시)은 H20-2에서 삭제 —
          대체 노출 없음(ADR-0028 결정 1). 서버 stats 응답의 ai·cache 필드는 그대로라
          다시 필요해지면 화면만 붙이면 된다. 토큰 예산은 AI 통계가 아니라 비용 가드(규칙 7)라 유지. */}
      {budget.enabled ? <TokenBudget budget={budget} /> : null}
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
