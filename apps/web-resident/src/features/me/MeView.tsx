"use client";

import { useState } from "react";
import { Switch } from "@liviq/ui";
import "./me.css";

const ACTIVITIES = [
  { icon: "💬", title: "AI 비서 — 인테리어 공사 가능 시간 질문", meta: "오늘 09:12" },
  { icon: "🛠", title: "민원 접수 — 1203동 엘리베이터 소음", meta: "2일 전" },
  { icon: "🧾", title: "관리비 6월분 자동납부 등록", meta: "1주 전" },
] as const;

type SettingKey = "push" | "ai" | "dark";
type ConsentKey = "quality" | "alerts";

export function MeView() {
  const [settings, setSettings] = useState<Record<SettingKey, boolean>>({
    push: true,
    ai: true,
    dark: false,
  });
  const [consent, setConsent] = useState<Record<ConsentKey, boolean>>({
    quality: true,
    alerts: true,
  });

  const toggleSetting = (key: SettingKey) =>
    setSettings((prev) => ({ ...prev, [key]: !prev[key] }));
  const toggleConsent = (key: ConsentKey) =>
    setConsent((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <main id="main" className="me">
      <div className="me-profile">
        <span className="me-profile__avatar" aria-hidden="true">
          홍
        </span>
        <div>
          <div className="me-profile__name">홍*동님</div>
          <div className="me-profile__sub">1203동 1502호 · 입주민 인증됨</div>
        </div>
      </div>

      <section className="me-section">
        <h2 className="me-section__title">활동 이력</h2>
        <div className="me-group">
          {ACTIVITIES.map((a) => (
            <a key={a.title} href="#" className="me-row me-row--link">
              <span className="me-row__icon" aria-hidden="true">
                {a.icon}
              </span>
              <span className="me-row__body">
                <span className="me-row__title">{a.title}</span>
                <span className="me-row__meta">{a.meta}</span>
              </span>
              <span aria-hidden="true" className="me-row__chevron">
                ›
              </span>
            </a>
          ))}
        </div>
      </section>

      <section className="me-section">
        <h2 className="me-section__title">설정</h2>
        <div className="me-group">
          <SettingToggle label="알림 수신" checked={settings.push} onChange={() => toggleSetting("push")} />
          <SettingToggle
            label="AI 추천 질문 표시"
            checked={settings.ai}
            onChange={() => toggleSetting("ai")}
          />
          <SettingToggle
            label="다크 모드 (베타)"
            checked={settings.dark}
            onChange={() => toggleSetting("dark")}
          />
          <a href="#" className="me-row me-row--link">
            <span className="me-row__label">언어 · 글자 크기</span>
            <span className="me-row__value">한국어 · 보통</span>
            <span aria-hidden="true" className="me-row__chevron">
              ›
            </span>
          </a>
        </div>
      </section>

      <section className="me-section">
        <h2 className="me-section__title">개인정보</h2>
        <div className="me-privacy">
          <div className="me-privacy__intro">
            <span aria-hidden="true" className="me-privacy__lock">
              🔒
            </span>
            <p>
              이름·연락처 등 개인정보는 화면과 담당자 전달 시 자동 마스킹됩니다. 예: 홍*동 ·
              010-****-1234
            </p>
          </div>
          <div className="me-consent">
            <div className="me-consent__row">
              <span>AI 응대 품질 개선을 위한 대화 활용 동의</span>
              <Switch
                label="대화 활용 동의"
                checked={consent.quality}
                onChange={() => toggleConsent("quality")}
              />
            </div>
            <div className="me-consent__row">
              <span>단지 공지·관리비 알림 수신 동의</span>
              <Switch
                label="알림 수신 동의"
                checked={consent.alerts}
                onChange={() => toggleConsent("alerts")}
              />
            </div>
          </div>
          <a href="#" className="me-privacy__link">
            개인정보 처리방침 보기 →
          </a>
        </div>
        <button type="button" className="me-logout">
          로그아웃
        </button>
      </section>
    </main>
  );
}

function SettingToggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: () => void;
}) {
  return (
    <div className="me-row">
      <span className="me-row__label">{label}</span>
      <Switch label={label} checked={checked} onChange={onChange} />
    </div>
  );
}
