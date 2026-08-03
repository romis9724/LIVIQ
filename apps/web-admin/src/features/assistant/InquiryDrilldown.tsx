"use client";

// 상태 카드 드릴다운(H20-13) — 고른 상태의 민원 줄 + 민원별 인라인 요약.
// 목록은 패널이 이미 받아둔 배열에서 거른다(서버 재조회 없음). 처리 내역만 펼칠 때 1회 조회한다.

import Link from "next/link";
import { Skeleton } from "@liviq/ui";
import { useEffect, useState } from "react";

import { listInquiryEvents, type Inquiry, type InquiryEvent, type InquiryStatus } from "@/lib/api";
import { drilldownRows, errorMessage, excerpt, historyLines } from "./panel-data";

/** 요약 발췌 상한 — 패널이 좁아 두세 줄이면 충분하다(원문은 민원 관리에서). */
const BODY_LIMIT = 160;

interface InquiryDrilldownProps {
  inquiries: readonly Inquiry[];
  status: InquiryStatus;
  now: Date;
}

export function InquiryDrilldown({ inquiries, status, now }: InquiryDrilldownProps) {
  const [openId, setOpenId] = useState<string | null>(null);
  const rows = drilldownRows(inquiries, status, now);

  if (rows.length === 0) {
    return <p className="adm-panel__note">해당 상태의 민원이 없습니다.</p>;
  }

  return (
    <ul className="adm-drill">
      {rows.map((row) => {
        const { inquiry } = row;
        const open = openId === inquiry.id;
        const detailId = `adm-detail-${inquiry.id}`;
        return (
          <li key={inquiry.id} className="adm-drill__item">
            <button
              type="button"
              className="adm-row"
              aria-expanded={open}
              aria-controls={detailId}
              onClick={() => setOpenId(open ? null : inquiry.id)}
            >
              <span className="adm-row__title">{inquiry.title}</span>
              <span className="adm-row__meta">
                <span className="adm-row__date">
                  {row.dateKind === "completed" ? "완료" : "접수"} {row.dateLabel}
                </span>
                {row.elapsedDays === null ? null : (
                  <span className="adm-row__elapsed" data-overdue={row.overdue || undefined}>
                    {row.elapsedDays === 0 ? "오늘 접수" : `${row.elapsedDays}일 경과`}
                  </span>
                )}
              </span>
            </button>
            {open ? <InquiryDetail inquiry={inquiry} id={detailId} /> : null}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * 민원 한 건의 요약 — 내용 발췌 + 처리 내역(inquiry_events).
 * 요약은 코드가 만든다(LLM 호출 없음 — 규칙 7). 민원↔AI 대화를 잇는 필드가 스키마에 없어
 * "대화 내용"은 접수 본문으로 대신한다(AI 상담에서 넘어온 접수는 본문에 상담 내용이 담긴다).
 */
function InquiryDetail({ inquiry, id }: { inquiry: Inquiry; id: string }) {
  const [events, setEvents] = useState<readonly InquiryEvent[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setEvents(null);
    setLoadError(null);
    listInquiryEvents(inquiry.id)
      .then((items) => {
        if (alive) setEvents(items);
      })
      .catch((err) => {
        if (alive) setLoadError(errorMessage(err));
      });
    return () => {
      alive = false;
    };
  }, [inquiry.id]);

  const body = excerpt(inquiry.body, BODY_LIMIT);

  return (
    <div id={id} className="adm-detail">
      <h4 className="adm-detail__label">민원 내용 요약</h4>
      <p className="adm-detail__body">{body || "내용이 없습니다."}</p>

      <h4 className="adm-detail__label">이전 처리 내역</h4>
      <DetailHistory events={events} loadError={loadError} />

      <Link href={`/inquiries?inquiry=${inquiry.id}`} className="adm-detail__link">
        민원 관리에서 열기
      </Link>
    </div>
  );
}

function DetailHistory({
  events,
  loadError,
}: {
  events: readonly InquiryEvent[] | null;
  loadError: string | null;
}) {
  if (loadError) return <p className="adm-panel__note">{loadError}</p>;
  if (events === null) return <Skeleton height="3rem" />;

  const lines = historyLines(events);
  if (lines.length === 0) return <p className="adm-panel__note">아직 처리 내역이 없습니다.</p>;

  return (
    <ol className="adm-history">
      {lines.map((line) => (
        <li key={line.id} className="adm-history__line">
          <span className="adm-history__date">{line.date}</span>
          <span className="adm-history__text">{line.text}</span>
        </li>
      ))}
    </ol>
  );
}
