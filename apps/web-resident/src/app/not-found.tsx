import Link from "next/link";
import { EmptyState } from "@liviq/ui";
import "./not-found.css";

/**
 * 존재하지 않거나 아직 준비되지 않은 화면의 폴백.
 * 빈 404 대신 다음 행동을 안내한다(docs/05 §9 권한/빈 상태 원칙).
 */
export default function NotFound() {
  return (
    <main id="main" className="placeholder">
      <EmptyState
        icon="🧭"
        title="이 화면을 찾을 수 없어요"
        description="주소가 바뀌었거나 아직 준비 중인 화면일 수 있습니다."
        action={
          <Link className="btn btn--primary btn--sm" href="/home">
            홈으로 돌아가기
          </Link>
        }
      />
    </main>
  );
}
