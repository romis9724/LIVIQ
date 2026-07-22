import { describe, it, expect } from "vitest";

import type { Notice } from "@/lib/api";
import {
  fileExtension,
  formatFileSize,
  hasErrors,
  isoToLocalInput,
  localInputToIso,
  MAX_ATTACHMENTS,
  MAX_BODY,
  MAX_TITLE,
  sortNotices,
  validateAttachment,
  validateNoticeForm,
} from "./data";

function makeNotice(over: Partial<Notice>): Notice {
  return {
    id: "n1",
    title: "제목",
    body: "본문",
    status: "draft",
    pinned: false,
    audience: "ALL",
    scheduledAt: null,
    publishedAt: null,
    publishedBy: null,
    createdAt: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    attachments: [],
    ...over,
  };
}

describe("fileExtension", () => {
  it("소문자 확장자를 반환한다", () => {
    expect(fileExtension("보고서.PDF")).toBe("pdf");
    expect(fileExtension("사진.jpeg")).toBe("jpeg");
  });

  it("확장자가 없으면 빈 문자열", () => {
    expect(fileExtension("noext")).toBe("");
  });
});

describe("validateAttachment", () => {
  it("허용 확장자·정상 용량이면 null", () => {
    expect(validateAttachment({ name: "a.pdf", size: 1024 }, 0)).toBeNull();
  });

  it("허용하지 않는 확장자는 거절한다", () => {
    expect(validateAttachment({ name: "a.exe", size: 1024 }, 0)).toMatch(/형식/);
  });

  it("빈 파일은 거절한다", () => {
    expect(validateAttachment({ name: "a.pdf", size: 0 }, 0)).toMatch(/빈 파일/);
  });

  it("20MB 초과는 거절한다", () => {
    expect(validateAttachment({ name: "a.pdf", size: 21 * 1024 * 1024 }, 0)).toMatch(/MB/);
  });

  it("이미 5개면 개수 상한으로 거절한다", () => {
    expect(validateAttachment({ name: "a.pdf", size: 1024 }, MAX_ATTACHMENTS)).toMatch(/최대/);
  });
});

describe("formatFileSize", () => {
  it("단위별로 포맷한다", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2.0 KB");
    expect(formatFileSize(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("sortNotices", () => {
  it("고정 공지를 먼저, 그다음 작성일 내림차순으로 정렬한다", () => {
    const notices = [
      makeNotice({ id: "old", pinned: false, createdAt: "2026-01-01T00:00:00Z" }),
      makeNotice({ id: "new", pinned: false, createdAt: "2026-03-01T00:00:00Z" }),
      makeNotice({ id: "pin", pinned: true, createdAt: "2026-02-01T00:00:00Z" }),
    ];
    expect(sortNotices(notices).map((n) => n.id)).toEqual(["pin", "new", "old"]);
  });

  it("원본을 변형하지 않는다", () => {
    const notices = [makeNotice({ id: "a" }), makeNotice({ id: "b" })];
    const before = notices.map((n) => n.id);
    sortNotices(notices);
    expect(notices.map((n) => n.id)).toEqual(before);
  });
});

describe("validateNoticeForm", () => {
  const now = new Date("2026-06-01T00:00:00Z").getTime();

  it("제목·본문이 있으면 오류 없음(임시저장)", () => {
    const errors = validateNoticeForm(
      { title: "안내", body: "본문", saveMode: "draft", scheduledAt: "" },
      now,
    );
    expect(hasErrors(errors)).toBe(false);
  });

  it("빈 제목·본문을 거절한다", () => {
    const errors = validateNoticeForm(
      { title: "  ", body: "", saveMode: "draft", scheduledAt: "" },
      now,
    );
    expect(errors.title).toBeDefined();
    expect(errors.body).toBeDefined();
  });

  it("제목·본문 길이 상한을 거절한다", () => {
    const errors = validateNoticeForm(
      {
        title: "a".repeat(MAX_TITLE + 1),
        body: "b".repeat(MAX_BODY + 1),
        saveMode: "draft",
        scheduledAt: "",
      },
      now,
    );
    expect(errors.title).toMatch(/이하/);
    expect(errors.body).toMatch(/이하/);
  });

  it("예약 발행인데 시각이 없으면 거절한다", () => {
    const errors = validateNoticeForm(
      { title: "안내", body: "본문", saveMode: "scheduled", scheduledAt: "" },
      now,
    );
    expect(errors.scheduledAt).toMatch(/지정/);
  });

  it("예약 시각이 과거면 거절한다", () => {
    const errors = validateNoticeForm(
      { title: "안내", body: "본문", saveMode: "scheduled", scheduledAt: "2020-01-01T00:00" },
      now,
    );
    expect(errors.scheduledAt).toMatch(/미래/);
  });

  it("예약 시각이 미래면 통과한다", () => {
    const errors = validateNoticeForm(
      { title: "안내", body: "본문", saveMode: "scheduled", scheduledAt: "2030-01-01T00:00" },
      now,
    );
    expect(hasErrors(errors)).toBe(false);
  });
});

describe("localInputToIso / isoToLocalInput", () => {
  it("빈 값은 null / 빈 문자열", () => {
    expect(localInputToIso("")).toBeNull();
    expect(isoToLocalInput(null)).toBe("");
  });

  it("로컬 값을 ISO로 바꿨다가 되돌리면 분 단위까지 보존된다", () => {
    const local = "2030-01-02T15:30";
    const iso = localInputToIso(local);
    expect(iso).not.toBeNull();
    expect(isoToLocalInput(iso)).toBe(local);
  });
});
