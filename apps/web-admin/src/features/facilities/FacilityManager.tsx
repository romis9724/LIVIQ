"use client";

import { useState } from "react";
import "./facilities.css";

type FacilityStatus = "ok" | "check" | "fault" | "risk";

interface Cause {
  title: string;
  likelihood: string;
  desc: string;
}

interface Facility {
  icon: string;
  name: string;
  loc: string;
  checked: string;
  status: FacilityStatus;
  detail: string;
  causes?: Cause[];
  sources?: string;
}

const STATUS_META: Record<FacilityStatus, { label: string }> = {
  ok: { label: "정상" },
  check: { label: "점검" },
  fault: { label: "장애" },
  risk: { label: "위험" },
};

const LEGEND: { status: FacilityStatus; count: number }[] = [
  { status: "ok", count: 18 },
  { status: "check", count: 3 },
  { status: "fault", count: 1 },
  { status: "risk", count: 0 },
];

const FACILITIES: readonly Facility[] = [
  {
    icon: "🛗",
    name: "1203동 3호기 승강기",
    loc: "1203동",
    checked: "5월",
    status: "fault",
    detail: "관련 민원 2건 · 2026-06-12 09:05 이상 감지. 운행 중 ‘덜컹’ 소음 및 저층 정지 지연.",
    sources: "승강기 점검 이력(2026-05) · 제조사 점검 매뉴얼",
    causes: [
      {
        title: "가이드 롤러·레일 마모",
        likelihood: "높음",
        desc: "저층 운행 시 ‘덜컹’ 소음은 롤러 또는 레일 마모에서 자주 보고됩니다. 점검 이력상 교체 주기가 도래했습니다.",
      },
      {
        title: "도어 인터록 정렬 불량",
        likelihood: "보통",
        desc: "정지 지연은 도어 센서·인터록 정렬 문제일 수 있습니다. 현장 확인이 필요합니다.",
      },
      {
        title: "권상기 브레이크 라이닝",
        likelihood: "낮음",
        desc: "가능성은 낮지만 안전 관련 항목이므로 전문 점검 시 함께 확인을 권장합니다.",
      },
    ],
  },
  { icon: "💧", name: "지하 저수조 펌프 A", loc: "지하 1층", checked: "어제", status: "check", detail: "정기 점검 주기 도래. 압력 센서 수치가 권장 범위 하단에 근접해 모니터링 중입니다." },
  { icon: "🔥", name: "지역난방 열교환기", loc: "기계실", checked: "6월", status: "ok", detail: "정상 운영 중입니다. 최근 점검에서 이상 소견이 없었습니다." },
  { icon: "🚗", name: "주차 차단기 (정문)", loc: "정문", checked: "6월", status: "ok", detail: "정상 운영 중입니다." },
  { icon: "💡", name: "단지 외곽 보안등", loc: "단지 전역", checked: "5월", status: "check", detail: "일부 구간 점멸 신고가 접수되어 점검이 권장됩니다." },
  { icon: "🎥", name: "CCTV 통합관제", loc: "관리사무소", checked: "오늘", status: "ok", detail: "정상 운영 중입니다. 전 채널 녹화 정상." },
];

export function FacilityManager() {
  const [selected, setSelected] = useState(0);
  const facility = FACILITIES[selected]!;

  return (
    <>
      <header className="admin-page__header fac-head">
        <div className="fac-head__text">
          <h1 id="main" className="admin-page__title">
            시설 관리
          </h1>
          <p className="admin-page__lede">
            단지 시설의 운영 상태를 한눈에. 이상 시설은 AI가 가능 원인 후보를 제시합니다.
          </p>
        </div>
        <div className="fac-legend">
          {LEGEND.map((l) => (
            <span key={l.status} className="fac-legend__item">
              <span className={`fac-dot fac-dot--${l.status}`} aria-hidden="true" />
              {STATUS_META[l.status].label} {l.count}
            </span>
          ))}
        </div>
      </header>

      <main className="fac-main">
        <div className="fac-list">
          {FACILITIES.map((f, i) => (
            <button
              key={f.name}
              type="button"
              className="fac-card"
              aria-pressed={selected === i}
              data-active={selected === i || undefined}
              onClick={() => setSelected(i)}
            >
              <span className="fac-card__icon" aria-hidden="true">
                {f.icon}
              </span>
              <span className="fac-card__body">
                <span className="fac-card__name">{f.name}</span>
                <span className="fac-card__meta">
                  {f.loc} · 최근 점검 {f.checked}
                </span>
              </span>
              <span className={`fac-pill fac-pill--${f.status}`}>
                <span className={`fac-dot fac-dot--${f.status}`} aria-hidden="true" />
                {STATUS_META[f.status].label}
              </span>
            </button>
          ))}
        </div>

        <aside className="fac-detail">
          <div>
            <div className="fac-detail__head">
              <span className="fac-detail__icon" data-status={facility.status} aria-hidden="true">
                {facility.icon}
              </span>
              <div>
                <div className="fac-detail__name">{facility.name}</div>
                <span className={`fac-pill fac-pill--${facility.status}`}>
                  <span className={`fac-dot fac-dot--${facility.status}`} aria-hidden="true" />
                  {STATUS_META[facility.status].label}
                </span>
              </div>
            </div>
            <p className="fac-detail__desc">{facility.detail}</p>
          </div>

          {facility.causes ? (
            <div className="fac-causes">
              <div className="fac-causes__head">
                <span className="fac-causes__mark" aria-hidden="true">
                  L
                </span>
                <span className="fac-causes__label">AI 도우미 · 가능 원인 후보</span>
              </div>
              <p className="fac-causes__disclaimer">
                아래는 민원 내용과 점검 이력을 바탕으로 한 <strong>추정 후보</strong>입니다. 단정이
                아니며, 실제 원인은 전문 점검으로 확인해야 합니다.
              </p>
              <ol className="fac-causes__list">
                {facility.causes.map((c) => (
                  <li key={c.title} className="fac-cause">
                    <div className="fac-cause__top">
                      <span className="fac-cause__title">{c.title}</span>
                      <span className="fac-cause__likelihood">가능성 {c.likelihood}</span>
                    </div>
                    <div className="fac-cause__desc">{c.desc}</div>
                  </li>
                ))}
              </ol>
              {facility.sources ? (
                <div className="fac-causes__sources">
                  <span aria-hidden="true">📄</span> 참고: {facility.sources}
                </div>
              ) : null}
            </div>
          ) : (
            <div className="fac-note" data-status={facility.status}>
              {facility.status === "ok"
                ? "현재 이상 징후가 없습니다. 다음 정기 점검까지 모니터링합니다."
                : "점검이 권장되는 상태입니다. 현장 확인 후 상태를 업데이트하세요."}
            </div>
          )}

          <div className="fac-detail__actions">
            <button type="button" className="btn btn--primary">
              전문 점검 요청
            </button>
            <button type="button" className="btn btn--secondary">
              점검 상태로 전환
            </button>
          </div>
        </aside>
      </main>
    </>
  );
}
