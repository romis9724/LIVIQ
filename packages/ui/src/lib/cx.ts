/** 조건부 className 결합 — falsy 값은 무시한다. */
export type ClassValue = string | false | null | undefined;

export function cx(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
