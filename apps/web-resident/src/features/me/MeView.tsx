"use client";

import { useEffect, useState } from "react";
import { Skeleton, Switch } from "@liviq/ui";
import { API_BASE_URL } from "@/lib/dev-context";
import { ApiError, getMe, type Me } from "@/lib/api";
import { NotificationInbox } from "./NotificationInbox";
import { accountStatusLabel, roleLabel } from "./logic";
import "./me.css";

/** 로그아웃 — 세션 revoke(멱등) 후 로그인 화면으로. 실패해도 로그인으로 이동. */
async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE_URL}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    window.location.href = "/login";
  }
}

type SettingKey = "push" | "ai" | "dark";

export function MeView() {
  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState(false);
  const [settings, setSettings] = useState<Record<SettingKey, boolean>>({
    push: true,
    ai: true,
    dark: false,
  });

  useEffect(() => {
    let alive = true;
    getMe()
      .then((data) => alive && setMe(data))
      .catch((err) => {
        // 401 은 apiFetch 가 /login 으로 유도. 그 외 오류만 표시.
        if (!alive || (err instanceof ApiError && err.status === 401)) return;
        setMeError(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  const toggleSetting = (key: SettingKey) =>
    setSettings((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <main id="main" className="me">
      <div className="me-profile">
        <span className="me-profile__avatar" aria-hidden="true">
          👤
        </span>
        <div className="me-profile__info">
          {me ? (
            <>
              <div className="me-profile__name">{roleLabel(me.roles)}</div>
              <div className="me-profile__sub">{accountStatusLabel(me.status)}</div>
            </>
          ) : meError ? (
            <div className="me-profile__sub">계정 정보를 불러오지 못했어요.</div>
          ) : (
            <Skeleton height="2.4rem" width="12rem" />
          )}
        </div>
      </div>

      <NotificationInbox />

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
          {/* 동의 변경 API 는 백로그 — 가입 시 받은 동의를 표시만 한다. */}
          <div className="me-consent">
            <div className="me-consent__row">
              <span>AI 응대 품질 개선을 위한 대화 활용 동의</span>
              <span className="me-consent__state">가입 시 동의 완료</span>
            </div>
            <div className="me-consent__row">
              <span>단지 공지·관리비 알림 수신 동의</span>
              <span className="me-consent__state">가입 시 동의 완료</span>
            </div>
          </div>
          <a href="#" className="me-privacy__link">
            개인정보 처리방침 보기 →
          </a>
        </div>
        <button type="button" className="me-logout" onClick={() => void logout()}>
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
