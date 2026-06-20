"use client";

import { useMemo, useState } from "react";
import "./inquiry-admin.css";

type Status = "unassigned" | "progress" | "done";
type Priority = "high" | "mid" | "low";

interface Row {
  id: string;
  title: string;
  asker: string;
  cat: string;
  catConf: string;
  prio: Priority;
  status: Status;
  assignee: string;
  date: string;
}

const ROWS: readonly Row[] = [
  { id: "C-0612", title: "1203동 엘리베이터 소음", asker: "홍*동", cat: "승강기", catConf: "92%", prio: "high", status: "unassigned", assignee: "—", date: "06/12" },
  { id: "C-0611", title: "지하주차장 B2 천장 누수", asker: "이*아", cat: "누수", catConf: "88%", prio: "high", status: "progress", assignee: "시설팀 박*철", date: "06/11" },
  { id: "C-0610", title: "놀이터 가로등 점멸", asker: "최*수", cat: "전기", catConf: "79%", prio: "mid", status: "unassigned", assignee: "—", date: "06/10" },
  { id: "C-0608", title: "분리수거장 악취 민원", asker: "정*민", cat: "환경", catConf: "71%", prio: "mid", status: "progress", assignee: "미화팀 김*숙", date: "06/08" },
  { id: "C-0605", title: "현관 자동문 센서 오작동", asker: "강*호", cat: "시설", catConf: "84%", prio: "low", status: "done", assignee: "시설팀 박*철", date: "06/05" },
  { id: "C-0603", title: "조경수 가지치기 요청", asker: "윤*경", cat: "조경", catConf: "66%", prio: "low", status: "done", assignee: "조경팀 외주", date: "06/03" },
  { id: "C-0601", title: "택배 보관함 고장", asker: "서*진", cat: "시설", catConf: "90%", prio: "mid", status: "done", assignee: "시설팀 박*철", date: "06/01" },
];

const PRIO_META: Record<Priority, { icon: string; label: string }> = {
  high: { icon: "▲", label: "높음" },
  mid: { icon: "■", label: "보통" },
  low: { icon: "▼", label: "낮음" },
};
const STATUS_LABEL: Record<Status, string> = {
  unassigned: "미배정",
  progress: "처리중",
  done: "완료",
};

type FilterId = "all" | Status;
const FILTERS: { id: FilterId; label: string }[] = [
  { id: "all", label: "전체" },
  { id: "unassigned", label: "미배정" },
  { id: "progress", label: "처리중" },
  { id: "done", label: "완료" },
];

export function InquiryAdmin() {
  const [filter, setFilter] = useState<FilterId>("all");

  const counts = useMemo(
    () => ({
      all: ROWS.length,
      unassigned: ROWS.filter((r) => r.status === "unassigned").length,
      progress: ROWS.filter((r) => r.status === "progress").length,
      done: ROWS.filter((r) => r.status === "done").length,
    }),
    [],
  );

  const rows = filter === "all" ? ROWS : ROWS.filter((r) => r.status === filter);

  return (
    <>
      <header className="admin-page__header">
        <div className="ia-head">
          <div>
            <h1 id="main" className="admin-page__title">
              민원 관리
            </h1>
            <p className="admin-page__lede">
              AI가 분류·우선순위를 제안합니다. 담당자 배정은 직접 확정합니다.
            </p>
          </div>
          <input
            type="search"
            className="ia-search"
            placeholder="제목·접수번호 검색"
            aria-label="민원 검색"
          />
        </div>
        <div className="ia-filters" role="tablist" aria-label="상태 필터">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              role="tab"
              aria-selected={filter === f.id}
              className="ia-filter"
              data-active={filter === f.id || undefined}
              onClick={() => setFilter(f.id)}
            >
              {f.label}
              <span className="ia-filter__count">{counts[f.id]}</span>
            </button>
          ))}
        </div>
      </header>

      <main className="admin-page__main">
        <div className="surface-card ia-tablecard">
          <div className="ia-table__scroll">
            <table className="ia-table">
              <thead>
                <tr>
                  <th scope="col">접수번호</th>
                  <th scope="col">제목 · 접수자</th>
                  <th scope="col">AI 분류</th>
                  <th scope="col">우선순위</th>
                  <th scope="col">상태</th>
                  <th scope="col">담당</th>
                  <th scope="col">접수일</th>
                  <th scope="col" className="ia-table__right">
                    배정
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const unassigned = r.status === "unassigned";
                  return (
                    <tr key={r.id}>
                      <td className="ia-cell--id">{r.id}</td>
                      <td>
                        <div className="ia-cell__title">{r.title}</div>
                        <div className="ia-cell__asker">{r.asker} 입주민</div>
                      </td>
                      <td className="ia-nowrap">
                        <span className="ia-cat">
                          <span className="ia-cat__name">{r.cat}</span>
                          <span className="ia-cat__conf">{r.catConf}</span>
                        </span>
                      </td>
                      <td className="ia-nowrap">
                        <span className={`ia-prio ia-prio--${r.prio}`}>
                          <span aria-hidden="true">{PRIO_META[r.prio].icon}</span>
                          {PRIO_META[r.prio].label}
                        </span>
                      </td>
                      <td className="ia-nowrap">
                        <span className={`ia-status ia-status--${r.status}`}>
                          <span className="ia-status__dot" aria-hidden="true" />
                          {STATUS_LABEL[r.status]}
                        </span>
                      </td>
                      <td className="ia-nowrap" data-muted={unassigned || undefined}>
                        {r.assignee}
                      </td>
                      <td className="ia-nowrap ia-cell--date">{r.date}</td>
                      <td className="ia-nowrap ia-table__right">
                        <button
                          type="button"
                          className={unassigned ? "btn btn--primary btn--sm" : "btn btn--secondary btn--sm"}
                        >
                          {unassigned ? "배정하기" : "보기"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="ia-pagination">
            <span>전체 {counts.all}건 중 1–{rows.length}</span>
            <div className="ia-pages">
              <button type="button" className="ia-page" aria-label="이전">
                ‹
              </button>
              <button type="button" className="ia-page ia-page--active" aria-current="page">
                1
              </button>
              <button type="button" className="ia-page">
                2
              </button>
              <button type="button" className="ia-page" aria-label="다음">
                ›
              </button>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}
