import { describe, it, expect } from "vitest";

import type { Code } from "@/lib/api";
import { buildCodeTree, validateCodeValue, validateGroupKey, validateLabel } from "./data";

function makeCode(over: Partial<Code>): Code {
  return {
    id: "c1",
    groupId: "g1",
    code: "A",
    label: "A",
    parentId: null,
    sortOrder: 0,
    active: true,
    ...over,
  };
}

describe("buildCodeTree (평면 → 2단계 트리)", () => {
  it("부모를 최상위로, 자식을 부모 아래로 배치한다", () => {
    const codes = [
      makeCode({ id: "parent", code: "P" }),
      makeCode({ id: "child", code: "C", parentId: "parent" }),
    ];
    const tree = buildCodeTree(codes);
    expect(tree).toHaveLength(1);
    expect(tree[0]?.id).toBe("parent");
    expect(tree[0]?.children.map((c) => c.id)).toEqual(["child"]);
  });

  it("sort_order 오름차순, 동률이면 code 사전순으로 정렬한다", () => {
    const codes = [
      makeCode({ id: "b", code: "B", sortOrder: 1 }),
      makeCode({ id: "a", code: "A", sortOrder: 1 }),
      makeCode({ id: "z", code: "Z", sortOrder: 0 }),
    ];
    expect(buildCodeTree(codes).map((n) => n.id)).toEqual(["z", "a", "b"]);
  });

  it("자식도 sort_order로 정렬한다", () => {
    const codes = [
      makeCode({ id: "p", code: "P" }),
      makeCode({ id: "c2", code: "C2", parentId: "p", sortOrder: 2 }),
      makeCode({ id: "c1", code: "C1", parentId: "p", sortOrder: 1 }),
    ];
    expect(buildCodeTree(codes)[0]?.children.map((c) => c.id)).toEqual(["c1", "c2"]);
  });

  it("부모가 목록에 없는 고아 코드는 최상위로 승격한다", () => {
    const codes = [makeCode({ id: "orphan", code: "O", parentId: "missing" })];
    const tree = buildCodeTree(codes);
    expect(tree).toHaveLength(1);
    expect(tree[0]?.id).toBe("orphan");
  });

  it("빈 배열은 빈 트리", () => {
    expect(buildCodeTree([])).toEqual([]);
  });
});

describe("validateGroupKey", () => {
  it("대문자 스네이크는 통과", () => {
    expect(validateGroupKey("FEE_KIND")).toBeNull();
    expect(validateGroupKey("FACILITY")).toBeNull();
  });

  it("소문자·하이픈·숫자 시작·공백은 거부", () => {
    expect(validateGroupKey("fee_kind")).not.toBeNull();
    expect(validateGroupKey("FEE-KIND")).not.toBeNull();
    expect(validateGroupKey("1FEE")).not.toBeNull();
    expect(validateGroupKey("   ")).toContain("입력");
  });
});

describe("validateCodeValue / validateLabel", () => {
  it("내용이 있으면 통과, 공백만이면 거부", () => {
    expect(validateCodeValue("WATER")).toBeNull();
    expect(validateCodeValue("  ")).not.toBeNull();
    expect(validateLabel("수도료")).toBeNull();
    expect(validateLabel("")).not.toBeNull();
  });
});
