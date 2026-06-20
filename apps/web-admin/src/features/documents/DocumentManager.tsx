import "./documents.css";

type IndexState = "indexed" | "indexing" | "pending" | "failed";
type Scope = "all" | "resident" | "staff";

interface Doc {
  name: string;
  meta: string;
  scope: Scope;
  index: IndexState;
  date: string;
}

const SUMMARY = [
  { label: "색인 완료", count: 42, color: "var(--color-success)" },
  { label: "색인 중", count: 2, color: "var(--color-accent)" },
  { label: "대기", count: 1, color: "var(--color-text-muted)" },
  { label: "실패", count: 1, color: "var(--color-danger)" },
] as const;

const SCOPE_META: Record<Scope, { icon: string; label: string }> = {
  all: { icon: "🌐", label: "전체 공개" },
  resident: { icon: "🏠", label: "입주민" },
  staff: { icon: "🔒", label: "관리자 전용" },
};

const INDEX_META: Record<IndexState, { icon: string; label: string; spin?: boolean }> = {
  indexed: { icon: "✓", label: "색인 완료" },
  indexing: { icon: "↻", label: "색인 중", spin: true },
  pending: { icon: "•", label: "대기" },
  failed: { icon: "⚠", label: "색인 실패" },
};

const DOCS: readonly Doc[] = [
  { name: "공동주택 관리규약", meta: "PDF · 1.8MB · 64p", scope: "all", index: "indexed", date: "06/01" },
  { name: "2026 관리비 부과 기준표", meta: "XLSX · 240KB", scope: "resident", index: "indexing", date: "06/18" },
  { name: "주차장 운영 세칙", meta: "HWP · 420KB · 12p", scope: "resident", index: "indexed", date: "05/22" },
  { name: "5월 입대의 회의록", meta: "DOCX · 88KB", scope: "staff", index: "pending", date: "06/19" },
  { name: "승강기 점검 계약서(스캔)", meta: "PDF · 9.2MB · 이미지", scope: "staff", index: "failed", date: "06/17" },
  { name: "분리수거 안내문", meta: "PDF · 320KB · 2p", scope: "all", index: "indexed", date: "05/30" },
];

function actionLabel(index: IndexState): string {
  if (index === "failed") return "재색인";
  if (index === "indexing") return "취소";
  return "관리";
}

export function DocumentManager() {
  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          문서 관리
        </h1>
        <p className="admin-page__lede">
          업로드한 문서가 색인되면 AI가 출처로 인용합니다. 색인 실패 문서는 인용되지 않으니
          재색인하세요.
        </p>
      </header>

      <main className="admin-page__main doc-main">
        <div className="doc-upload">
          <span className="doc-upload__icon" aria-hidden="true">
            ⬆
          </span>
          <div className="doc-upload__text">
            <div className="doc-upload__title">문서를 끌어다 놓거나 선택하세요</div>
            <div className="doc-upload__hint">
              PDF · DOCX · HWP · XLSX · 최대 50MB. 관리규약·공지·회의록 등.
            </div>
          </div>
          <button type="button" className="btn btn--primary">
            파일 선택
          </button>
        </div>

        <div className="doc-summary">
          {SUMMARY.map((s) => (
            <div key={s.label} className="doc-summary__card">
              <span className="doc-summary__dot" style={{ background: s.color }} aria-hidden="true" />
              <span className="doc-summary__label">{s.label}</span>
              <span className="doc-summary__count">{s.count}</span>
            </div>
          ))}
        </div>

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
                {DOCS.map((d) => {
                  const ix = INDEX_META[d.index];
                  const sc = SCOPE_META[d.scope];
                  return (
                    <tr key={d.name}>
                      <td>
                        <div className="doc-name">
                          <span className="doc-name__icon" aria-hidden="true">
                            📄
                          </span>
                          <div>
                            <div className="doc-name__title">{d.name}</div>
                            <div className="doc-name__meta">{d.meta}</div>
                          </div>
                        </div>
                      </td>
                      <td className="doc-nowrap">
                        <span className="doc-scope">
                          <span aria-hidden="true">{sc.icon}</span>
                          {sc.label}
                        </span>
                      </td>
                      <td className="doc-nowrap">
                        <span className={`doc-idx doc-idx--${d.index}`}>
                          <span aria-hidden="true" className={ix.spin ? "doc-idx__spin" : undefined}>
                            {ix.icon}
                          </span>
                          {ix.label}
                        </span>
                      </td>
                      <td className="doc-nowrap doc-date">{d.date}</td>
                      <td className="doc-nowrap doc-table__right">
                        <button
                          type="button"
                          className={d.index === "failed" ? "btn btn--danger btn--sm" : "btn btn--secondary btn--sm"}
                        >
                          {actionLabel(d.index)}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </>
  );
}
