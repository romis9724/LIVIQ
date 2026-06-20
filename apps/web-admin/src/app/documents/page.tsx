import type { Metadata } from "next";
import { DocumentManager } from "@/features/documents/DocumentManager";

export const metadata: Metadata = {
  title: "문서 관리",
  description: "업로드 · 공개 범위 · 색인 상태",
};

export default function DocumentsPage() {
  return <DocumentManager />;
}
