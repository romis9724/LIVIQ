import type { Metadata } from "next";
import { DocumentForm } from "@/features/documents/DocumentForm";

export const metadata: Metadata = {
  title: "새 문서",
  description: "제목 · 카테고리 · 공개 범위 · 첨부 문서를 등록합니다.",
};

export default function DocumentNewPage() {
  return <DocumentForm />;
}
