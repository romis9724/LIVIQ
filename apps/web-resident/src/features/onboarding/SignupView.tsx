"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Button, FormField } from "@liviq/ui";
import { ApiError, submitProfile } from "@/lib/api";
import { buildProfilePayload, isUnderMinAge, isValidInviteCode } from "./logic";
import "./onboarding.css";

/** 동의받은 개인정보 처리방침 버전. FR-ONB: policy_version 기록 대상. */
const POLICY_VERSION = "2026-07";

const DONG_OPTIONS = ["101", "102", "103"] as const;

/** 1~15층 × 1~2호 → 101 … 1502. */
const HO_OPTIONS: readonly string[] = Array.from({ length: 15 }, (_, floorIdx) =>
  [1, 2].map((unit) => String((floorIdx + 1) * 100 + unit)),
).flat();

type Step = 1 | 2;

interface Consents {
  privacy: boolean;
  alerts: boolean;
}

interface InfoErrors {
  invite?: string;
  name?: string;
  birth?: string;
  dong?: string;
  ho?: string;
}

export function SignupView() {
  const router = useRouter();
  const [step, setStep] = useState<Step>(1);
  const [consents, setConsents] = useState<Consents>({ privacy: false, alerts: false });

  return (
    <main id="main" className="auth-shell">
      <div className="auth-inner">
        <div className="auth-brand auth-brand--sm">
          <span className="auth-brand__logo" aria-hidden="true">
            L
          </span>
          <span className="auth-brand__wordmark">LIVIQ</span>
        </div>

        <ol className="auth-steps" aria-label="가입 단계">
          <li className="auth-step" data-active={step === 1 || undefined} aria-current={step === 1 ? "step" : undefined}>
            <span className="auth-step__num">1</span> 약관 동의
          </li>
          <li className="auth-step" data-active={step === 2 || undefined} aria-current={step === 2 ? "step" : undefined}>
            <span className="auth-step__num">2</span> 정보 입력
          </li>
        </ol>

        {step === 1 ? (
          <ConsentStep
            consents={consents}
            onChange={setConsents}
            onNext={() => setStep(2)}
          />
        ) : (
          <InfoStep
            consents={consents}
            onBack={() => setStep(1)}
            onDone={() => router.push("/pending")}
          />
        )}
      </div>
    </main>
  );
}

function ConsentStep({
  consents,
  onChange,
  onNext,
}: {
  consents: Consents;
  onChange: (next: Consents) => void;
  onNext: () => void;
}) {
  const allChecked = consents.privacy && consents.alerts;

  const toggleAll = () => onChange({ privacy: !allChecked, alerts: !allChecked });

  return (
    <form
      className="auth-form"
      onSubmit={(e) => {
        e.preventDefault();
        onNext();
      }}
    >
      <h1 className="auth-title auth-title--sm">약관에 동의해 주세요</h1>

      <label className="auth-consent auth-consent--all">
        <input type="checkbox" checked={allChecked} onChange={toggleAll} />
        <span className="auth-consent__label">전체 동의</span>
      </label>

      <div className="auth-consent-group">
        <ConsentRow
          checked={consents.privacy}
          onToggle={() => onChange({ ...consents, privacy: !consents.privacy })}
          label={`(필수) 개인정보 수집·이용 동의 v${POLICY_VERSION}`}
        />
        <ConsentRow
          checked={consents.alerts}
          onToggle={() => onChange({ ...consents, alerts: !consents.alerts })}
          label="(선택) 공지·관리비 알림 수신"
        />
      </div>

      <Button type="submit" variant="primary" className="auth-submit" disabled={!consents.privacy}>
        다음
      </Button>
      {!consents.privacy ? (
        <p className="auth-hint" role="status">
          필수 항목에 동의해야 다음 단계로 넘어갈 수 있습니다.
        </p>
      ) : null}
    </form>
  );
}

function ConsentRow({
  checked,
  onToggle,
  label,
}: {
  checked: boolean;
  onToggle: () => void;
  label: string;
}) {
  return (
    <div className="auth-consent">
      <label className="auth-consent__main">
        <input type="checkbox" checked={checked} onChange={onToggle} />
        <span className="auth-consent__label">{label}</span>
      </label>
      <a className="auth-consent__view" href="#" onClick={(e) => e.preventDefault()}>
        보기
      </a>
    </div>
  );
}

