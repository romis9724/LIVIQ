import { describe, it, expect } from "vitest";

import {
  MIN_SIGNUP_AGE,
  VALID_INVITE_CODE,
  fullAge,
  isUnderMinAge,
  isValidInviteCode,
  maskKoreanName,
} from "./logic";

describe("isValidInviteCode", () => {
  it("데모 코드 LIVIQ1은 유효하다", () => {
    expect(isValidInviteCode(VALID_INVITE_CODE)).toBe(true);
  });

  it("공백·소문자를 정규화해 비교한다", () => {
    expect(isValidInviteCode("  liviq1 ")).toBe(true);
  });

  it("다른 코드는 무효다", () => {
    expect(isValidInviteCode("ABC123")).toBe(false);
    expect(isValidInviteCode("")).toBe(false);
  });
});

describe("fullAge", () => {
  const today = new Date(2026, 6, 13); // 2026-07-13 (month is 0-based)

  it("생일이 지났으면 온전한 나이", () => {
    expect(fullAge("2000-01-01", today)).toBe(26);
  });

  it("생일 전이면 한 살 적다", () => {
    expect(fullAge("2000-12-31", today)).toBe(25);
  });

  it("생일 당일은 나이가 오른 것으로 본다", () => {
    expect(fullAge("2000-07-13", today)).toBe(26);
  });

  it("형식이 잘못되면 null", () => {
    expect(fullAge("not-a-date", today)).toBeNull();
    expect(fullAge("", today)).toBeNull();
  });
});

describe("isUnderMinAge (만 14세 게이트)", () => {
  const today = new Date(2026, 6, 13); // 2026-07-13

  it("14번째 생일 하루 전이면 만 13세 → 차단", () => {
    expect(isUnderMinAge("2012-07-14", today)).toBe(true);
  });

  it("14번째 생일 당일이면 만 14세 → 허용", () => {
    expect(isUnderMinAge("2012-07-13", today)).toBe(false);
  });

  it("14번째 생일 다음 날이면 만 14세 → 허용", () => {
    expect(isUnderMinAge("2012-07-12", today)).toBe(false);
  });

  it("명백한 성인은 허용", () => {
    expect(isUnderMinAge("1990-01-01", today)).toBe(false);
  });

  it("미입력·형식오류는 차단하지 않는다(별도 필수검증)", () => {
    expect(isUnderMinAge("", today)).toBe(false);
    expect(isUnderMinAge("bad", today)).toBe(false);
  });

  it("경계값 상수와 일치한다", () => {
    expect(MIN_SIGNUP_AGE).toBe(14);
  });
});

describe("maskKoreanName", () => {
  it("세 글자는 가운데를 가린다", () => {
    expect(maskKoreanName("홍길동")).toBe("홍*동");
  });

  it("네 글자는 가운데 둘을 가린다", () => {
    expect(maskKoreanName("남궁민수")).toBe("남**수");
  });

  it("두 글자는 끝을 가린다", () => {
    expect(maskKoreanName("김수")).toBe("김*");
  });

  it("한 글자·공백은 그대로", () => {
    expect(maskKoreanName("홍")).toBe("홍");
    expect(maskKoreanName("  홍길동  ")).toBe("홍*동");
  });
});
