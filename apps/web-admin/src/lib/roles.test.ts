import { describe, expect, it } from "vitest";
import { isSysAdmin, navForRoles, roleHome, roleLabel } from "./roles";

/** 그룹 배열을 평탄화해 href만 뽑는다(순서 유지). */
function flatHrefs(groups: ReturnType<typeof navForRoles>): string[] {
  return groups.flatMap((g) => g.items.map((i) => i.href));
}

describe("navForRoles", () => {
  it("SYS_ADMIN에는 단지 관리·AI 설정만 섹션 헤더 없이 노출한다 (H15-1)", () => {
    const nav = navForRoles(["SYS_ADMIN"]);
    expect(nav).toHaveLength(1);
    expect(nav[0]?.title).toBeUndefined();
    expect(flatHrefs(nav)).toEqual(["/system/tenants", "/system/ai"]);
  });

  it("AI 설정은 MANAGER·STAFF에 노출하지 않는다 (SYS_ADMIN 전용)", () => {
    expect(flatHrefs(navForRoles(["MANAGER"]))).not.toContain("/system/ai");
    expect(flatHrefs(navForRoles(["STAFF"]))).not.toContain("/system/ai");
  });

  it("STAFF(소장 아님)에는 민원·공지·문서만 섹션 헤더 없이 노출한다", () => {
    const nav = navForRoles(["STAFF"]);
    expect(nav).toHaveLength(1);
    expect(nav[0]?.title).toBeUndefined();
    expect(flatHrefs(nav)).toEqual(["/inquiries", "/notices", "/documents"]);
  });

  it("MANAGER는 섹션 그룹 구조(제목·순서)로 노출한다", () => {
    const nav = navForRoles(["MANAGER"]);
    expect(nav.map((g) => g.title)).toEqual([
      undefined,
      "입주민 관리",
      "관리소 운영",
      "설정",
    ]);
    expect(nav.map((g) => g.items.map((i) => i.href))).toEqual([
      ["/dashboard", "/parking", "/notices"],
      ["/residents", "/fees", "/inquiries"],
      ["/staff", "/documents", "/facilities"],
      ["/settings/households", "/settings/codes"],
    ]);
  });

  it("MANAGER에는 전체와 직원 관리·코드 관리를 노출한다", () => {
    const hrefs = flatHrefs(navForRoles(["MANAGER"]));
    expect(hrefs).toContain("/dashboard");
    expect(hrefs).toContain("/staff");
    expect(hrefs).toContain("/fees");
    expect(hrefs).toContain("/settings/codes");
  });

  it("설정(코드 관리)은 STAFF·SYS_ADMIN에 노출하지 않는다", () => {
    expect(flatHrefs(navForRoles(["STAFF"]))).not.toContain("/settings/codes");
    expect(flatHrefs(navForRoles(["SYS_ADMIN"]))).not.toContain("/settings/codes");
  });

  it("MANAGER+STAFF는 소장 기준 전체 내비를 노출한다", () => {
    expect(flatHrefs(navForRoles(["MANAGER", "STAFF"]))).toContain("/staff");
  });

  it("역할 미상(빈 배열)은 MANAGER 전체로 폴백한다", () => {
    expect(flatHrefs(navForRoles([]))).toContain("/dashboard");
  });

  it("hasTwin이면 MANAGER 대시보드 바로 아래(첫 그룹)에 트윈·주차장 대시보드를 노출한다", () => {
    const top = navForRoles(["MANAGER"], { hasTwin: true })[0];
    expect(top?.items.map((i) => i.href)).toEqual(["/dashboard", "/twin", "/parking", "/notices"]);
    // 관리소 운영에는 더 이상 트윈이 없다(대시보드 계열로 이동, H9-4).
    const ops = navForRoles(["MANAGER"], { hasTwin: true }).find(
      (g) => g.title === "관리소 운영",
    );
    expect(ops?.items.map((i) => i.href)).toEqual(["/staff", "/documents", "/facilities"]);
  });

  it("주차장 대시보드는 hasTwin과 무관하게 MANAGER 첫 그룹에 항상 노출한다 (H9-5)", () => {
    // 트윈 없음: 대시보드 바로 다음. 트윈 있음: 트윈 바로 다음.
    expect(navForRoles(["MANAGER"])[0]?.items.map((i) => i.href)).toEqual([
      "/dashboard",
      "/parking",
      "/notices",
    ]);
    expect(navForRoles(["MANAGER"], { hasTwin: false })[0]?.items.map((i) => i.href)).toEqual([
      "/dashboard",
      "/parking",
      "/notices",
    ]);
  });

  it("STAFF·SYS_ADMIN에는 주차장 대시보드를 노출하지 않는다", () => {
    expect(flatHrefs(navForRoles(["STAFF"]))).not.toContain("/parking");
    expect(flatHrefs(navForRoles(["SYS_ADMIN"]))).not.toContain("/parking");
  });

  it("hasTwin 미전달(기본)이면 트윈 대시보드를 노출하지 않는다", () => {
    expect(flatHrefs(navForRoles(["MANAGER"]))).not.toContain("/twin");
    expect(flatHrefs(navForRoles(["MANAGER"], { hasTwin: false }))).not.toContain("/twin");
  });

  it("STAFF·SYS_ADMIN은 hasTwin이라도 단지 트윈을 노출하지 않는다", () => {
    expect(flatHrefs(navForRoles(["STAFF"], { hasTwin: true }))).not.toContain("/twin");
    expect(flatHrefs(navForRoles(["SYS_ADMIN"], { hasTwin: true }))).not.toContain("/twin");
  });
});

describe("roleHome", () => {
  it("SYS_ADMIN은 단지 관리로 진입한다", () => {
    expect(roleHome(["SYS_ADMIN"])).toBe("/system/tenants");
  });

  it("STAFF는 민원으로 진입한다", () => {
    expect(roleHome(["STAFF"])).toBe("/inquiries");
  });

  it("MANAGER는 대시보드로 진입한다 (H7-6)", () => {
    expect(roleHome(["MANAGER"])).toBe("/dashboard");
  });
});

describe("isSysAdmin", () => {
  it("SYS_ADMIN 포함 여부를 판별한다", () => {
    expect(isSysAdmin(["SYS_ADMIN"])).toBe(true);
    expect(isSysAdmin(["MANAGER"])).toBe(false);
  });
});

describe("roleLabel", () => {
  it("역할별 표시 라벨을 돌려준다", () => {
    expect(roleLabel(["SYS_ADMIN"])).toBe("시스템 관리자");
    expect(roleLabel(["MANAGER", "STAFF"])).toBe("관리소장");
    expect(roleLabel(["STAFF"])).toBe("직원");
    expect(roleLabel([])).toBe("관리자");
  });
});