function InfoStep({
  consents,
  onBack,
  onDone,
}: {
  consents: Consents;
  onBack: () => void;
  onDone: () => void;
}) {
  const [invite, setInvite] = useState("");
  const [name, setName] = useState("");
  const [birth, setBirth] = useState("");
  const [dong, setDong] = useState("");
  const [ho, setHo] = useState("");
  const [errors, setErrors] = useState<InfoErrors>({});
  const [submitting, setSubmitting] = useState(false);
  // 서버 검증 실패(초대코드·명부·연령 등) 메시지. 최종 판정은 서버(클라 검증은 즉시 피드백 보조).
  const [serverError, setServerError] = useState<string | null>(null);

  const submit = async () => {
    const next: InfoErrors = {};
    if (!isValidInviteCode(invite)) next.invite = "유효하지 않은 초대코드입니다.";
    if (!name.trim()) next.name = "성명을 입력해 주세요.";
    if (!birth) next.birth = "생년월일을 입력해 주세요.";
    else if (isUnderMinAge(birth)) next.birth = "만 14세 미만은 가입할 수 없습니다.";
    if (!dong) next.dong = "동을 선택해 주세요.";
    if (!ho) next.ho = "호를 선택해 주세요.";

    setErrors(next);
    setServerError(null);
    if (Object.keys(next).length > 0) return;

    setSubmitting(true);
    try {
      await submitProfile(
        buildProfilePayload({
          inviteCode: invite,
          name,
          birthDate: birth,
          dong,
          ho,
          privacyConsent: consents.privacy,
          alertsConsent: consents.alerts,
        }),
      );
      onDone();
    } catch (err) {
      // 401 은 apiFetch 가 /login 으로 유도(온보딩 세션 없음). 그 외는 서버 메시지 노출.
      setServerError(
        err instanceof ApiError || err instanceof Error
          ? err.message
          : "가입 신청 중 오류가 발생했습니다.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form
      className="auth-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      noValidate
    >
      <h1 className="auth-title auth-title--sm">입주민 정보를 입력해 주세요</h1>

      <FormField
        label="단지 초대코드"
        value={invite}
        onChange={(e) => setInvite(e.target.value)}
        maxLength={6}
        autoCapitalize="characters"
        placeholder="6자리 코드"
        help="관리사무소에서 받은 코드를 입력하세요. (데모: LIVIQ1)"
        error={errors.invite}
        wrapperClassName="auth-field"
      />

      <FormField
        label="성명"
        value={name}
        onChange={(e) => setName(e.target.value)}
        autoComplete="name"
        error={errors.name}
        wrapperClassName="auth-field"
      />

      <FormField
        label="생년월일"
        type="date"
        value={birth}
        onChange={(e) => setBirth(e.target.value)}
        error={errors.birth}
        wrapperClassName="auth-field"
      />

      <div className="auth-field auth-field--row">
        <SelectField
          id="signup-dong"
          label="동"
          value={dong}
          onChange={setDong}
          options={DONG_OPTIONS}
          placeholder="선택"
          error={errors.dong}
        />
        <SelectField
          id="signup-ho"
          label="호"
          value={ho}
          onChange={setHo}
          options={HO_OPTIONS}
          placeholder="선택"
          error={errors.ho}
        />
      </div>

      {serverError ? (
        <p className="auth-hint auth-hint--error" role="alert">
          {serverError}
        </p>
      ) : null}

      <div className="auth-actions">
        <Button type="button" variant="ghost" onClick={onBack} disabled={submitting}>
          이전
        </Button>
        <Button type="submit" variant="primary" className="auth-submit" disabled={submitting}>
          {submitting ? "신청 중…" : "가입 신청"}
        </Button>
      </div>
    </form>
  );
}

function SelectField({
  id,
  label,
  value,
  onChange,
  options,
  placeholder,
  error,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly string[];
  placeholder: string;
  error?: string;
}) {
  const errorId = useMemo(() => (error ? `${id}-error` : undefined), [error, id]);

  return (
    <div className="auth-select">
      <label className="form-field__label" htmlFor={id}>
        {label}
      </label>
      <select
        id={id}
        className="auth-select__input"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-invalid={error ? true : undefined}
        aria-describedby={errorId}
      >
        <option value="" disabled>
          {placeholder}
        </option>
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
      {error ? (
        <div id={errorId} className="form-field__error">
          {error}
        </div>
      ) : null}
    </div>
  );
}
