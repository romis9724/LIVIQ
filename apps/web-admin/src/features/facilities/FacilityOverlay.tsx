"use client";

import { useEffect, useRef, type ReactNode } from "react";

// 시설관리 메인은 전체화면 그래프 하나다(H14-1). 목록·평면도·AI 도우미는 탭이 아니라
// 이 오버레이로 덮어 연다. 3D canvas 는 스크린리더로 읽히지 않으므로(ADR-0022 결정 6)
// 목록 오버레이는 동등 기능의 접근성 대체 수단 — 진입 버튼을 포커스 순서 맨 앞에 둔다.

interface FacilityOverlayProps {
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function FacilityOverlay({ title, onClose, children }: FacilityOverlayProps) {
  const panelRef = useRef<HTMLDivElement>(null);

  // 열릴 때 포커스를 패널로 옮기고 Esc 로 닫는다(포커스 트랩까지는 두지 않는다 — 공용 유틸 없음).
  useEffect(() => {
    panelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key !== "Escape") return;
      // 안쪽 다이얼로그(설비 등록 등)가 열려 있으면 그쪽이 먼저다 — 오버레이는 닫지 않는다.
      if (panelRef.current?.querySelector('[role="dialog"]')) return;
      onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fac-overlay">
      <div
        className="fac-overlay__panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={panelRef}
      >
        <div className="fac-overlay__bar">
          <h2 className="fac-overlay__title">{title}</h2>
          <button type="button" className="fac-overlay__close" onClick={onClose}>
            닫기
          </button>
        </div>
        <div className="fac-overlay__body">{children}</div>
      </div>
    </div>
  );
}
