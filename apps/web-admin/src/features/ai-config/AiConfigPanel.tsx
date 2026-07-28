"use client";

// AI 설정(SYS_ADMIN) — LLM·임베딩 엔드포인트·튜닝 노브를 화면에서 바꾸고 연결을 확인한다
// (H15-1 · H15-3 확장). 재색인은 저장과 별개 액션이라 폼 밖(ReindexSection).
// 입력은 uncontrolled(ref+defaultValue) — 제출형 폼이라 상태가 필요 없고 IME 조합도 안전하다.

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { ApiError } from "@/lib/api";
import {
  REASONING_EFFORTS,
  TUNING_KNOBS,
  getAiConfig,
  isReindexRequiringChange,
  parseKnob,
  saveAiConfig,
  testAiConfig,
  testEmbeddingConfig,
  validateBaseUrl,
  validateModel,
  validateTuning,
  type AiConfig,
  type AiConfigInput,
  type AiTestResult,
  type EmbeddingInput,
  type EmbeddingTestResult,
  type LlmInput,
  type ReasoningEffort,
  type TuningInput,
  type TuningKnob,
} from "./data";
import { Field, describedBy } from "./Field";
import { EmbeddingSection } from "./EmbeddingSection";
import { TuningSection } from "./TuningSection";
import { ReindexSection } from "./ReindexSection";
import "./ai-config.css";

const TOAST_DURATION_MS = 3200;

const DANGER_CONFIRM_MESSAGE =
  "임베딩·청킹 설정을 바꾸면 저장 후 재색인 전까지 기존 색인과 불일치합니다. 저장할까요?";

const EFFORT_LABEL: Record<ReasoningEffort, string> = {
  none: "none (추론 끄기)",
  low: "low",
  medium: "medium",
  high: "high",
};

