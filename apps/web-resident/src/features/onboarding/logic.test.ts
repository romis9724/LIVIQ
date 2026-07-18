import { describe, it, expect } from "vitest";

import type { AppNotification } from "@/lib/api";
import {
  MIN_SIGNUP_AGE,
  accountView,
  buildProfilePayload,
  fullAge,
  isUnderMinAge,
  isValidInviteCode,
  maskKoreanName,
  rejectionReasonFrom,
  rootDestination,
} from "./logic";

describe("isValidInviteCode (형식만 — 유효성은 서버 정본)", () => {
  it("비어있지 않으면 통과한다(단지별 코드는 서버가 검증)", () => {
    expect(isValidInviteCode("LIVIQ1")).toBe(true);
    expect(isValidInviteCode("HANGANG")).toBe(true);
    expect(isValidInviteCode("ABC123")).toBe(true);
  });

  it("빈 값·공백만은 무효다", () => {
    expect(isValidInviteCode("")).toBe(false);
    expect(isValidInviteCode("   ")).toBe(false);
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
    inviteCode: "  liviq1 ",
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

  it("초대코드·성명 공백을 다듬는다", () => {
    const p = buildProfilePayload(base);
    expect(p.invite_code).toBe("liviq1");
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
  it("온보딩 세션은 onboarding", () => {
    expect(accountView({ kind: "onboarding", status: "onboarding" })).toBe("onboarding");
  });

  it("user 세션은 status 를 그대로 매핑한다", () => {
    expect(accountView({ kind: "user", status: "pending" })).toBe("pending");
    expect(accountView({ kind: "user", status: "rejected" })).toBe("rejected");
    expect(accountView({ kind: "user", status: "active" })).toBe("active");
    expect(accountView({ kind: "user", status: "inactive" })).toBe("inactive");
  });

  it("예상 밖 상태는 unknown", () => {
    expect(accountView({ kind: "user", status: "weird" })).toBe("unknown");
  });
});

describe("rootDestination (루트 상태별 라우팅)", () => {
  it("활성 계정은 홈으로", () => {
    expect(rootDestination({ kind: "user", status: "active" })).toBe("/home");
  });

  it("온보딩 세션은 가입 화면으로", () => {
    expect(rootDestination({ kind: "onboarding", status: "onboarding" })).toBe("/onboarding");
  });

  it("대기·반려·비활성·예상밖 상태는 계정 상태 화면으로", () => {
    expect(rootDestination({ kind: "user", status: "pending" })).toBe("/pending");
    expect(rootDestination({ kind: "user", status: "rejected" })).toBe("/pending");
    expect(rootDestination({ kind: "user", status: "inactive" })).toBe("/pending");
    expect(rootDestination({ kind: "user", status: "weird" })).toBe("/pending");
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
