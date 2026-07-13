/** 가입 승인 목업 데이터 — 백엔드 연동 전 결정적 시드. 성함·생일은 원본(가명)으로 두고 표시 시 마스킹. */
import type { RosterDiffResult, PendingSignup } from "./logic";

/** 명부 엑셀 diff 병합 결과(데모): 신규 12 · 매칭 유지 74 · 전출 후보 4. */
export const ROSTER_DIFF: RosterDiffResult = {
  newRegistered: 12,
  matchedKept: 74,
  moveOutCandidates: [
    { id: "mo-1", unit: "101동 302호", name: "김영희" },
    { id: "mo-2", unit: "102동 1101호", name: "박철수" },
    { id: "mo-3", unit: "103동 705호", name: "정미경" },
    { id: "mo-4", unit: "101동 1503호", name: "최동훈" },
  ],
};

/** 가입 대기 신청(데모): 명부 일치 3 · 불일치 2. */
export const PENDING_SIGNUPS: readonly PendingSignup[] = [
  {
    id: "sg-1",
    name: "홍길동",
    birth: "1985-03-12",
    unit: "103동 1502호",
    appliedAt: "2026-07-13",
    policyVersion: "v1.2",
    rosterMatch: true,
    status: "pending",
  },
  {
    id: "sg-2",
    name: "이서아",
    birth: "1991-08-24",
    unit: "101동 904호",
    appliedAt: "2026-07-13",
    policyVersion: "v1.2",
    rosterMatch: true,
    status: "pending",
  },
  {
    id: "sg-3",
    name: "박지훈",
    birth: "1978-12-05",
    unit: "102동 507호",
    appliedAt: "2026-07-12",
    policyVersion: "v1.2",
    rosterMatch: true,
    status: "pending",
  },
  {
    id: "sg-4",
    name: "김하늘",
    birth: "1996-02-17",
    unit: "103동 208호",
    appliedAt: "2026-07-12",
    policyVersion: "v1.1",
    rosterMatch: false,
    status: "pending",
  },
  {
    id: "sg-5",
    name: "정우성",
    birth: "1983-06-30",
    unit: "101동 1201호",
    appliedAt: "2026-07-11",
    policyVersion: "v1.1",
    rosterMatch: false,
    status: "pending",
  },
];
