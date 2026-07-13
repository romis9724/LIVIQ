"use client";

import { useState } from "react";
import { Button, Toast } from "@liviq/ui";
import { confidenceLook, REVIEW_ITEMS, type ReviewItem } from "./data";
import "./review-queue.css";

type Decision = { id: string; label: string };

export function ReviewQueue() {
  const [items, setItems] = useState<ReviewItem[]>([...REVIEW_ITEMS]);
  const [toast, setToast] = useState<Decision | null>(null);

  const decide = (item: ReviewItem, label: string) => {
    setItems((prev) => prev.filter((i) => i.id !== item.id));
    setToast({ id: item.id, label });
  };

  return (
    <>
      <header className="admin-page__header">
        <div className="rq-head">
          <div>
            <div className="rq-head__titlerow">
              <h1 id="main" className="admin-page__title">
                AI 검수 큐
              </h1>
              <span className="rq-head__count">{items.length}건 대기</span>
            </div>
            <p className="admin-page__lede">
              신뢰도가 낮거나 출처가 약한 답변을 검토하고 승인·반려합니다. 승인·반려 결과는 골든셋과
              FAQ 개선에 반영됩니다(사용자에게 재전달되지 않음).
            </p>
          </div>
          <div className="rq-head__sort">
            <label htmlFor="rq-sort">정렬</label>
            <select id="rq-sort" className="rq-select">
              <option>신뢰도 낮은순</option>
              <option>최신순</option>
              <option>문의 많은순</option>
            </select>
          </div>
        </div>
      </header>

      <main className="admin-page__main">
        {items.length === 0 ? (
          <div className="rq-empty">
            <span className="rq-empty__mark" aria-hidden="true">
              ✓
            </span>
            <p className="rq-empty__title">검수 대기 항목이 없습니다</p>
            <p className="rq-empty__desc">
              모든 답변이 처리되었어요. 신뢰도가 낮은 새 답변이 생기면 이곳에 모입니다.
            </p>
          </div>
        ) : (
          <div className="rq-list">
            {items.map((item) => (
              <ReviewCard key={item.id} item={item} onDecide={decide} />
            ))}
          </div>
        )}
      </main>

      {toast ? <div className="rq-toast"><Toast message={`'${toast.label}' 처리되었습니다.`} /></div> : null}
    </>
  );
}

function ReviewCard({ item, onDecide }: { item: ReviewItem; onDecide: (item: ReviewItem, label: string) => void }) {
  const look = confidenceLook(item.confidence);
  const canApprove = Boolean(item.source);

  return (
    <article className="rq-card">
      <div className="rq-card__main">
        <div className="rq-card__meta">
          <span className="rq-card__asker">{item.asker}</span>
          <span aria-hidden="true">·</span>
          <span>{item.when}</span>
          <span aria-hidden="true">·</span>
          <span>문의 {item.count}회</span>
        </div>
        <h2 className="rq-card__question">{item.question}</h2>

        <div className="rq-card__sublabel">AI 초안 답변</div>
        <p className="rq-card__answer">{item.answer}</p>

        {item.source ? (
          <div className="rq-source">
            <div className="rq-source__head">
              <span aria-hidden="true">📄</span>
              <span className="rq-source__label">출처</span>
            </div>
            <div className="rq-source__title">{item.source.title}</div>
            <div className="rq-source__meta">{item.source.meta}</div>
          </div>
        ) : (
          <div className="rq-nosource" role="alert">
            <div className="rq-nosource__head">
              <span aria-hidden="true">⚠</span> 근거 문서를 찾지 못함
            </div>
            <div className="rq-nosource__desc">
              출처 없는 답변은 발송할 수 없습니다. ‘담당자 연결’ 폴백을 권장합니다.
            </div>
          </div>
        )}
      </div>

      <div className="rq-card__side">
        <div>
          <div className="rq-conf__top">
            <span className="rq-conf__label">신뢰도</span>
            <span className="rq-conf__tag" style={{ color: look.color }}>
              <span aria-hidden="true">{look.icon}</span>
              {look.label}
            </span>
          </div>
          <div
            className="rq-conf__meter"
            role="meter"
            aria-valuenow={item.confidence}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="AI 신뢰도"
          >
            <span style={{ width: `${item.confidence}%`, background: look.color }} />
          </div>
          <div className="rq-conf__score">
            {item.confidence}
            <span className="rq-conf__denom">/100</span>
          </div>
        </div>

        <div className="rq-actions">
          <Button
            variant="primary"
            disabled={!canApprove}
            onClick={() => onDecide(item, "승인")}
          >
            {canApprove ? "승인" : "승인 불가 (출처 없음)"}
          </Button>
          <Button variant="secondary" onClick={() => onDecide(item, "수정 후 승인")}>
            수정 후 승인
          </Button>
          <Button variant="danger" onClick={() => onDecide(item, "반려")}>
            반려
          </Button>
        </div>
      </div>
    </article>
  );
}
