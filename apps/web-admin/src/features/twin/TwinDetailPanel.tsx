"use client";

import { useCallback, useEffect, useState } from "react";
import { Button, EmptyState, Skeleton } from "@liviq/ui";
import {
  ApiError,
  getTwinHouseholdDetail,
  type TwinHouseholdDetail,
  type TwinOpenInquiry,
} from "@/lib/api";
import { formatWon } from "@/features/fee-upload/logic";

// 표시용 라벨 — 서버 코드값이 아니면 원문을 그대로 노출(폴백).
const ROLE_LABELS: Record<string, string> = {
  RESIDENT: "입주민",
  MANAGER: "관리소장",
  STAFF: "관리직원",
};
const MEMBER_STATUS_LABELS: Record<string, string> = {
  active: "거주중",
  pending: "가입 대기",
  pre_registered: "사전등록",
};
const INQUIRY_STATUS_LABELS: Record<string, string> = {
  received: "접수됨",
  assigned: "배정됨",
  in_progress: "처리중",
  reopened: "재접수",
};
const PRIORITY_LABELS: Record<string, string> = {
  urgent: "긴급",
  normal: "보통",
  low: "낮음",
};

function labelOf(map: Record<string, string>, key: string): string {
  return map[key] ?? key;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

/** ISO → "YYYY-MM-DD"(로케일 비의존). 잘못된 값은 원문 유지. */
function shortDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${mm}-${dd}`;
}

interface TwinDetailPanelProps {
  householdId: string;
  onClose: () => void;
  /** 평면도 보기 — 왼쪽 3D 무대 오버레이는 TwinView 가 띄운다(세대 타입을 올려보낸다). */
  onOpenFloorPlan: (unitTypeLabel: string) => void;
  /** 평면도 오버레이가 열려 있으면 Escape 는 평면도만 닫는다(상세는 유지). */
  isFloorPlanOpen: boolean;
}

type DetailState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; detail: TwinHouseholdDetail };

/** 세대 상세 우측 슬라이드오버 — 세대원(마스킹)·미종결 민원·당월 관리비. 개인정보는 마스킹만. */
export function TwinDetailPanel({
  householdId,
  onClose,
  onOpenFloorPlan,
  isFloorPlanOpen,
}: TwinDetailPanelProps) {
  const [state, setState] = useState<DetailState>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", detail: await getTwinHouseholdDetail(householdId) });
    } catch (err) {
      setState({ kind: "error", message: errorMessage(err) });
    }
  }, [householdId]);

  useEffect(() => {
    void load();
  }, [load]);

  // 열려 있는 동안 Escape 로 닫기(평면도 오버레이가 위에 있으면 그쪽이 먼저 닫힌다).
  useEffect(() => {
    if (isFloorPlanOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose, isFloorPlanOpen]);

  return (
    // 평면도가 열리면 스크림을 투명하게 — 왼쪽 3D 가 오버레이 뒤로 비쳐야 한다(닫기 클릭 영역은 유지).
    <div className="twin-detail-scrim" data-dim={!isFloorPlanOpen || undefined} onClick={onClose}>
      <aside
        className="twin-detail"
        role="dialog"
        // 평면도 오버레이가 열리면 상세는 모달이 아니다(포커스가 상세 밖 오버레이로 간다).
        aria-modal={!isFloorPlanOpen}
        aria-label="세대 상세"
        onClick={(e) => e.stopPropagation()}
      >
        <TwinDetailContent
          state={state}
          onClose={onClose}
          onRetry={() => void load()}
          onOpenFloorPlan={onOpenFloorPlan}
        />
      </aside>
    </div>
  );
}

interface TwinDetailContentProps {
  state: DetailState;
  onClose: () => void;
  onRetry: () => void;
  onOpenFloorPlan: (unitTypeLabel: string) => void;
}

function TwinDetailContent({ state, onClose, onRetry, onOpenFloorPlan }: TwinDetailContentProps) {
  const closeButton = (
    <button type="button" className="twin-detail__close" aria-label="닫기" onClick={onClose}>
      ✕
    </button>
  );

  if (state.kind === "loading") {
    return (
      <>
        <header className="twin-detail__head">
          <h2 className="twin-detail__title">세대 상세</h2>
          {closeButton}
        </header>
        <div className="twin-detail__body">
          <Skeleton height="1.5rem" />
          <Skeleton height="4rem" />
          <Skeleton height="4rem" />
        </div>
      </>
    );
  }

  if (state.kind === "error") {
    return (
      <>
        <header className="twin-detail__head">
          <h2 className="twin-detail__title">세대 상세</h2>
          {closeButton}
        </header>
        <div className="twin-detail__body">
          <EmptyState
            icon="⚠"
            title="세대 정보를 불러오지 못했습니다"
            description={state.message}
            action={
              <Button variant="secondary" onClick={onRetry}>
                다시 시도
              </Button>
            }
          />
        </div>
      </>
    );
  }

  const { detail } = state;
  return (
    <>
      <header className="twin-detail__head">
        <div>
          <h2 className="twin-detail__title">
            {detail.buildingName} {detail.unitNo}호
          </h2>
          <p className="twin-detail__sub">
            {detail.floor}층{detail.unitTypeLabel ? ` · ${detail.unitTypeLabel}` : ""}
          </p>
        </div>
        {closeButton}
      </header>

      <div className="twin-detail__body">
        <MembersSection members={detail.members} />
        <InquiriesSection inquiries={detail.openInquiries} />
        <FeeSection fee={detail.currentFee} />
        <FloorPlanSection unitTypeLabel={detail.unitTypeLabel} onOpen={onOpenFloorPlan} />
      </div>
    </>
  );
}

function MembersSection({ members }: { members: TwinHouseholdDetail["members"] }) {
  return (
    <section className="twin-detail__section">
      <h3 className="twin-detail__section-title">세대원 {members.length}명</h3>
      {members.length === 0 ? (
        <p className="twin-detail__empty">등록된 세대원이 없습니다.</p>
      ) : (
        <ul className="twin-detail__members">
          {members.map((m, i) => (
            <li key={`${m.nameMasked}-${i}`} className="twin-detail__member">
              <span className="twin-detail__member-name">{m.nameMasked}</span>
              <span className="twin-chip">{labelOf(ROLE_LABELS, m.role)}</span>
              <span className="twin-chip twin-chip--muted">
                {labelOf(MEMBER_STATUS_LABELS, m.status)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function InquiriesSection({ inquiries }: { inquiries: readonly TwinOpenInquiry[] }) {
  return (
    <section className="twin-detail__section">
      <h3 className="twin-detail__section-title">미종결 민원 {inquiries.length}건</h3>
      {inquiries.length === 0 ? (
        <p className="twin-detail__empty">미종결 민원 없음</p>
      ) : (
        <ul className="twin-detail__inquiries">
          {inquiries.map((inq) => (
            <li key={inq.id} className="twin-detail__inquiry">
              <div className="twin-detail__inquiry-top">
                <span className="twin-pill">{labelOf(INQUIRY_STATUS_LABELS, inq.status)}</span>
                {inq.priority ? (
                  <span className="twin-chip twin-chip--muted">
                    {labelOf(PRIORITY_LABELS, inq.priority)}
                  </span>
                ) : null}
                <span className="twin-detail__inquiry-date">{shortDate(inq.createdAt)}</span>
              </div>
              <p className="twin-detail__inquiry-title">{inq.title}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function FeeSection({ fee }: { fee: TwinHouseholdDetail["currentFee"] }) {
  return (
    <section className="twin-detail__section">
      <h3 className="twin-detail__section-title">당월 관리비</h3>
      {fee ? (
        <div className="twin-detail__fee">
          <span className="twin-detail__fee-period">{fee.period}</span>
          <span className="twin-detail__fee-total">{formatWon(fee.total)}</span>
        </div>
      ) : (
        <p className="twin-detail__empty">부과 내역 없음</p>
      )}
    </section>
  );
}

/**
 * 세대 평면도 — 왼쪽 3D 무대를 덮는 오버레이로 연다(TwinFloorPlanOverlay 가 그때 불러온다).
 * 타입이 없는 세대는 매칭할 평면도가 없으므로 버튼을 내지 않는다.
 */
function FloorPlanSection({
  unitTypeLabel,
  onOpen,
}: {
  unitTypeLabel: string | null;
  onOpen: (unitTypeLabel: string) => void;
}) {
  return (
    <section className="twin-detail__section">
      <h3 className="twin-detail__section-title">평면도</h3>
      {unitTypeLabel ? (
        <Button variant="secondary" onClick={() => onOpen(unitTypeLabel)}>
          평면도 보기
        </Button>
      ) : (
        <p className="twin-detail__empty">세대 타입이 없어 평면도를 찾을 수 없습니다.</p>
      )}
    </section>
  );
}
