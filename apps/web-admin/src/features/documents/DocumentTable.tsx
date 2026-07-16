"use client";

import { Button } from "@liviq/ui";
import type { ChangeEvent } from "react";

import type { DocumentItem, Visibility } from "@/lib/api";
import { INDEX_META, VISIBILITIES, VISIBILITY_META, shortDate } from "./data";

interface DocumentTableProps {
  docs: readonly DocumentItem[];
  /** 공개범위 수정·재색인 진행 중인 문서 id (버튼 잠금용). */
  busyId: string | null;
  onChangeVisibility: (id: string, visibility: Visibility) => void;
  onReindex: (id: string) => void;
}

export function DocumentTable({
  docs,
  busyId,
  onChangeVisibility,
  onReindex,
}: DocumentTableProps) {
  return (
    <div className="surface-card doc-tablecard">
      <div className="doc-table__scroll">
        <table className="doc-table">
          <thead>
            <tr>
              <th scope="col">문서명</th>
              <th scope="col">공개 범위</th>
              <th scope="col">색인 상태</th>
              <th scope="col">업로드</th>
              <th scope="col" className="doc-table__right">
                작업
              </th>
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => {
              const ix = INDEX_META[doc.indexStatus];
              const isBusy = busyId === doc.id;
              return (
                <tr key={doc.id}>
                  <td>
                    <div className="doc-name">
                      <span className="doc-name__icon" aria-hidden="true">
                        📄
                      </span>
                      <div>
                        <div className="doc-name__title">{doc.title}</div>
                        <div className="doc-name__meta">{doc.sourceType}</div>
                      </div>
                    </div>
                  </td>
                  <td className="doc-nowrap">
                    <label className="doc-visibility">
                      <span className="doc-visibility__label">공개 범위</span>
                      <select
                        className="doc-select"
                        value={doc.visibility}
                        disabled={isBusy}
                        onChange={(event: ChangeEvent<HTMLSelectElement>) =>
                          onChangeVisibility(doc.id, event.target.value as Visibility)
                        }
                      >
                        {VISIBILITIES.map((v) => (
                          <option key={v} value={v}>
                            {VISIBILITY_META[v].label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </td>
                  <td className="doc-nowrap">
                    <span className={`doc-idx doc-idx--${doc.indexStatus}`}>
                      <span aria-hidden="true" className={ix.spin ? "doc-idx__spin" : undefined}>
                        {ix.icon}
                      </span>
                      {ix.label}
                    </span>
                  </td>
                  <td className="doc-nowrap doc-date">{shortDate(doc.createdAt)}</td>
                  <td className="doc-nowrap doc-table__right">
                    {doc.indexStatus === "failed" ? (
                      <Button
                        variant="danger"
                        size="sm"
                        disabled={isBusy}
                        onClick={() => onReindex(doc.id)}
                      >
                        재색인
                      </Button>
                    ) : (
                      <span className="doc-date">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
