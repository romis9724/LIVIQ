import { describe, it, expect } from "vitest";

import type { AppNotification } from "@/lib/api";
import {
  MIN_PASSWORD_LENGTH,
  MIN_SIGNUP_AGE,
  accountView,
  authedRedirect,
  buildProfilePayload,
  fullAge,
  isUnderMinAge,
  isValidEmail,
  maskKoreanName,
  parseTenantId,
  rejectionReasonFrom,
  rootDestination,
  validateAccountSignup,
  validateNewPassword,
} from "./logic";

describe("isValidEmail", () => {
  it("정상 형식은 유효하다", () => {
    expect(isValidEmail("kim@example.com")).toBe(true);
    expect(isValidEmail("  kim@example.com  ")).toBe(true);
  });

  it("형식이 아니면 무효다", () => {
    expect(isValidEmail("kim@")).toBe(false);
    expect(isValidEmail("kim example.com")).toBe(false);
    expect(isValidEmail("")).toBe(false);
  });
});

describe("parseTenantId (가입 링크 ?t)", () => {
  const uuid = "11111111-2222-3333-4444-555555555555";

  it("UUID 형식이면 공백을 제거해 반환한다", () => {
    expect(parseTenantId(uuid)).toBe(uuid);
    expect(parseTenantId(`  ${uuid}  `)).toBe(uuid);
  });

  it("형식이 아니거나 없으면 null", () => {
    expect(parseTenantId("not-a-uuid")).toBeNull();
    expect(parseTenantId("")).toBeNull();
    expect(parseTenantId(null)).toBeNull();
    expect(parseTenantId(undefined)).toBeNull();
  });
});

describe("validateAccountSignup (계정 가입 검증)", () => {
  const valid = {
    tenantId: "11111111-1111-1111-1111-111111111111",
    email: "kim@example.com",
    password: "verylongpass",
    passwordConfirm: "verylongpass",
  };

  it("정상 입력은 오류 없음", () => {
    expect(validateAccountSignup(valid)).toEqual({});
  });

  it("단지 미선택을 잡는다 (H7-5)", () => {
    expect(validateAccountSignup({ ...valid, tenantId: "" }).tenantId).toBeDefined();
  });

  it("이메일 형식 오류를 잡는다", () => {
    expect(validateAccountSignup({ ...valid, email: "bad" }).email).toBeDefined();
  });

  it(`비밀번호 ${MIN_PASSWORD_LENGTH}자 미만을 잡는다`, () => {
    const short = "a".repeat(MIN_PASSWORD_LENGTH - 1);
    expect(validateAccountSignup({ ...valid, password: short, passwordConfirm: short }).password).toBeDefined();
  });

  it("비밀번호 확인 불일치를 잡는다", () => {
    expect(validateAccountSignup({ ...valid, passwordConfirm: "different123" }).passwordConfirm).toBeDefined();
  });
});

describe("validateNewPassword (재설정 새 비밀번호)", () => {
  it("정상 입력은 오류 없음", () => {
    expect(validateNewPassword("verylongpass", "verylongpass")).toEqual({});
  });

  it("길이 미만·불일치를 각각 잡는다", () => {
    expect(validateNewPassword("short", "short").password).toBeDefined();
    expect(validateNewPassword("verylongpass", "verylongpazz").passwordConfirm).toBeDefined();
  });
});

describe("authedRedirect (로그인 사용자 진입 화면 가드)", () => {
  it("active 는 홈으로", () => {
    expect(authedRedirect("active")).toBe("/home");
  });

  it("registered 는 온보딩으로", () => {
    expect(authedRedirect("registered")).toBe("/onboarding");
  });

  it("그 외 상태는 null(머무름)", () => {
    expect(authedRedirect("pending")).toBeNull();
    expect(authedRedirect("rejected")).toBeNull();
    expect(authedRedirect("inactive")).toBeNull();
    expect(authedRedirect("weird")).toBeNull();
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

describe("buildProfilePayload (폼 → 서버 계약)", () => {
  const base = {
    name: "  김입주 ",
    birthDate: "1990-05-05",
    dong: "101",
    ho: "1002",
    privacyConsent: true,
    alertsConsent: false,
  };

  it("호수 상위 자리에서 층을 파생한다 (1002 → floor 10)", () => {
    const p = buildProfilePayload(base);
    expect(p.unit_no).toBe(1002);
    expect(p.floor).toBe(10);
    expect(p.building_name).toBe("101");
  });

  it("301호는 floor 3 · unit_no 301", () => {
    const p = buildProfilePayload({ ...base, ho: "301" });
    expect(p.floor).toBe(3);
    expect(p.unit_no).toBe(301);
  });

  it("성명 공백을 다듬는다", () => {
    const p = buildProfilePayload(base);
    expect(p.name).toBe("김입주");
  });

  it("필수·선택 동의를 각각 consents 로 담는다", () => {
    const p = buildProfilePayload({ ...base, alertsConsent: true });
    expect(p.consents).toEqual([
      { purpose: "privacy_required", granted: true },
      { purpose: "alerts", granted: true },
    ]);
  });
});

describe("accountView (계정 상태 분기)", () => {
  it("registered(프로필 미제출)는 onboarding", () => {
    expect(accountView({ status: "registered" })).toBe("onboarding");
  });

  it("status 를 그대로 매핑한다", () => {
    expect(accountView({ status: "pending" })).toBe("pending");
    expect(accountView({ status: "rejected" })).toBe("rejected");
    expect(accountView({ status: "active" })).toBe("active");
    expect(accountView({ status: "inactive" })).toBe("inactive");
  });

  it("예상 밖 상태는 unknown", () => {
    expect(accountView({ status: "weird" })).toBe("unknown");
  });
});

describe("rootDestination (루트 상태별 라우팅)", () => {
  it("활성 계정은 홈으로", () => {
    expect(rootDestination({ status: "active" })).toBe("/home");
  });

  it("registered(프로필 미제출)는 가입 화면으로", () => {
    expect(rootDestination({ status: "registered" })).toBe("/onboarding");
  });

  it("대기·반려·비활성·예상밖 상태는 계정 상태 화면으로", () => {
    expect(rootDestination({ status: "pending" })).toBe("/pending");
    expect(rootDestination({ status: "rejected" })).toBe("/pending");
    expect(rootDestination({ status: "inactive" })).toBe("/pending");
    expect(rootDestination({ status: "weird" })).toBe("/pending");
  });
});

describe("rejectionReasonFrom (알림에서 반려 사유)", () => {
  const notif = (over: Partial<AppNotification>): AppNotification => ({
    id: "n",
    type: "approval",
    title: "가입이 거절되었습니다",
    body: null,
    link: null,
    readAt: null,
    createdAt: "2026-07-13T00:00:00Z",
    ...over,
  });

  it("가장 최근 반려 알림의 body 를 반환한다", () => {
    const reason = rejectionReasonFrom([
      notif({ id: "old", body: "예전 사유", createdAt: "2026-07-10T00:00:00Z" }),
      notif({ id: "new", body: "동·호가 명부와 다릅니다", createdAt: "2026-07-13T00:00:00Z" }),
    ]);
    expect(reason).toBe("동·호가 명부와 다릅니다");
  });

  it("body 없는 승인 알림은 무시한다", () => {
    expect(rejectionReasonFrom([notif({ type: "approval", body: null })])).toBeNull();
  });

  it("반려 알림이 없으면 null", () => {
    expect(rejectionReasonFrom([notif({ type: "notice", body: "공지" })])).toBeNull();
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
