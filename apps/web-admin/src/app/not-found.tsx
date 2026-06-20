import Link from "next/link";
import { EmptyState } from "@liviq/ui";

/** 미구현 관리자 화면 폴백(대시보드·민원·문서·시설·회의록). */
export default function NotFound() {
  return (
    <main id="main" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "var(--space-12)", flex: 1 }}>
      <EmptyState
        icon="🧭"
        title="이 화면은 아직 준비 중이에요"
        description="P0 단계에서는 AI 검수 큐와 공지 초안 작성만 구현되어 있습니다."
        action={
          <Link className="btn btn--primary btn--sm" href="/review-queue">
            AI 검수 큐로 가기
          </Link>
        }
      />
    </main>
  );
}
