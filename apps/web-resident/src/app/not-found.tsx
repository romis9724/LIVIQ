import Link from "next/link";
import { EmptyState } from "@liviq/ui";
import "./not-found.css";

/**
 * 아직 구현되지 않은 화면(개요가 링크하는 입주민/관리자 화면)의 폴백.
 * 빈 404 대신 다음 행동을 안내한다(docs/05 §9 권한/빈 상태 원칙).
 */
export default function NotFound() {
  return (
    <main id="main" className="placeholder">
      <EmptyState
        icon="🧭"
        title="이 화면은 아직 준비 중이에요"
        description="현재 단계에서는 디자인 파운데이션과 전체 화면 개요만 구현되어 있습니다."
        action={
          <Link className="btn btn--primary btn--sm" href="/">
            전체 화면으로 돌아가기
          </Link>
        }
      />
    </main>
  );
}
