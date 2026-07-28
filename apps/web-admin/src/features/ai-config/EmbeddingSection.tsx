// 임베딩 백엔드 섹션(H15-3) — base URL·모델·키 + 차원 실측 연결 테스트.
// 입력값은 부모(AiConfigPanel)가 ref로 읽어 한 번에 저장한다(페이지 전체 1폼).

import type { RefObject } from "react";
import { Button } from "@liviq/ui";
import { REQUIRED_EMBEDDING_DIM, type AiConfig, type EmbeddingTestResult } from "./data";
import { Field, describedBy } from "./Field";

export interface EmbeddingRefs {
  baseUrl: RefObject<HTMLInputElement | null>;
  model: RefObject<HTMLInputElement | null>;
  apiKey: RefObject<HTMLInputElement | null>;
}

interface EmbeddingSectionProps {
  config: AiConfig;
  refs: EmbeddingRefs;
  errors: { baseUrl?: string; model?: string };
  testing: boolean;
  busy: boolean;
  result: EmbeddingTestResult | null;
  error: string | null;
  onTest: () => void;
}

/** 차원이 스키마와 다르면 응답이 ok:true여도 실패로 읽는다(저장이 422로 막히는 값). */
export function isEmbeddingDimOk(result: EmbeddingTestResult): boolean {
  return result.ok && result.dimensions === REQUIRED_EMBEDDING_DIM;
}

export function EmbeddingSection({
  config,
  refs,
  errors,
  testing,
  busy,
  result,
  error,
  onTest,
}: EmbeddingSectionProps) {
  const keyHelp = config.embeddingApiKeyMasked
    ? `현재 키 ${config.embeddingApiKeyMasked} — 비워두면 기존 키를 유지합니다.`
    : "저장된 키가 없습니다. 인증이 필요 없는 엔드포인트라면 비워두세요.";

  return (
    <section className="surface-card ai-cfg" aria-labelledby="ai-cfg-embed-h">
      <h2 id="ai-cfg-embed-h" className="ai-cfg__title">
        임베딩
      </h2>
      <p className="ai-cfg__lede">
        문서를 벡터로 만드는 임베딩 엔드포인트입니다. 차원은 {REQUIRED_EMBEDDING_DIM}로 고정입니다.
      </p>

      <p className="ai-cfg__notice ai-cfg__notice--warn">
        임베딩 설정을 바꾸면 문서 전량 재색인이 필요합니다.
      </p>

      {config.embeddingSource === "env" ? (
        <p className="ai-cfg__notice">
          임베딩은 env 기본값 사용 중 — 저장하면 DB 설정이 우선합니다.
        </p>
      ) : null}

      <div className="ai-cfg__fields">
        <Field id="ai-cfg-embed-url" label="임베딩 base URL" required error={errors.baseUrl}>
          <input
            ref={refs.baseUrl}
            id="ai-cfg-embed-url"
            className="form-field__input"
            type="url"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            defaultValue={config.embeddingBaseUrl}
            placeholder="http://localhost:11434/v1"
            aria-required="true"
            aria-invalid={errors.baseUrl ? true : undefined}
            aria-describedby={describedBy("ai-cfg-embed-url", false, errors.baseUrl)}
          />
        </Field>

        <Field id="ai-cfg-embed-model" label="임베딩 모델명" required error={errors.model}>
          <input
            ref={refs.model}
            id="ai-cfg-embed-model"
            className="form-field__input"
            type="text"
            autoComplete="off"
            spellCheck={false}
            defaultValue={config.embeddingModel}
            placeholder="bge-m3"
            aria-required="true"
            aria-invalid={errors.model ? true : undefined}
            aria-describedby={describedBy("ai-cfg-embed-model", false, errors.model)}
          />
        </Field>

        <Field id="ai-cfg-embed-key" label="임베딩 API 키" help={keyHelp}>
          <input
            ref={refs.apiKey}
            id="ai-cfg-embed-key"
            className="form-field__input"
            type="password"
            autoComplete="off"
            placeholder={config.embeddingApiKeyMasked ?? "키 없음"}
            aria-describedby={describedBy("ai-cfg-embed-key", true)}
          />
        </Field>

        <div className="ai-cfg__actions">
          <Button type="button" variant="secondary" disabled={busy} onClick={onTest}>
            {testing ? "테스트 중…" : "임베딩 연결 테스트"}
          </Button>
        </div>

        {error ? (
          <p className="ai-cfg__result ai-cfg__result--fail" role="alert">
            연결 테스트 실패 — {error}
          </p>
        ) : result ? (
          <p
            className={`ai-cfg__result ai-cfg__result--${isEmbeddingDimOk(result) ? "ok" : "fail"}`}
            role="status"
          >
            {result.ok
              ? `응답 OK · ${result.latencyMs}ms · ${result.model} · ${result.dimensions}차원`
              : `연결 테스트 실패 — ${result.error ?? "원인을 알 수 없습니다."}`}
            {result.ok && !isEmbeddingDimOk(result)
              ? ` — ${REQUIRED_EMBEDDING_DIM}차원 필요(이 모델은 저장할 수 없습니다)`
              : ""}
          </p>
        ) : null}
      </div>
    </section>
  );
}
