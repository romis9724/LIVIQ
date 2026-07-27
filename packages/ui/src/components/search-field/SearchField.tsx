import type { ComponentPropsWithRef } from "react";
import { cx } from "../../lib/cx";

export interface SearchFieldProps extends Omit<ComponentPropsWithRef<"input">, "type"> {
  /** 접근성 이름 (예: "민원 검색"). 시각 라벨은 두지 않는다. */
  label: string;
}

/**
 * 툴바 검색 입력 — 높이 44px, 장식 없음(docs/05 §5A).
 * 한글 IME 조합 씹힘을 피하려면 controlled 대신 `ref` + `onInput`/디바운스로 쓴다.
 */
export function SearchField({ label, className, ...rest }: SearchFieldProps) {
  return <input type="search" aria-label={label} className={cx("search-field", className)} {...rest} />;
}
