"use client";

/**
 * 구조화 블록 렌더러 (H18-3 ②) — `citation.data.kind` 별 표·목록·상태 카드.
 *
 * 두 번째 소비자(관리자 홈 어시스턴트)가 생겨 `packages/ui` 로 올렸다(ADR-0028 결정 4 — 어시스턴트
 * **메커니즘**은 공용, 조립은 앱별). 형태는 여전히 SSE 도구 페이로드 계약(ADR-0025 §6) 그
 * 자체다. 스타일은 assistant.css 의 토큰만 쓴다.
 *
 * 값은 서버가 확정한 것을 **그대로** 뿌린다. 프론트에서 하는 계산은 천단위 구분 표기뿐이다.
 */

import type {
  FacilityStatusData,
  FeeCompareData,
  FeeTableData,
  InquiryCasesData,
  ParkingSpotsData,
  StructuredData,
} from "./assistant-structured";

/** 금액 표기 — 값 자체는 서버 것 그대로, 자릿수 구분만 붙인다. */
const won = (amount: number) => `${amount.toLocaleString("ko-KR")}원`;

export function StructuredBlock({ data }: { data: StructuredData }) {
  switch (data.kind) {
    case "fee_table":
      return <FeeTable data={data} />;
    case "fee_compare":
      return <FeeCompare data={data} />;
    case "parking_spots":
      return <ParkingSpots data={data} />;
    case "facility_status":
      return <FacilityStatus data={data} />;
    case "inquiry_cases":
      return <InquiryCases data={data} />;
  }
}

