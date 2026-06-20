import type { Metadata } from "next";
import Link from "next/link";
import {
  Button,
  CitationCard,
  ConfidenceBadge,
  EmptyState,
  FeedbackButtons,
  FormField,
  StatusPill,
  SurfaceCard,
} from "@liviq/ui";
import { DialogDemo } from "./DialogDemo";
import "./foundation.css";

export const metadata: Metadata = {
  title: "파운데이션",
  description: "LIVIQ 디자인 토큰과 핵심 컴포넌트 — Trustworthy Utility.",
};

const SURFACE_SWATCHES = [
  { name: "surface", bg: "var(--color-surface)", note: "99% 0 0", border: true },
  { name: "surface-sunken", bg: "var(--color-surface-sunken)", note: "97% .005 250", border: true },
  { name: "text", bg: "var(--color-text)", note: "22% .02 250", border: false },
  { name: "text-muted", bg: "var(--color-text-muted)", note: "50% .02 250", border: false },
] as const;

const SEMANTIC_SWATCHES = [
  { name: "accent", bg: "var(--color-accent)", note: "행동·링크", border: false },
  { name: "success", bg: "var(--color-success)", note: "답변됨·완료", border: false },
  { name: "warning", bg: "var(--color-warning)", note: "검토 필요", border: false },
  { name: "danger", bg: "var(--color-danger)", note: "장애·반려", border: false },
  { name: "citation", bg: "var(--color-citation)", note: "출처 카드 배경", border: true },
] as const;

const RHYTHM = [
  { n: "2", w: "var(--space-2)" },
  { n: "4", w: "var(--space-4)" },
  { n: "6", w: "var(--space-6)" },
  { n: "8", w: "var(--space-8)" },
  { n: "12", w: "var(--space-12)" },
] as const;

const RADII = [
  { label: "sm", radius: "var(--radius-sm)" },
  { label: "md", radius: "var(--radius-md)" },
  { label: "lg", radius: "var(--radius-lg)" },
] as const;

