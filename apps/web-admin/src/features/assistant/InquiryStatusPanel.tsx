"use client";

// AI 비서 우측 패널 — 상태 요약 + 최근 민원 목록(ADR-0028 맥락: 민원 관리 화면 임베드 아님).
// 마운트 1회 조회, 폴링 없음. 실패해도 왼쪽 채팅은 그대로 쓸 수 있어야 한다.
// 상태 카드를 누르면 같은 패널 안에서 그 상태의 목록으로 드릴다운한다(H20-13).

import Link from "next/link";
import { Button, Skeleton, StatusPill } from "@liviq/ui";
import { useCallback, useEffect, useState } from "react";

import { listAdminInquiries, type Inquiry, type InquiryStatus } from "@/lib/api";
import { STATUS_META, countByStatus } from "@/features/inquiry-admin/data";
import { InquiryDrilldown } from "./InquiryDrilldown";
import { errorMessage, pillKind, recentInquiries, relativeDay, statusRows } from "./panel-data";

const RECENT_LIMIT = 5;
const DRILL_SECTION_ID = "adm-drill-section";

export function InquiryStatusPanel() {
  const [inquiries, setInquiries] = useState<readonly Inquiry[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      setInquiries(await listAdminInquiries());
    } catch (err) {
      setInquiries(null);
      setLoadError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <aside className="adm-panel" aria-labelledby="adm-panel-title">
      <div className="adm-panel__head">
        <h2 id="adm-panel-title" className="adm-panel__title">
          민원 현황
        </h2>
        <Link href="/inquiry-status" className="adm-panel__more">
          민원현황 보기
        </Link>
      </div>

      {loadError ? (
        <div className="adm-panel__error" role="status">
          <p className="adm-panel__note">{loadError}</p>
          <Button size="sm" variant="secondary" onClick={() => void load()}>
            다시 시도
          </Button>
        </div>
      ) : inquiries === null ? (
        <PanelSkeleton />
      ) : (
        <PanelBody inquiries={inquiries} />
      )}

      <Link href="/inquiries" className="btn btn--secondary btn--sm adm-panel__cta">
        민원 관리 열기
      </Link>
    </aside>
  );
}

function PanelSkeleton() {
  return (
    <>
      <Skeleton height="5rem" />
      <Skeleton height="9rem" />
    </>
  );
}

function PanelBody({ inquiries }: { inquiries: readonly Inquiry[] }) {
  // 드릴다운으로 펼친 상태 — null 이면 기본 화면(최근 민원).
  const [openStatus, setOpenStatus] = useState<InquiryStatus | null>(null);
  const rows = statusRows(countByStatus(inquiries));
  const now = new Date();

  return (
    <>
      <ul className="adm-counts">
        {rows.map((row) => {
          const open = openStatus === row.status;
          return (
            <li key={row.status}>
              <button
                type="button"
                className="adm-count"
                data-alert={row.alert || undefined}
                aria-pressed={open}
                aria-controls={DRILL_SECTION_ID}
                onClick={() => setOpenStatus(open ? null : row.status)}
              >
                <span className="adm-count__label">{row.label}</span>
                <span className="adm-count__value">{row.count}</span>
              </button>
            </li>
          );
        })}
      </ul>

      {openStatus ? (
        <section id={DRILL_SECTION_ID} aria-labelledby="adm-drill-title">
          <div className="adm-panel__head">
            <h3 id="adm-drill-title" className="adm-panel__subtitle">
              {STATUS_META[openStatus].label} 민원
            </h3>
            <button type="button" className="adm-panel__more" onClick={() => setOpenStatus(null)}>
              닫기
            </button>
          </div>
          <InquiryDrilldown inquiries={inquiries} status={openStatus} now={now} />
        </section>
      ) : (
        <section aria-labelledby="adm-recent-title">
          <h3 id="adm-recent-title" className="adm-panel__subtitle">
            최근 민원
          </h3>
          {inquiries.length === 0 ? (
            <p className="adm-panel__note">접수된 민원이 없습니다.</p>
          ) : (
            <ul className="adm-recent">
              {recentInquiries(inquiries, RECENT_LIMIT).map((item) => (
                <li key={item.id} className="adm-recent__item">
                  <span className="adm-recent__title">{item.title}</span>
                  <span className="adm-recent__meta">
                    <StatusPill
                      status={pillKind(item.status)}
                      label={STATUS_META[item.status].label}
                    />
                    <span className="adm-recent__date">{relativeDay(item.createdAt, now)}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </>
  );
}