function FeeTable({ data }: { data: FeeTableData }) {
  // 다중 월 조회는 월별 표 + 평균 — 항목표는 월마다 갈라져 한 표로 못 합친다.
  if (data.months.length > 0) return <FeeMonths data={data} />;
  if (data.rows.length === 0 || data.total === null) return null;
  // 증감은 색만으로 전하지 않는다 — "늘었어요/줄었어요"를 글자로 함께 쓴다(WCAG 1.4.1).
  const trend =
    data.diff === null ? null : data.diff >= 0 ? "늘었어요" : "줄었어요";
  // 범위 평균(H20-1)은 본인 세대 값이 아니다 — 제목·합계 라벨로 평균임을 못박는다.
  const caption = data.scope
    ? `${data.scope.label} ${data.period} 관리비 평균 (표본 ${data.scope.sampleSize}세대)`
    : `${data.period} 관리비 내역`;
  return (
    <figure className="sb">
      <figcaption className="sb__caption">{caption}</figcaption>
      {/* 375px 에서 표가 넘치면 이 컨테이너 안에서만 가로 스크롤된다. */}
      <div className="sb__scroll" tabIndex={0} role="group" aria-label="관리비 항목 표">
        <table className="sb__table">
          <thead>
            <tr>
              <th scope="col">항목</th>
              <th scope="col" className="sb__num">
                금액
              </th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.name}>
                <th scope="row">{row.name}</th>
                <td className="sb__num">{won(row.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">{data.scope ? "평균 총액" : "합계"}</th>
              <td className="sb__num">{won(data.total)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      {data.prevTotal !== null && data.diff !== null ? (
        <p className="sb__note">
          전월 {won(data.prevTotal)} 대비 {won(Math.abs(data.diff))} {trend}
        </p>
      ) : null}
    </figure>
  );
}

/**
 * 관리비 비교(H20-1 후속) — 대상별 값과 차액. 값을 못 낸 대상도 사유와 함께 그린다.
 * 값·차액은 서버가 확정한 것 그대로다(여기서 빼지 않는다, 규칙 5).
 */
function FeeCompare({ data }: { data: FeeCompareData }) {
  if (data.rows.length === 0) return null;
  const caption = data.item
    ? `${data.period} 관리비 비교 (${data.item})`
    : `${data.period} 관리비 비교`;
  return (
    <figure className="sb">
      <figcaption className="sb__caption">{caption}</figcaption>
      <div className="sb__scroll" tabIndex={0} role="group" aria-label="관리비 비교 표">
        <table className="sb__table">
          <thead>
            <tr>
              <th scope="col">대상</th>
              <th scope="col" className="sb__num">
                금액
              </th>
              <th scope="col" className="sb__num">
                표본
              </th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={row.label}>
                <th scope="row">{row.label}</th>
                <td className="sb__num">{row.amount === null ? row.note : won(row.amount)}</td>
                <td className="sb__num">
                  {row.sampleSize === null ? "—" : `${row.sampleSize}세대`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* 증감은 색이 아니라 글자로 전한다(WCAG 1.4.1) — 부호만으로는 안 읽힌다. */}
      {data.diffs.map((d) => (
        <p className="sb__note" key={d.label}>
          {data.baseLabel}이(가) {d.label}보다 {won(Math.abs(d.diff))}{" "}
          {d.diff >= 0 ? "많아요" : "적어요"}
        </p>
      ))}
    </figure>
  );
}

/**
 * 여러 달 관리비 — 월별 합계와 **서버가 낸 평균**. 평균이 null 이면 줄을 그리지 않는다.
 * 여기서 나눗셈을 하면 AI 가 하던 계산을 프론트가 대신하는 것뿐이다(규칙 5).
 */
function FeeMonths({ data }: { data: FeeTableData }) {
  return (
    <figure className="sb">
      <figcaption className="sb__caption">{data.period} 관리비</figcaption>
      <div className="sb__scroll" tabIndex={0} role="group" aria-label="월별 관리비 표">
        <table className="sb__table">
          <thead>
            <tr>
              <th scope="col">월</th>
              <th scope="col" className="sb__num">
                합계
              </th>
            </tr>
          </thead>
          <tbody>
            {data.months.map((month) => (
              <tr key={month.period}>
                <th scope="row">{month.period}</th>
                <td className="sb__num">{won(month.total)}</td>
              </tr>
            ))}
          </tbody>
          {data.averageTotal !== null ? (
            <tfoot>
              <tr>
                <th scope="row">{data.months.length}개월 평균</th>
                <td className="sb__num">{won(data.averageTotal)}</td>
              </tr>
            </tfoot>
          ) : null}
        </table>
      </div>
      {data.missingPeriods.length > 0 ? (
        <p className="sb__note">
          {data.missingPeriods.join(", ")} 관리비 내역이 없어 평균을 내지 않았어요
        </p>
      ) : null}
      {data.excludedPeriods.length > 0 ? (
        <p className="sb__note">
          {data.excludedPeriods.join(", ")}은(는) 입주 승인 이전이라 제외했어요
        </p>
      ) : null}
    </figure>
  );
}

function ParkingSpots({ data }: { data: ParkingSpotsData }) {
  if (data.spots.length === 0) return null;
  return (
    <figure className="sb">
      <figcaption className="sb__caption">가까운 빈자리</figcaption>
      <ol className="sb__list">
        {data.spots.map((spot, i) => (
          <li key={spot.no} className="sb__item">
            <span className="sb__rank" aria-hidden="true">
              {i + 1}
            </span>
            <span className="sb__item-main">
              <strong>{spot.no}면</strong>
              <span className="sb__item-sub">{spot.kind}</span>
            </span>
            <span className="sb__item-side">약 {spot.distanceM}m</span>
          </li>
        ))}
      </ol>
    </figure>
  );
}

function FacilityStatus({ data }: { data: FacilityStatusData }) {
  if (data.total === 0) return null;
  return (
    <figure className="sb">
      <figcaption className="sb__caption">시설 현황 (총 {data.total}대)</figcaption>
      <ul className="sb__counts">
        {data.statusCounts.map(({ status, count }) => (
          <li key={status} className="sb__count">
            {/* 상태는 글자로 쓴다 — 색·아이콘 단독 전달 금지(WCAG 1.4.1). */}
            <span className="sb__count-label">{status}</span>
            <span className="sb__count-value">{count}대</span>
          </li>
        ))}
      </ul>
      {data.items.length > 0 ? (
        <ul className="sb__list">
          {data.items.map((item) => (
            <li key={item.code ?? item.name} className="sb__item">
              <span className="sb__item-main">
                <strong>{item.name}</strong>
                {item.code ? <span className="sb__item-sub">{item.code}</span> : null}
              </span>
              <span className="sb__item-side">{item.status}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </figure>
  );
}

function InquiryCases({ data }: { data: InquiryCasesData }) {
  if (data.cases.length === 0) return null;
  return (
    <figure className="sb">
      <figcaption className="sb__caption">비슷한 민원 {data.cases.length}건</figcaption>
      <ul className="sb__list">
        {data.cases.map((c) => (
          <li key={c.title} className="sb__case">
            <span className="sb__case-head">
              <strong>{c.title}</strong>
              <span className="sb__item-sub">
                {c.category} · {c.status}
                {c.isMine ? " · 내 접수" : ""}
              </span>
            </span>
            <span className="sb__case-body">{c.resolution}</span>
          </li>
        ))}
      </ul>
    </figure>
  );
}
