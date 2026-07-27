"use client";

// AI 설정(SYS_ADMIN) — LLM 엔드포인트·모델·키를 화면에서 바꾸고 연결을 확인한다(H15-1).
// 입력은 uncontrolled(ref+defaultValue) — 제출형 폼이라 상태가 필요 없고 IME 조합도 안전하다.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Button, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { ApiError } from "@/lib/api";
import {
  REASONING_EFFORTS,
  getAiConfig,
  saveAiConfig,
  testAiConfig,
  validateBaseUrl,
  validateModel,
  type AiConfig,
  type AiConfigInput,
  type AiTestResult,
  type ReasoningEffort,
} from "./data";
import "./ai-config.css";

const TOAST_DURATION_MS = 3200;

const EFFORT_LABEL: Record<ReasoningEffort, string> = {
  none: "none (추론 끄기)",
  low: "low",
  medium: "medium",
  high: "high",
};

type ToastState = { message: string; tone: ToastTone };
type FieldErrors = { baseUrl?: string; model?: string };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface FieldProps {
  id: string;
  label: string;
  required?: boolean;
  help?: string;
  error?: string;
  children: ReactNode;
}

/** @liviq/ui FormField와 같은 마크업·클래스를 쓰되 ref를 넘길 수 있게 컨트롤을 children으로 받는다. */
function Field({ id, label, required, help, error, children }: FieldProps) {
  return (
    <div className="form-field ai-cfg__field">
      <label className="form-field__label" htmlFor={id}>
        {label}
        {required ? <span aria-hidden="true"> *</span> : null}
      </label>
      {children}
      {error ? (
        <div id={`${id}-error`} className="form-field__error">
          {error}
        </div>
      ) : help ? (
        <div id={`${id}-help`} className="form-field__help">
          {help}
        </div>
      ) : null}
    </div>
  );
}

/** 도움말·에러 중 실제로 렌더되는 쪽을 aria-describedby로 연결(FormField와 동일 규칙). */
function describedBy(id: string, hasHelp: boolean, error?: string): string | undefined {
  if (error) return `${id}-error`;
  return hasHelp ? `${id}-help` : undefined;
}

