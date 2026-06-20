import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import "@liviq/ui/styles.css";
import { AdminShell } from "@/components/admin-shell/AdminShell";

export const metadata: Metadata = {
  title: {
    default: "LIVIQ 관리자",
    template: "%s · LIVIQ 관리자",
  },
  description: "LIVIQ 관리자 콘솔 — AI 검수·공지 초안·민원·문서·시설·회의록.",
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
        <AdminShell>{children}</AdminShell>
      </body>
    </html>
  );
}
