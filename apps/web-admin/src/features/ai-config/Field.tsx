// AI 설정 폼의 필드 래퍼 — 섹션 컴포넌트들이 공유한다(H15-3).
// @liviq/ui FormField와 같은 마크업·클래스를 쓰되 ref를 넘길 수 있게 컨트롤을 children으로 받는다.

import type { ReactNode } from "react";

interface FieldProps {
  id: string;
  label: string;
  required?: boolean;
  help?: string;
  error?: string;
  children: ReactNode;
}

export function Field({ id, label, required, help, error, children }: FieldProps) {
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
export function describedBy(id: string, hasHelp: boolean, error?: string): string | undefined {
  if (error) return `${id}-error`;
  return hasHelp ? `${id}-help` : undefined;
}
