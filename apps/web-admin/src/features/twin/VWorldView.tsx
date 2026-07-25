"use client";

import { EmptyState } from "@liviq/ui";

// VWorld 프론트 키는 서비스 URL 도메인 잠금이라 번들 노출 무방(ADR-0019 개정, docs/06 §6).
// 미설정이면 실사 뷰만 안내로 대체하고 기본 deck.gl 뷰는 그대로 동작한다.
const VWORLD_KEY = process.env.NEXT_PUBLIC_VWORLD_API_KEY ?? "";

/**
 * 실사 3D(VWorld) 뷰 — 관리 셀 임베딩(ADR-0019 개정, H9-3).
 * 현재는 배선 스캐폴드: 키 미설정 안내 / 키 설정 시 준비 안내. Cesium 실건물 렌더는
 * 프로토타입 dashboard_vworld.html 로직을 트윈 API(geometry·overlay)로 재배선해 후속 포팅하며,
 * 그때 geometry·overlay·onSelectHousehold props 를 TwinDeck 과 동일 계약으로 받는다.
 */
export function VWorldView() {
  if (!VWORLD_KEY) {
    return (
      <div className="twin-canvas twin-canvas--fallback">
        <EmptyState
          icon="🛰"
          title="VWorld 실사 3D 키가 설정되지 않았습니다"
          description="apps/web-admin/.env.local 에 NEXT_PUBLIC_VWORLD_API_KEY 를 설정하고 vworld.kr 에서 서비스 URL(http://localhost:3001)을 등록하면 실사 3D가 표시됩니다. 기본 3D 뷰는 그대로 사용할 수 있어요."
        />
      </div>
    );
  }

  // ponytail: 키 확인까지만 배선. Cesium 실건물 렌더는 URL 등록·라이브 검증 후 포팅(H9-3 후속).
  return (
    <div className="twin-canvas twin-canvas--fallback">
      <EmptyState
        icon="🛰"
        title="실사 3D 준비 중"
        description="VWorld 키가 확인되었습니다. 실사 건물 3D 렌더는 다음 단계에서 연결됩니다(H9-3)."
      />
    </div>
  );
}
