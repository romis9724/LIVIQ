"use client";

import { useEffect, useRef, useState } from "react";
import { Skeleton } from "@liviq/ui";
import "./meetings.css";

type View = "upload" | "processing" | "review";

const TRANSCRIPT = [
  { time: "00:42", speaker: "김*수 소장", text: "노후 배관 교체 건부터 논의하겠습니다. 1203동 민원이 가장 많습니다." },
  { time: "03:15", speaker: "박*철 위원", text: "예산은 예비비에서 충당 가능합니다. 다만 공사 시간대 협의가 필요합니다." },
  { time: "07:48", speaker: "이*아 위원", text: "새벽 단수는 불편하니 사전 공지를 충분히 해야 합니다." },
  { time: "12:30", speaker: "김*수 소장", text: "6월 22일 새벽 2시간으로 잡고, 일주일 전 공지하는 것으로 하겠습니다." },
  { time: "18:05", speaker: "박*철 위원", text: "시설팀이 당일 현장 대기하도록 하겠습니다." },
] as const;

const DECISIONS = [
  "1203동 노후 배관 교체를 6월 내 우선 시행한다.",
  "공사는 6/22(월) 03:00~05:00, 일주일 전 사전 공지한다.",
] as const;

const ACTIONS = [
  { task: "단수 공지문 작성·발송", owner: "관리사무소", due: "6/15" },
  { task: "공사 업체 일정 확정", owner: "박*철 위원", due: "6/13" },
  { task: "당일 현장 대기 편성", owner: "시설팀", due: "6/22" },
] as const;

export function MeetingMinutes() {
  const [view, setView] = useState<View>("upload");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const start = () => {
    setView("processing");
    timer.current = setTimeout(() => setView("review"), 1600);
  };

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          회의록
        </h1>
        <p className="admin-page__lede">
          음성을 업로드하면 STT·요약·결정·액션아이템을 자동 생성합니다. 검수 후 확정하세요.
        </p>
      </header>

      <main className="mtg-main">
        {view === "upload" ? (
          <div className="mtg-center">
            <div className="mtg-upload">
              <span className="mtg-upload__icon" aria-hidden="true">
                🎙
              </span>
              <div className="mtg-upload__title">회의 음성 파일을 올려주세요</div>
              <div className="mtg-upload__hint">
                MP3 · M4A · WAV · 최대 200MB. 입대의·관리 회의 녹음.
              </div>
              <button type="button" className="btn btn--primary" onClick={start}>
                파일 선택 후 분석 시작
              </button>
            </div>
          </div>
        ) : null}

        {view === "processing" ? (
          <div className="mtg-center">
            <div className="surface-card mtg-processing">
              <div className="mtg-processing__head" role="status" aria-live="polite">
                <span className="mtg-processing__mark" aria-hidden="true">
                  L
                </span>
                <div className="mtg-processing__title">음성을 텍스트로 변환하고 요약하는 중…</div>
              </div>
              <div className="mtg-steps">
                <div className="mtg-step mtg-step--done">
                  <span aria-hidden="true">✓</span> 음성 업로드 완료 (42:18)
                </div>
                <div className="mtg-step mtg-step--done">
                  <span aria-hidden="true">✓</span> 화자 분리 · STT 변환 완료
                </div>
                <div className="mtg-step mtg-step--active">
                  <span aria-hidden="true" className="mtg-step__spin">
                    ↻
                  </span>{" "}
                  요약·결정·액션아이템 추출 중
                </div>
              </div>
              <Skeleton height="14px" width="90%" style={{ marginTop: "var(--space-6)" }} />
              <Skeleton height="14px" width="75%" style={{ marginTop: "var(--space-2)" }} />
            </div>
          </div>
        ) : null}

        {view === "review" ? (
          <div className="mtg-review">
            <div className="mtg-transcript">
              <div className="mtg-transcript__head">
                <h2 className="mtg-transcript__title">전체 녹취 (STT)</h2>
                <span className="mtg-transcript__meta">5월 입대의 정기회의 · 42분</span>
              </div>
              <div className="surface-card mtg-transcript__body">
                {TRANSCRIPT.map((t) => (
                  <div key={t.time} className="mtg-line">
                    <span className="mtg-line__time">{t.time}</span>
                    <div className="mtg-line__text">
                      <span className="mtg-line__speaker">{t.speaker}</span> {t.text}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <aside className="mtg-summary">
              <div className="mtg-summary__scroll">
                <span className="mtg-badge">
                  <span aria-hidden="true">✨</span> AI 생성 · 검수 후 확정하세요
                </span>

                <section className="mtg-block">
                  <h3 className="mtg-block__title">요약</h3>
                  <p className="mtg-block__summary">
                    노후 배관 교체 공사 일정과 예산을 논의했습니다. 6월 내 1203동 우선 시행에
                    합의했고, 주민 사전 공지 방식을 확정했습니다.
                  </p>
                </section>

                <section className="mtg-block">
                  <h3 className="mtg-block__title">결정 사항</h3>
                  <ul className="mtg-decisions">
                    {DECISIONS.map((d) => (
                      <li key={d}>
                        <span className="mtg-decisions__check" aria-hidden="true">
                          ✓
                        </span>
                        <span>{d}</span>
                      </li>
                    ))}
                  </ul>
                </section>

                <section className="mtg-block">
                  <h3 className="mtg-block__title">액션 아이템</h3>
                  <div className="mtg-actions">
                    {ACTIONS.map((a) => (
                      <div key={a.task} className="mtg-action">
                        <span className="mtg-action__task">{a.task}</span>
                        <span className="mtg-action__owner">
                          {a.owner} · {a.due}
                        </span>
                      </div>
                    ))}
                  </div>
                </section>
              </div>

              <div className="mtg-summary__footer">
                <button type="button" className="btn btn--secondary mtg-footer__edit">
                  수정
                </button>
                <button type="button" className="btn btn--primary mtg-footer__confirm">
                  검수 완료 · 확정
                </button>
              </div>
            </aside>
          </div>
        ) : null}
      </main>
    </>
  );
}
