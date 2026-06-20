import { redirect } from "next/navigation";

/** 관리자 진입점 — P0 단계에서는 AI 검수 큐로 이동. */
export default function AdminIndex() {
  redirect("/review-queue");
}
