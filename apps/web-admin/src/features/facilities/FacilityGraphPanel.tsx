"use client";

import { useEffect, useState } from "react";
import { EmptyState, Skeleton } from "@liviq/ui";
import {
  ApiError,
  getFacility,
  listAdminInquiries,
  type FacilityDetail,
  type Inquiry,
} from "@/lib/api";
import { STATUS_META as INQUIRY_STATUS_META } from "@/features/inquiry-admin/data";
import { STATUS_META, shortDate } from "./data";
import { HistorySection } from "./FacilityHistory";
import { estimatedInquiries, type EstimatedInquiries } from "./graph-data";

// 그래프 노드 클릭 → 시설 상세. 데이터는 목록 뷰와 같은 GET /admin/facilities/{id} 를 재사용한다
// (그래프는 읽기 전용 소비자 — ADR-0022 결정 1). 상태 변경·기록은 목록 뷰 다이얼로그가 담당.

interface FacilityGraphPanelProps {
  facilityId: string | null;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function FacilityGraphPanel({ facilityId }: FacilityGraphPanelProps) {
  const [detail, setDetail] = useState<FacilityDetail | null>(null);
  const [inquiries, setInquiries] = useState<Inquiry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!facilityId) {
      setDetail(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    void getFacility(facilityId)
      .then((item) => {
        if (alive) setDetail(item);
      })
      .catch((err: unknown) => {
        if (alive) setError(errorMessage(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [facilityId]);

  // 민원은 위치 추정 표시용 보조 데이터 — 실패해도 패널 본문을 막지 않는다(1회 조회).
  useEffect(() => {
    let alive = true;
    void listAdminInquiries()
      .then((items) => {
        if (alive) setInquiries(items);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  if (!facilityId) {
    return (
      <aside className="fac-graph__panel">
        <EmptyState
          icon="🕸"
          title="노드를 선택하세요"
          description="그래프에서 설비·장애·정비 노드를 클릭하면 해당 설비의 현황과 이력이 표시됩니다."
        />
      </aside>
    );
  }

  if (error) {
    return (
      <aside className="fac-graph__panel">
        <EmptyState icon="⚠" title="시설 정보를 불러오지 못했습니다" description={error} />
      </aside>
    );
  }

  if (!detail) {
    return (
      <aside className="fac-graph__panel">
        <Skeleton height="6rem" />
        <Skeleton height="10rem" />
      </aside>
    );
  }

  const meta = STATUS_META[detail.status];
  const estimated = estimatedInquiries(inquiries, detail.location);

  return (
    <aside className="fac-graph__panel" aria-busy={loading || undefined}>
      <div>
        <div className="fac-detail__head">
          <span className="fac-detail__icon" data-status={meta.css} aria-hidden="true">
            {meta.icon}
          </span>
          <div>
            <div className="fac-detail__name">{detail.name}</div>
            <span className={`fac-pill fac-pill--${meta.css}`}>
              <span className={`fac-dot fac-dot--${meta.css}`} aria-hidden="true" />
              {meta.label}
            </span>
          </div>
        </div>
        <p className="fac-detail__desc">
          {detail.type ? `${detail.type} · ` : "미분류 · "}
          {detail.location ?? "위치 미지정"} · 다음 점검 {shortDate(detail.nextCheckAt)}
        </p>
      </div>

      <HistorySection
        title="장애 이력"
        empty="기록된 장애가 없습니다."
        items={detail.incidents.map((i) => ({
          id: i.id,
          date: shortDate(i.occurredAt),
          primary: i.symptom,
          secondary: i.resolution ? `조치: ${i.resolution}` : null,
        }))}
      />
      <HistorySection
        title="정비 이력"
        empty="기록된 정비가 없습니다."
        items={detail.maintenanceLogs.map((m) => ({
          id: m.id,
          date: shortDate(m.performedAt),
          primary: m.work,
          secondary: m.performer ? `작업자: ${m.performer}` : null,
        }))}
      />

      <RelatedInquiries estimated={estimated} />
    </aside>
  );
}

/** 관련 민원 — 아직 정식 연결이 없어(H13-2) 위치 문자열 매칭 '추정'만 보여준다. */
function RelatedInquiries({ estimated }: { estimated: EstimatedInquiries }) {
  const { token, items } = estimated;

  return (
    <section className="fac-history">
      <div className="fac-history__title">
        관련 민원 <span className="fac-estimate">추정</span>
      </div>
      {token === null ? (
        <p className="fac-history__empty">
          설비 위치에 동 표기가 없어 관련 민원을 추정하지 않습니다.
        </p>
      ) : items.length === 0 ? (
        <p className="fac-history__empty">‘{token}’에 해당하는 미종결 민원이 없습니다.</p>
      ) : (
        <ol className="fac-history__list">
          {items.map((inquiry) => (
            <li key={inquiry.id} className="fac-history__item">
              <span className="fac-history__date">
                {INQUIRY_STATUS_META[inquiry.status].label}
              </span>
              <div className="fac-history__body">
                <div className="fac-history__primary">{inquiry.title}</div>
              </div>
            </li>
          ))}
        </ol>
      )}
      <p className="fac-estimate__note">
        근거: 위치 문자열 매칭{token ? ` (‘${token}’)` : ""}. 담당자가 확인하기 전까지 확정된
        연결이 아닙니다.
      </p>
    </section>
  );
}
