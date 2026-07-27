/** 장애·정비 이력 타임라인 — 목록 뷰 상세 패널과 그래프 상세 패널이 공유한다. */

export interface HistoryItem {
  id: string;
  date: string;
  primary: string;
  secondary: string | null;
}

interface HistorySectionProps {
  title: string;
  empty: string;
  items: readonly HistoryItem[];
}

export function HistorySection({ title, empty, items }: HistorySectionProps) {
  return (
    <section className="fac-history">
      <div className="fac-history__title">{title}</div>
      {items.length === 0 ? (
        <p className="fac-history__empty">{empty}</p>
      ) : (
        <ol className="fac-history__list">
          {items.map((item) => (
            <li key={item.id} className="fac-history__item">
              <span className="fac-history__date">{item.date}</span>
              <div className="fac-history__body">
                <div className="fac-history__primary">{item.primary}</div>
                {item.secondary ? (
                  <div className="fac-history__secondary">{item.secondary}</div>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