type ToastState = { message: string; tone: ToastTone };
type FieldErrors = {
  baseUrl?: string;
  model?: string;
  embedBaseUrl?: string;
  embedModel?: string;
};

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function AiConfigPanel() {
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [knobErrors, setKnobErrors] = useState<Partial<Record<TuningKnob, string>>>({});
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<AiTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const [embedTesting, setEmbedTesting] = useState(false);
  const [embedResult, setEmbedResult] = useState<EmbeddingTestResult | null>(null);
  const [embedError, setEmbedError] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const baseUrlRef = useRef<HTMLInputElement>(null);
  const modelRef = useRef<HTMLInputElement>(null);
  const apiKeyRef = useRef<HTMLInputElement>(null);
  const effortRef = useRef<HTMLSelectElement>(null);
  const embedBaseUrlRef = useRef<HTMLInputElement>(null);
  const embedModelRef = useRef<HTMLInputElement>(null);
  const embedApiKeyRef = useRef<HTMLInputElement>(null);
  const knobInputs = useRef(new Map<TuningKnob, HTMLInputElement | null>());

  const busy = saving || testing || embedTesting;

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

  /** 노브 입력 6종 → 값(빈 칸=null=기본값). 숫자가 아니면 NaN 그대로 넘겨 검증에서 걸린다. */
  function readTuning(): TuningInput {
    const values = {} as TuningInput;
    for (const spec of TUNING_KNOBS) {
      values[spec.key] = parseKnob(knobInputs.current.get(spec.key)?.value ?? "");
    }
    return values;
  }

  /** LLM 4종 읽기 — 빈 키는 "기존 유지"라 전송하지 않는다. errors 는 호출자가 병합한다. */
  function readLlmPart(): { part: LlmInput; errors: FieldErrors } {
    const baseUrl = baseUrlRef.current?.value ?? "";
    const model = modelRef.current?.value ?? "";
    const apiKey = apiKeyRef.current?.value.trim() ?? "";
    const effort = effortRef.current?.value ?? "";
    return {
      part: {
        baseUrl: baseUrl.trim(),
        model: model.trim(),
        apiKey: apiKey === "" ? undefined : apiKey,
        reasoningEffort: effort === "" ? null : (effort as ReasoningEffort),
      },
      errors: {
        baseUrl: validateBaseUrl(baseUrl) ?? undefined,
        model: validateModel(model) ?? undefined,
      },
    };
  }

  function readEmbeddingPart(): { part: EmbeddingInput; errors: FieldErrors } {
    const baseUrl = embedBaseUrlRef.current?.value ?? "";
    const model = embedModelRef.current?.value ?? "";
    const apiKey = embedApiKeyRef.current?.value.trim() ?? "";
    return {
      part: {
        baseUrl: baseUrl.trim(),
        model: model.trim(),
        apiKey: apiKey === "" ? undefined : apiKey,
      },
      errors: {
        embedBaseUrl: validateBaseUrl(baseUrl) ?? undefined,
        embedModel: validateModel(model) ?? undefined,
      },
    };
  }

  /** 폼 전체 → 입력값. 검증 실패면 null(에러 표시). */
  function readForm(): AiConfigInput | null {
    const llm = readLlmPart();
    const embedding = readEmbeddingPart();
    const tuning = readTuning();
    const fieldErrors: FieldErrors = { ...llm.errors, ...embedding.errors };
    const tuningErrors = validateTuning(tuning);
    setErrors(fieldErrors);
    setKnobErrors(tuningErrors);
    if (Object.values(fieldErrors).some(Boolean) || Object.keys(tuningErrors).length > 0) {
      return null;
    }
    return { ...llm.part, embedding: embedding.part, tuning };
  }

  async function submitSave() {
    const input = readForm();
    if (!input || !config) return;
    // 위험 변경(임베딩·청킹)은 재색인 전까지 색인 불일치 — 사람이 한 번 더 확정한다.
    if (isReindexRequiringChange(config, input) && !window.confirm(DANGER_CONFIRM_MESSAGE)) return;
    setSaving(true);
    try {
      const saved = await saveAiConfig(input);
      setConfig(saved);
      // 원문을 화면에 남기지 않는다
      if (apiKeyRef.current) apiKeyRef.current.value = "";
      if (embedApiKeyRef.current) embedApiKeyRef.current.value = "";
      // 저장 전 값의 테스트 결과가 새 설정의 결과처럼 남지 않게
      setTestResult(null);
      setTestError(null);
      setEmbedResult(null);
      setEmbedError(null);
      showToast("AI 설정을 저장했습니다. 이후 요청부터 적용됩니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setSaving(false);
    }
  }

  /** 연결 테스트는 해당 섹션 필드만 검증한다 — 다른 섹션의 미완성 값이 테스트를 막지 않게. */
  async function runTest() {
    const { part, errors: fieldErrors } = readLlmPart();
    setErrors((prev) => ({ ...prev, ...fieldErrors }));
    if (fieldErrors.baseUrl || fieldErrors.model) return;
    setTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      setTestResult(await testAiConfig(part));
    } catch (err) {
      setTestError(errorMessage(err));
    } finally {
      setTesting(false);
    }
  }

  async function runEmbedTest() {
    const { part, errors: fieldErrors } = readEmbeddingPart();
    setErrors((prev) => ({ ...prev, ...fieldErrors }));
    if (fieldErrors.embedBaseUrl || fieldErrors.embedModel) return;
    setEmbedTesting(true);
    setEmbedResult(null);
    setEmbedError(null);
    try {
      setEmbedResult(await testEmbeddingConfig(part));
    } catch (err) {
      setEmbedError(errorMessage(err));
    } finally {
      setEmbedTesting(false);
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
          <div className="ai-cfg__sections">
            <form
              className="ai-cfg__form"
              onSubmit={(e) => {
                e.preventDefault();
                void submitSave();
              }}
              noValidate
            >
              <section className="surface-card ai-cfg" aria-labelledby="ai-cfg-h">
                <h2 id="ai-cfg-h" className="ai-cfg__title">
                  LLM 엔드포인트
                </h2>
                <p className="ai-cfg__lede">
                  어시스턴트가 사용하는 OpenAI-호환 엔드포인트입니다. 저장하면 서버 재시작 없이 이후
                  요청부터 적용됩니다.
                </p>

                {config.source === "env" ? (
                  <p className="ai-cfg__notice">
                    env 기본값 사용 중 — 저장하면 DB 설정이 우선합니다.
                  </p>
                ) : null}

                <div className="ai-cfg__fields">
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
                      className="form-field__input ai-cfg__select"
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
                      disabled={busy}
                      onClick={() => void runTest()}
                    >
                      {testing ? "테스트 중…" : "연결 테스트"}
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
                </div>
              </section>

              <EmbeddingSection
                config={config}
                refs={{ baseUrl: embedBaseUrlRef, model: embedModelRef, apiKey: embedApiKeyRef }}
                errors={{ baseUrl: errors.embedBaseUrl, model: errors.embedModel }}
                testing={embedTesting}
                busy={busy}
                result={embedResult}
                error={embedError}
                onTest={() => void runEmbedTest()}
              />

              <TuningSection config={config} inputs={knobInputs} errors={knobErrors} />

              <div className="ai-cfg__actions ai-cfg__actions--page">
                <Button type="submit" variant="primary" disabled={busy}>
                  {saving ? "저장 중…" : "저장"}
                </Button>
              </div>
            </form>

            <ReindexSection showToast={showToast} />
          </div>
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
