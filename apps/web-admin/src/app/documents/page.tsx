import type { Metadata } from "next";
import { DocumentManager } from "@/features/documents/DocumentManager";

export const metadata: Metadata = {
  title: "문서 관리",
  description: "문서 게시판 · 첨부 · 버전 · 색인 상태",
};

export default function DocumentsPage() {
  return <DocumentManager />;
}