export default function FoundationPage() {
  return (
    <main id="main" className="fnd">
      <header className="fnd__header">
        <div className="fnd__brand">
          <span className="fnd__logo" aria-hidden="true">
            L
          </span>
          <span className="fnd__wordmark">LIVIQ</span>
          <span className="fnd__version">Foundation · v0.1</span>
        </div>
        <h1 className="fnd__title">디자인 파운데이션 &amp; 핵심 컴포넌트</h1>
        <p className="fnd__lede">
          콘셉트는 <strong>Trustworthy Utility</strong> — 차분하고 명료하며 신뢰감 있는 라이트 테마.
          AI는 마법이 아니라 <strong>근거를 보여주는 도구</strong>로 표현합니다. 모든 AI 답변에는
          출처 카드가 함께 따라갑니다.
        </p>
        <Link className="fnd__back" href="/">
          ← 전체 화면으로
        </Link>
      </header>

      {/* 색상 */}
      <section className="fnd__section" aria-labelledby="colors-heading">
        <div className="fnd__section-head">
          <h2 id="colors-heading" className="fnd__section-title">
            색상
          </h2>
          <span className="fnd__section-meta">oklch · 토큰만 사용</span>
        </div>
        <SurfaceCard>
          <div className="fnd__group-label">표면 · 텍스트</div>
          <div className="swatch-grid">
            {SURFACE_SWATCHES.map((s) => (
              <div className="swatch" key={s.name}>
                <div
                  className="swatch__chip"
                  style={{ background: s.bg, borderBottom: s.border ? undefined : "none" }}
                />
                <div className="swatch__body">
                  <div className="swatch__name">{s.name}</div>
                  <div className="swatch__note">{s.note}</div>
                </div>
              </div>
            ))}
          </div>
          <div className="fnd__group-label">강조 · 의미</div>
          <div className="swatch-grid">
            {SEMANTIC_SWATCHES.map((s) => (
              <div className="swatch" key={s.name}>
                <div className="swatch__chip" style={{ background: s.bg }} />
                <div className="swatch__body">
                  <div className="swatch__name">{s.name}</div>
                  <div className="swatch__note">{s.note}</div>
                </div>
              </div>
            ))}
          </div>
        </SurfaceCard>
      </section>

      {/* 타이포그래피 */}
      <section className="fnd__section" aria-labelledby="type-heading">
        <div className="fnd__section-head">
          <h2 id="type-heading" className="fnd__section-title">
            타이포그래피
          </h2>
          <span className="fnd__section-meta">system-ui · 위계는 scale 대비로</span>
        </div>
        <SurfaceCard>
          <div className="type-row">
            <span className="type-row__tag">title · 700</span>
            <span className="type-sample--title">관리비가 왜 올랐나요?</span>
          </div>
          <div className="type-row">
            <span className="type-row__tag">lg · 600</span>
            <span className="type-sample--lg">단지 공지 3건 · 처리중 민원 1건</span>
          </div>
          <div className="type-row">
            <span className="type-row__tag">base · 400</span>
            <span className="type-sample--base">
              평일 09:00~18:00에 인테리어 공사가 가능하며, 주말과 공휴일에는 제한됩니다.
            </span>
          </div>
          <div className="type-row">
            <span className="type-row__tag">sm · 400 muted</span>
            <span className="type-sample--sm">출처: 관리규약 제32조 · p.12</span>
          </div>
        </SurfaceCard>
      </section>

      {/* 간격·모서리·그림자 */}
      <section className="fnd__section" aria-labelledby="space-heading">
        <div className="fnd__section-head">
          <h2 id="space-heading" className="fnd__section-title">
            간격 · 모서리 · 그림자
          </h2>
        </div>
        <div className="token-grid">
          <SurfaceCard>
            <div className="fnd__group-label">간격 (rhythm)</div>
            <div className="fnd-stack">
              {RHYTHM.map((r) => (
                <div className="rhythm-row" key={r.n} style={{ width: "100%" }}>
                  <span className="rhythm-row__n">{r.n}</span>
                  <div className="rhythm-bar" style={{ width: r.w }} />
                </div>
              ))}
            </div>
          </SurfaceCard>
          <SurfaceCard>
            <div className="fnd__group-label">모서리</div>
            <div className="radii-row">
              {RADII.map((r) => (
                <div key={r.label}>
                  <div className="radii-box" style={{ borderRadius: r.radius }} />
                  <div className="radii-label">{r.label}</div>
                </div>
              ))}
            </div>
          </SurfaceCard>
          <SurfaceCard>
            <div className="fnd__group-label">그림자</div>
            <div className="shadow-demo">shadow-card</div>
          </SurfaceCard>
        </div>
      </section>

      {/* 핵심 컴포넌트 */}
      <section className="fnd__section" aria-labelledby="comp-heading">
        <div className="fnd__section-head">
          <h2 id="comp-heading" className="fnd__section-title">
            핵심 컴포넌트
          </h2>
          <span className="fnd__section-meta">신뢰를 만드는 빌딩 블록</span>
        </div>

        <SurfaceCard style={{ marginBottom: "var(--space-4)" }}>
          <div className="comp-card__name">Button</div>
          <div className="comp-card__note">최소 터치 영역 44px · 키보드 포커스 링</div>
          <div className="fnd-row">
            <Button variant="primary">담당자 연결</Button>
            <Button variant="secondary">다시 묻기</Button>
            <Button variant="ghost">원문 보기</Button>
            <Button variant="danger">반려</Button>
            <Button variant="secondary" disabled>
              발송됨
            </Button>
          </div>
        </SurfaceCard>

        <div className="comp-grid">
          <SurfaceCard>
            <div className="comp-card__name">CitationCard</div>
            <div className="comp-card__note">모든 AI 답변에 항상 동반</div>
            <CitationCard
              title="관리규약 제32조 (공사 시간 제한)"
              meta="12페이지 · 2024.03 개정본"
              href="#"
            />
          </SurfaceCard>
          <SurfaceCard>
            <div className="comp-card__name">ConfidenceBadge</div>
            <div className="comp-card__note">색 + 아이콘 + 라벨 (색만으로 전달 금지)</div>
            <div className="fnd-stack">
              <ConfidenceBadge status="answered" />
              <ConfidenceBadge status="review" />
              <ConfidenceBadge status="handoff" />
            </div>
          </SurfaceCard>
        </div>

        <div className="comp-grid">
          <SurfaceCard>
            <div className="comp-card__name">StatusPill</div>
            <div className="comp-card__note">민원·시설 상태</div>
            <div className="fnd-row">
              <StatusPill status="received" />
              <StatusPill status="progress" />
              <StatusPill status="done" />
              <StatusPill status="fault" />
            </div>
          </SurfaceCard>
          <SurfaceCard>
            <div className="comp-card__name">FeedbackButtons</div>
            <div className="comp-card__note">답변 품질 신호 수집</div>
            <FeedbackButtons />
          </SurfaceCard>
        </div>

        <div className="comp-grid">
          <SurfaceCard>
            <div className="comp-card__name">FormField</div>
            <FormField
              label="민원 제목"
              placeholder="예: 1234동 엘리베이터 소음"
              help="개인정보는 자동으로 마스킹됩니다."
            />
          </SurfaceCard>
          <SurfaceCard>
            <div className="comp-card__name">EmptyState</div>
            <EmptyState
              icon="🗂️"
              title="아직 접수한 민원이 없어요"
              description="불편한 점이 있으면 사진과 함께 접수해 주세요."
            />
          </SurfaceCard>
        </div>

        <div className="comp-grid">
          <SurfaceCard>
            <div className="comp-card__name">Toast · Dialog</div>
            <div className="comp-card__note">위험 액션(발송)은 확인 다이얼로그 후 실행</div>
            <DialogDemo />
          </SurfaceCard>
        </div>
      </section>

      <footer className="fnd__footer">
        다음 단계는 P0 화면 — 입주민 <strong>AI 비서</strong>·<strong>홈</strong>, 관리자{" "}
        <strong>AI 검수 큐</strong>·<strong>공지 초안</strong>입니다.
      </footer>
    </main>
  );
}
