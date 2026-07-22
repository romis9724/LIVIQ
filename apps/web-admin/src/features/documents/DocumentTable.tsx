"use client";

import Link from "next/link";

import type { DocumentItem } from "@/lib/api";
import { INDEX_META, VISIBILITY_META, shortDate } from "./data";

interface DocumentTableProps {
  docs: readonly DocumentItem[];
}

/** 문서 게시판 목록 — 행 클릭(제목 링크)으로 상세/수정. 편집·재색인은 상세에서. */
export function DocumentTable({ docs }: DocumentTableProps) {
  return (
    <div className="surface-card doc-tablecard">
      <div className="doc-table__scroll">
        <table className="doc-table">
          <thead>
            <tr>
              <th scope="col">제목</th>
              <th scope="col">카테고리</th>
              <th scope="col">공개 범위</th>
              <th scope="col">버전</th>
              <th scope="col">색인 상태</th>
              <th scope="col">수정일</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((doc) => {
              const ix = INDEX_META[doc.indexStatus];
              const scope = VISIBILITY_META[doc.visibility];
              return (
                <tr key={doc.id}>
                  <td>
                    <Link className="doc-name doc-name--link" href={`/documents/${doc.id}`}>
                      <span className="doc-name__icon" aria-hidden="true">
                        📄
                      </span>
                      <span className="doc-name__title">{doc.title}</span>
                    </Link>
                  </td>
                  <td className="doc-nowrap">{doc.sourceType}</td>
                  <td className="doc-nowrap">
                    <span className="doc-scope">
                      <span aria-hidden="true">{scope.icon}</span>
                      {scope.label}
                    </span>
                  </td>
                  <td className="doc-nowrap doc-version">v{doc.version}</td>
                  <td className="doc-nowrap">
                    <span className={`doc-idx doc-idx--${doc.indexStatus}`}>
                      <span aria-hidden="true" className={ix.spin ? "doc-idx__spin" : undefined}>
                        {ix.icon}
                      </span>
                      {ix.label}
                    </span>
                  </td>
                  <td className="doc-nowrap doc-date">{shortDate(doc.updatedAt)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
