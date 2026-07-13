// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { FileDropzone } from "./FileDropzone";

const baseProps = {
  label: "명부 엑셀 업로드",
  accept: ".xlsx, .xls",
  maxSizeMb: 10,
  onFile: () => {},
};

describe("FileDropzone", () => {
  it("idle 상태에서 확장자·최대 용량 안내를 표시한다", () => {
    render(<FileDropzone {...baseProps} state="idle" />);
    expect(screen.getByText(/\.xlsx, \.xls · 최대 10MB/)).toBeDefined();
    expect(screen.getByRole("button").getAttribute("aria-label")).toBe(
      "명부 엑셀 업로드",
    );
  });

  it("selected 상태에서 파일명과 용량을 표시한다", () => {
    render(
      <FileDropzone
        {...baseProps}
        state="selected"
        fileName="roster.xlsx"
        fileSize="2.4 MB"
      />,
    );
    expect(screen.getByText("roster.xlsx")).toBeDefined();
    expect(screen.getByText(/2\.4 MB/)).toBeDefined();
  });

  it("uploading 상태에서 진행률 progressbar 를 노출한다", () => {
    render(<FileDropzone {...baseProps} state="uploading" progress={42} />);
    const bar = screen.getByRole("progressbar");
    expect(bar.getAttribute("aria-valuenow")).toBe("42");
    expect(screen.getByText(/42%/)).toBeDefined();
  });

  it("error 상태에서 danger 메시지를 alert 로 표시한다", () => {
    render(
      <FileDropzone
        {...baseProps}
        state="error"
        errorMessage="지원하지 않는 형식입니다."
      />,
    );
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("지원하지 않는 형식입니다.");
  });

  it("파일 선택 시 onFile 콜백을 호출한다", () => {
    const onFile = vi.fn();
    const { container } = render(<FileDropzone {...baseProps} onFile={onFile} />);
    const input = container.querySelector<HTMLInputElement>(
      ".file-dropzone__input",
    );
    const file = new File(["x"], "roster.xlsx");
    fireEvent.change(input!, { target: { files: [file] } });
    expect(onFile).toHaveBeenCalledWith(file);
  });
});
