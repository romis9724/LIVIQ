"use client";

import { buildInvoice, formatWon, type Invoice } from "./logic";
import type { FeeBreakdownRow } from "@/lib/api";

/**
 * 관리비 고지서 — 대분류(공용관리비·개별사용료 등) 2단 그리드 + 합계 강조 + 잡수입 참고.
 * 당월 고지금액 1열만(전월·증감 없음). 누적지표(충당금잔액·적립요율)는 buildInvoice가 숨긴다.
 */
interface FeeInvoiceProps {
  breakdown: FeeBreakdownRow[];
  total: number;
  caption: string; // 예: "401동 201호 · 2026년 7월"
}

export function FeeInvoice({ breakdown, total, caption }: FeeInvoiceProps) {
  const invoice: Invoice = buildInvoice(breakdown);
  const totalAmount = invoice.total?.amount ?? total;

  return (
    <section className="fee-invoice" aria-label="관리비 고지서">
      <div className="fee-invoice__caption">{caption}</div>

      <div className="fee-invoice__grid">
        {invoice.groups.map((group) => (
          <article key={group.name} className="fee-invoice__group">
            <header className="fee-invoice__group-head">
              <span className="fee-invoice__group-name">{group.name}</span>
              <span className="fee-invoice__group-amount">{formatWon(group.amount)}</span>
            </header>
            <table className="fee-invoice__table">
              <caption className="sr-only">{group.name} 세부 내역</caption>
              <thead>
                <tr>
                  <th scope="col">항목</th>
                  <th scope="col" className="fee-invoice__num">
                    당월 고지금액
                  </th>
                </tr>
              </thead>
              <tbody>
                {group.rows.map((row) => (
                  <tr key={row.name} data-sub={row.level >= 2 || undefined}>
                    <th scope="row" className="fee-invoice__row-name">
                      {row.name}
                    </th>
                    <td className="fee-invoice__num">{formatWon(row.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </article>
        ))}
      </div>

      <div className="fee-invoice__total">
        <span className="fee-invoice__total-label">당월 고지금액 합계</span>
        <span className="fee-invoice__total-value">{formatWon(totalAmount)}</span>
      </div>

      {invoice.info ? (
        <div className="fee-invoice__info">
          <span className="fee-invoice__info-title">
            {invoice.info.name} (참고 · 부과액에서 차감하지 않음)
          </span>
          <ul className="fee-invoice__info-list">
            {invoice.info.rows.map((row) => (
              <li key={row.name}>
                <span>{row.name}</span>
                <span>{formatWon(row.amount)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
