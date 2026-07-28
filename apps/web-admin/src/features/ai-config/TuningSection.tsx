// 튜닝 노브 섹션(H15-3) — 노브 6종 숫자 입력. 빈 칸 = 기본값 사용(서버 컬럼 NULL).
// 값은 부모가 refs 맵에서 읽는다(페이지 전체 1폼).

import type { RefObject } from "react";
import { TUNING_KNOBS, type AiConfig, type TuningKnob } from "./data";
import { Field, describedBy } from "./Field";

interface TuningSectionProps {
  config: AiConfig;
  /** 노브별 입력 엘리먼트 — 부모가 소유하고 여기서 등록만 한다. */
  inputs: RefObject<Map<TuningKnob, HTMLInputElement | null>>;
  errors: Partial<Record<TuningKnob, string>>;
}

export function TuningSection({ config, inputs, errors }: TuningSectionProps) {
  return (
    <section className="surface-card ai-cfg" aria-labelledby="ai-cfg-tune-h">
      <h2 id="ai-cfg-tune-h" className="ai-cfg__title">
        튜닝
      </h2>
      <p className="ai-cfg__lede">
        검색·생성 품질 노브입니다. 비워두면 기본값을 사용하며, 저장하면 이후 요청부터 적용됩니다.
      </p>

      <div className="ai-cfg__fields ai-cfg__fields--grid">
        {TUNING_KNOBS.map((spec) => {
          const id = `ai-cfg-knob-${spec.field}`;
          const error = errors[spec.key];
          return (
            <Field
              key={spec.key}
              id={id}
              label={spec.label}
              help={`기본값 ${spec.fallback} · 범위 ${spec.min}~${spec.max} · 비우면 기본값`}
              error={error}
            >
              <input
                ref={(element) => {
                  inputs.current?.set(spec.key, element);
                }}
                id={id}
                className="form-field__input"
                type="number"
                inputMode="decimal"
                min={spec.min}
                max={spec.max}
                step={spec.step}
                autoComplete="off"
                defaultValue={String(config.tuning[spec.key])}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy(id, true, error)}
              />
            </Field>
          );
        })}
      </div>
    </section>
  );
}
