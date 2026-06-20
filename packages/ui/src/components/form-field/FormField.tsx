import type { InputHTMLAttributes } from "react";
import { useId } from "react";
import { cx } from "../../lib/cx";

export interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  /** 도움말 (정상 상태). */
  help?: string;
  /** 에러 메시지 (있으면 aria-invalid + 도움말 대체). */
  error?: string;
  /** 래퍼 className. */
  wrapperClassName?: string;
}

/**
 * 라벨·도움말·에러를 aria로 연결한 폼 필드. 입력 폰트 16px로 모바일 자동확대 방지.
 */
export function FormField({
  label,
  help,
  error,
  id,
  wrapperClassName,
  className,
  ...rest
}: FormFieldProps) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const describedById = error ? `${fieldId}-error` : help ? `${fieldId}-help` : undefined;

  return (
    <div className={cx("form-field", wrapperClassName)}>
      <label className="form-field__label" htmlFor={fieldId}>
        {label}
      </label>
      <input
        id={fieldId}
        className={cx("form-field__input", className)}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedById}
        {...rest}
      />
      {error ? (
        <div id={`${fieldId}-error`} className="form-field__error">
          {error}
        </div>
      ) : help ? (
        <div id={`${fieldId}-help`} className="form-field__help">
          {help}
        </div>
      ) : null}
    </div>
  );
}
