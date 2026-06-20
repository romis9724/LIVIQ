import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@liviq/ui/styles.css";

export const metadata: Metadata = {
  title: {
    default: "LIVIQ",
    template: "%s · LIVIQ",
  },
  description: "아파트 관리 AI 플랫폼 — 검색·응대·요약 계층. 모든 AI 답변은 출처와 함께.",
};

export const viewport: Viewport = {
  themeColor: "#fff",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <a className="skip-link" href="#main">
          본문으로 건너뛰기
        </a>
        {children}
      </body>
    </html>
  );
}
