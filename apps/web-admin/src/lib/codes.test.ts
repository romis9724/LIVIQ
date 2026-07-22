import { describe, it, expect } from "vitest";

import type { Code, CodeGroup } from "./api";
import { codeLabelMap, codeOptions } from "./codes";

function code(over: Partial<Code>): Code {
  return {
    id: over.id ?? "c1",
    groupId: over.groupId ?? "g1",
    code: over.code ?? "A",
    label: over.label ?? "라벨",
    parentId: over.parentId ?? null,
    sortOrder: over.sortOrder ?? 0,
    active: over.active ?? true,
  };
}

function group(groupKey: string, codes: Code[]): CodeGroup {
  return { id: `id-${groupKey}`, groupKey, name: groupKey, description: null, isSystem: true, codes };
}

const groups: CodeGroup[] = [
  group("DOC_CATEGORY", [
    code({ id: "b", code: "B", label: "회의록", sortOrder: 2 }),
    code({ id: "a", code: "A", label: "규약", sortOrder: 1 }),
    code({ id: "z", code: "Z", label: "폐지", sortOrder: 3, active: false }),
  ]),
  group("NOTICE_CATEGORY", [code({ id: "n", code: "N", label: "행사" })]),
];

describe("codeOptions", () => {
  it("active 코드만 sort_order 순으로 반환한다", () => {
    expect(codeOptions(groups, "DOC_CATEGORY")).toEqual([
      { id: "a", label: "규약" },
      { id: "b", label: "회의록" },
    ]);
  });

  it("없는 그룹 키는 빈 배열", () => {
    expect(codeOptions(groups, "MISSING")).toEqual([]);
  });
});

describe("codeLabelMap", () => {
  it("비활성 코드까지 id→라벨로 매핑한다", () => {
    const map = codeLabelMap(groups, "DOC_CATEGORY");
    expect(map.get("a")).toBe("규약");
    expect(map.get("z")).toBe("폐지");
  });

  it("없는 그룹 키는 빈 맵", () => {
    expect(codeLabelMap(groups, "MISSING").size).toBe(0);
  });
});
