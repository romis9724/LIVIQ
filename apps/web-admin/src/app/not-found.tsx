import Link from "next/link";
import { EmptyState } from "@liviq/ui";

/** 미구현 관리자 화면 폴백(대시보드·민원·문서·시설·회의록). */
export default function NotFound() {
  return (
    <main id="main" style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "var(--space-12)", flex: 1 }}>
      <EmptyState
        icon="🧭"
        title="이 화면은 아직 준비 중이에요"
        description="요청하신 화면을 찾을 수 없습니다."
        action={
          <Link className="btn btn--primary btn--sm" href="/dashboard">
            대시보드로 가기
          </Link>
        }
      />
    </main>
  );
}