export function AiConfigPanel() {
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<AiTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const baseUrlRef = useRef<HTMLInputElement>(null);
  const modelRef = useRef<HTMLInputElement>(null);
  const apiKeyRef = useRef<HTMLInputElement>(null);
  const effortRef = useRef<HTMLSelectElement>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  useEffect(() => {
    let alive = true;
    void getAiConfig()
      .then((value) => alive && setConfig(value))
      .catch((err) => alive && setLoadError(errorMessage(err)));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  /** 폼 → 입력값. 검증 실패면 null(에러 표시). 빈 키는 "기존 유지"라 전송하지 않는다. */
  function readForm(): AiConfigInput | null {
    const baseUrl = baseUrlRef.current?.value ?? "";
    const model = modelRef.current?.value ?? "";
    const baseUrlError = validateBaseUrl(baseUrl);
    const modelError = validateModel(model);
    setErrors({ baseUrl: baseUrlError ?? undefined, model: modelError ?? undefined });
    if (baseUrlError || modelError) return null;
    const apiKey = apiKeyRef.current?.value.trim() ?? "";
    const effort = effortRef.current?.value ?? "";
    return {
      baseUrl: baseUrl.trim(),
      model: model.trim(),
      apiKey: apiKey === "" ? undefined : apiKey,
      reasoningEffort: effort === "" ? null : (effort as ReasoningEffort),
    };
  }

  async function submitSave() {
    const input = readForm();
    if (!input) return;
    setSaving(true);
    try {
      const saved = await saveAiConfig(input);
      setConfig(saved);
      if (apiKeyRef.current) apiKeyRef.current.value = ""; // 원문을 화면에 남기지 않는다
      setTestResult(null); // 저장 전 값의 테스트 결과가 새 설정의 결과처럼 남지 않게
      setTestError(null);
      showToast("AI 설정을 저장했습니다. 이후 요청부터 적용됩니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setSaving(false);
    }
  }

  async function runTest() {
    const input = readForm();
    if (!input) return;
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      setTestResult(await testAiConfig(input));
    } catch (err) {
      setTestError(errorMessage(err));
    } finally {
      setTesting(false);
    }
  }

  const keyHelp = config?.apiKeyMasked
    ? `현재 키 ${config.apiKeyMasked} — 비워두면 기존 키를 유지합니다.`
    : "저장된 키가 없습니다. 인증이 필요 없는 엔드포인트라면 비워두세요.";

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          AI 설정
        </h1>
      </header>

      <main className="admin-page__main">
        {loadError ? (
          <EmptyState icon="⚠" title="설정을 불러오지 못했습니다" description={loadError} />
        ) : config === null ? (
          <div className="ai-cfg__loading">
            <Skeleton height="360px" />
          </div>
        ) : (
          <section className="surface-card ai-cfg" aria-labelledby="ai-cfg-h">
            <h2 id="ai-cfg-h" className="ai-cfg__title">
              LLM 엔드포인트
            </h2>
            <p className="ai-cfg__lede">
              어시스턴트가 사용하는 OpenAI-호환 엔드포인트입니다. 저장하면 서버 재시작 없이 이후
              요청부터 적용됩니다.
            </p>

            {config.source === "env" ? (
              <p className="ai-cfg__notice">env 기본값 사용 중 — 저장하면 DB 설정이 우선합니다.</p>
            ) : null}

            <form
              className="ai-cfg__form"
              onSubmit={(e) => {
                e.preventDefault();
                void submitSave();
              }}
              noValidate
            >
              <Field id="ai-cfg-base-url" label="base URL" required error={errors.baseUrl}>
                <input
                  ref={baseUrlRef}
                  id="ai-cfg-base-url"
                  className="form-field__input"
                  type="url"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  defaultValue={config.baseUrl}
                  placeholder="http://localhost:11434/v1"
                  aria-required="true"
                  aria-invalid={errors.baseUrl ? true : undefined}
                  aria-describedby={describedBy("ai-cfg-base-url", false, errors.baseUrl)}
                />
              </Field>

              <Field id="ai-cfg-model" label="모델명" required error={errors.model}>
                <input
                  ref={modelRef}
                  id="ai-cfg-model"
                  className="form-field__input"
                  type="text"
                  autoComplete="off"
                  spellCheck={false}
                  defaultValue={config.model}
                  placeholder="llama3.1:8b"
                  aria-required="true"
                  aria-invalid={errors.model ? true : undefined}
                  aria-describedby={describedBy("ai-cfg-model", false, errors.model)}
                />
              </Field>

              <Field id="ai-cfg-api-key" label="API 키" help={keyHelp}>
                <input
                  ref={apiKeyRef}
                  id="ai-cfg-api-key"
                  className="form-field__input"
                  type="password"
                  autoComplete="off"
                  placeholder={config.apiKeyMasked ?? "키 없음"}
                  aria-describedby={describedBy("ai-cfg-api-key", true)}
                />
              </Field>

              <Field
                id="ai-cfg-effort"
                label="reasoning effort"
                help="추론(thinking) 모델에서만 의미가 있습니다. 지원하지 않는 모델이면 없음으로 두세요."
              >
                <select
                  ref={effortRef}
                  id="ai-cfg-effort"
                  className="form-field__input"
                  defaultValue={config.reasoningEffort ?? ""}
                  aria-describedby={describedBy("ai-cfg-effort", true)}
                >
                  <option value="">없음 (모델 기본값)</option>
                  {REASONING_EFFORTS.map((effort) => (
                    <option key={effort} value={effort}>
                      {EFFORT_LABEL[effort]}
                    </option>
                  ))}
                </select>
              </Field>

              <div className="ai-cfg__actions">
                <Button
                  type="button"
                  variant="secondary"
                  disabled={testing || saving}
                  onClick={() => void runTest()}
                >
                  {testing ? "테스트 중…" : "연결 테스트"}
                </Button>
                <Button type="submit" variant="primary" disabled={saving || testing}>
                  {saving ? "저장 중…" : "저장"}
                </Button>
              </div>

              {testError ? (
                <p className="ai-cfg__result ai-cfg__result--fail" role="alert">
                  연결 테스트 실패 — {testError}
                </p>
              ) : testResult ? (
                <p
                  className={`ai-cfg__result ai-cfg__result--${testResult.ok ? "ok" : "fail"}`}
                  role="status"
                >
                  {testResult.ok
                    ? `응답 OK · ${testResult.latencyMs}ms · ${testResult.model}`
                    : `연결 테스트 실패 — ${testResult.error ?? "원인을 알 수 없습니다."}`}
                </p>
              ) : null}
            </form>
          </section>
        )}
      </main>

      {toast ? (
        <div className="ai-cfg__toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}
