"use client";

import { Button, FormField, Switch } from "@liviq/ui";

import { MAX_BODY, MAX_TITLE, SAVE_MODES, type NoticeFormErrors, type NoticeFormValues } from "./data";

interface NoticeFormProps {
  values: NoticeFormValues;
  errors: NoticeFormErrors;
  disabled: boolean;
  submitting: boolean;
  submitLabel: string;
  /** 발행된 공지 수정 — 저장 방식(역행) 선택을 숨기고 제목·본문·고정만 편집. */
  publishedLock: boolean;
  onChange: (patch: Partial<NoticeFormValues>) => void;
  onSubmit: () => void;
}

export function NoticeForm({
  values,
  errors,
  disabled,
  submitting,
  submitLabel,
  publishedLock,
  onChange,
  onSubmit,
}: NoticeFormProps) {
  return (
    <form
      className="surface-card notice-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled) onSubmit();
      }}
    >
      <FormField
        label="제목"
        value={values.title}
        maxLength={MAX_TITLE}
        error={errors.title}
        disabled={disabled}
        placeholder="예: 정기 소독 안내"
        onChange={(event) => onChange({ title: event.target.value })}
      />

      <div className="notice-field">
        <label className="form-field__label" htmlFor="notice-body">
          본문
        </label>
        <textarea
          id="notice-body"
          className="notice-textarea"
          rows={12}
          value={values.body}
          maxLength={MAX_BODY}
          disabled={disabled}
          aria-invalid={errors.body ? true : undefined}
          aria-describedby={errors.body ? "notice-body-error" : undefined}
          placeholder="입주민에게 전달할 내용을 입력하세요."
          onChange={(event) => onChange({ body: event.target.value })}
        />
        {errors.body ? (
          <div id="notice-body-error" className="form-field__error">
            {errors.body}
          </div>
        ) : null}
      </div>

      <div className="notice-toggle">
        <Switch
          checked={values.pinned}
          label="상단 고정"
          onChange={(next) => onChange({ pinned: next })}
        />
        <span className="notice-toggle__text">
          <span className="notice-toggle__label">상단 고정</span>
          <span className="notice-toggle__help">목록·입주민 화면 맨 위에 고정합니다.</span>
        </span>
      </div>

      {publishedLock ? (
        <p className="notice-locknote" role="note">
          <span aria-hidden="true">🔒</span> 이미 발행된 공지입니다. 제목·본문·고정은 수정할 수
          있지만 임시저장·예약 상태로는 되돌릴 수 없습니다.
        </p>
      ) : (
        <fieldset className="notice-savemode" disabled={disabled}>
          <legend className="form-field__label">저장 방식</legend>
          <div className="notice-savemode__opts">
            {SAVE_MODES.map((mode) => (
              <label key={mode.id} className="notice-radio" data-active={values.saveMode === mode.id || undefined}>
                <input
                  type="radio"
                  name="notice-savemode"
                  value={mode.id}
                  checked={values.saveMode === mode.id}
                  onChange={() => onChange({ saveMode: mode.id })}
                />
                <span className="notice-radio__body">
                  <span className="notice-radio__label">{mode.label}</span>
                  <span className="notice-radio__help">{mode.help}</span>
                </span>
              </label>
            ))}
          </div>

          {values.saveMode === "scheduled" ? (
            <div className="notice-field notice-schedule">
              <label className="form-field__label" htmlFor="notice-scheduled">
                예약 발행 시각
              </label>
              <input
                id="notice-scheduled"
                type="datetime-local"
                className="notice-input"
                value={values.scheduledAt}
                aria-invalid={errors.scheduledAt ? true : undefined}
                aria-describedby={errors.scheduledAt ? "notice-scheduled-error" : undefined}
                onChange={(event) => onChange({ scheduledAt: event.target.value })}
              />
              {errors.scheduledAt ? (
                <div id="notice-scheduled-error" className="form-field__error">
                  {errors.scheduledAt}
                </div>
              ) : null}
            </div>
          ) : null}
        </fieldset>
      )}

      <div className="notice-form__actions">
        <Button type="submit" variant="primary" disabled={disabled}>
          {submitting ? "저장 중…" : submitLabel}
        </Button>
      </div>
    </form>
  );
}
