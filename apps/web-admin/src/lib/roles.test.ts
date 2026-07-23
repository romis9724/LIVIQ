import { describe, expect, it } from "vitest";
import { isSysAdmin, navForRoles, roleHome, roleLabel } from "./roles";

/** 그룹 배열을 평탄화해 href만 뽑는다(순서 유지). */
function flatHrefs(groups: ReturnType<typeof navForRoles>): string[] {
  return groups.flatMap((g) => g.items.map((i) => i.href));
}

describe("navForRoles", () => {
  it("SYS_ADMIN에는 단지 관리 하나만 섹션 헤더 없이 노출한다", () => {
    const nav = navForRoles(["SYS_ADMIN"]);
    expect(nav).toHaveLength(1);
    expect(nav[0]?.title).toBeUndefined();
    expect(flatHrefs(nav)).toEqual(["/system/tenants"]);
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
      ["/dashboard", "/notices"],
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
