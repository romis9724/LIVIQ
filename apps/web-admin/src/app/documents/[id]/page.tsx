import type { Metadata } from "next";
import { DocumentDetail } from "@/features/documents/DocumentDetail";

export const metadata: Metadata = {
  title: "문서 상세",
  description: "게시글 정보 · 첨부 파일 · 버전 이력",
};

export default function DocumentDetailPage() {
  return <DocumentDetail />;
}
