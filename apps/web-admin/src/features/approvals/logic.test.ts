import { describe, it, expect } from "vitest";

import {
  summarizeDiff,
  deactivateCandidate,
  validateRoster,
  decideSignup,
  pendingCount,
  maskName,
  maskBirth,
  ROSTER_MAX_BYTES,
  type RosterDiffResult,
  type PendingSignup,
} from "./logic";

const diff: RosterDiffResult = {
  newRegistered: 12,
  matchedKept: 74,
  moveOutCandidates: [
    { id: "m1", unit: "101동 302호", name: "김영희" },
    { id: "m2", unit: "102동 1101호", name: "박철수" },
  ],
};

describe("summarizeDiff", () => {
  it("전출 후보 수를 목록 길이에서 파생한다", () => {
    const s = summarizeDiff(diff);
    expect(s.newRegistered).toBe(12);
    expect(s.matchedKept).toBe(74);
    expect(s.moveOutCandidates).toBe(2);
  });

  it("전출 후보를 비활성화하면 요약 수치가 줄어든다", () => {
    const next = { ...diff, moveOutCandidates: deactivateCandidate(diff.moveOutCandidates, "m1") };
    expect(summarizeDiff(next).moveOutCandidates).toBe(1);
    // 원본 불변
    expect(diff.moveOutCandidates).toHaveLength(2);
  });
});

describe("validateRoster (경계 입력)", () => {
  it("xlsx 파일은 통과", () => {
    expect(validateRoster({ name: "roster.xlsx", size: 1024 })).toBeNull();
  });

  it("다른 확장자는 거절", () => {
    expect(validateRoster({ name: "roster.csv", size: 1024 })).toContain(".xlsx");
  });

  it("10MB 초과는 거절", () => {
    expect(validateRoster({ name: "roster.xlsx", size: ROSTER_MAX_BYTES + 1 })).toContain("MB");
  });
});

describe("decideSignup / pendingCount (상태 전이)", () => {
  const items: PendingSignup[] = [
    { id: "s1", name: "홍길동", birth: "1985-03-12", unit: "103동 1502호", appliedAt: "2026-07-13", policyVersion: "v1.2", rosterMatch: true, status: "pending" },
    { id: "s2", name: "이순신", birth: "1990-11-01", unit: "101동 204호", appliedAt: "2026-07-12", policyVersion: "v1.2", rosterMatch: false, status: "pending" },
  ];

  it("승인은 해당 항목 status만 바꾸고 원본을 변형하지 않는다", () => {
    const next = decideSignup(items, "s1", "approved");
    expect(next.find((i) => i.id === "s1")?.status).toBe("approved");
    expect(next.find((i) => i.id === "s2")?.status).toBe("pending");
    expect(items[0]!.status).toBe("pending"); // 불변
  });

  it("모두 처리하면 대기 건수가 0이 된다", () => {
    let next = decideSignup(items, "s1", "approved");
    expect(pendingCount(next)).toBe(1);
    next = decideSignup(next, "s2", "rejected");
    expect(pendingCount(next)).toBe(0);
  });
});

describe("PII 마스킹 (docs/06)", () => {
  it("성함은 가운데를 가린다", () => {
    expect(maskName("홍길동")).toBe("홍*동");
    expect(maskName("김수")).toBe("김*");
    expect(maskName("남궁민수")).toBe("남**수");
  });

  it("생년월일은 앞 2자리만 남긴다", () => {
    expect(maskBirth("1985-03-12")).toBe("19**-**-**");
  });
});
