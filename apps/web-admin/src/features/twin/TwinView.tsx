"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { Button, EmptyState } from "@liviq/ui";
import {
  ApiError,
  getTwinOverlay,
  listTwinGeometry,
  type TwinGeometryItem,
} from "@/lib/api";
import { OVERLAY_KINDS, OVERLAY_LABELS, type OverlayKind } from "./twin-data";
import { TwinDetailPanel } from "./TwinDetailPanel";
import "./twin.css";

// deck.gl 은 무겁다 — /twin 에서만 클라이언트로 로드해 타 페이지 번들에 새지 않게 한다(ADR-0019).
const TwinDeck = dynamic(() => import("./TwinDeck").then((m) => m.TwinDeck), {
  ssr: false,
  loading: () => (
    <div className="twin-canvas twin-canvas--loading" role="status" aria-live="polite">
      3D 모형 불러오는 중…
    </div>
  ),
});

type GeoState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; geometry: TwinGeometryItem[] };

// 받아온 kind 는 캐시해 토글 시 재요청을 막는다(geometry 는 1회 로드).
type OverlayCache = Partial<Record<OverlayKind, Record<string, number>>>;

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function TwinView() {
  const [geo, setGeo] = useState<GeoState>({ kind: "loading" });
  const [overlayKind, setOverlayKind] = useState<OverlayKind>("occupancy");
  const [overlays, setOverlays] = useState<OverlayCache>({});
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setGeo({ kind: "loading" });
    setOverlays({});
    try {
      // geometry·초기 오버레이(입주)는 독립 — 병렬로 받아 왕복을 줄인다.
      const [geometry, occupancy] = await Promise.all([
        listTwinGeometry(),
        getTwinOverlay("occupancy"),
      ]);
      setGeo({ kind: "ready", geometry });
      setOverlays({ occupancy });
    } catch (err) {
      setGeo({ kind: "error", message: errorMessage(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  // 현재 kind 오버레이가 미캐시면 로드해 병합 — 캐시된 kind 는 재요청하지 않는다.
  useEffect(() => {
    if (geo.kind !== "ready" || overlays[overlayKind]) return;
    let alive = true;
    void getTwinOverlay(overlayKind)
      .then((values) => {
        if (alive) setOverlays((cur) => ({ ...cur, [overlayKind]: values }));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [overlayKind, geo.kind, overlays]);

  const showSegments = geo.kind === "ready";
  const overlay = overlays[overlayKind] ?? {};

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          단지 트윈
        </h1>
        <p className="admin-page__lede">
          세대 3D 모형에 상태를 색으로 겹쳐 봅니다. 확정 데이터만 표시하며 AI는 개입하지 않습니다.
        </p>
        {showSegments ? (
          <div className="twin-overlays" role="tablist" aria-label="오버레이 선택">
            {OVERLAY_KINDS.map((kind) => (
              <button
                key={kind}
                type="button"
                role="tab"
                aria-selected={overlayKind === kind}
                className="twin-overlay-tab"
                data-active={overlayKind === kind || undefined}
                onClick={() => setOverlayKind(kind)}
              >
                {OVERLAY_LABELS[kind]}
              </button>
            ))}
          </div>
        ) : null}
      </header>

      <main className="admin-page__main">
        <TwinBody
          geo={geo}
          overlay={overlay}
          overlayKind={overlayKind}
          onRetry={() => void load()}
          onSelectHousehold={setSelectedId}
        />
      </main>

      {selectedId ? (
        <TwinDetailPanel householdId={selectedId} onClose={() => setSelectedId(null)} />
      ) : null}
    </>
  );
}

interface TwinBodyProps {
  geo: GeoState;
  overlay: Record<string, number>;
  overlayKind: OverlayKind;
  onRetry: () => void;
  onSelectHousehold: (householdId: string) => void;
}

function TwinBody({ geo, overlay, overlayKind, onRetry, onSelectHousehold }: TwinBodyProps) {
  if (geo.kind === "loading") {
    return (
      <section className="surface-card twin-stage">
        <div className="twin-canvas twin-canvas--loading" role="status" aria-live="polite">
          불러오는 중…
        </div>
      </section>
    );
  }

  if (geo.kind === "error") {
    return (
      <section className="surface-card twin-empty">
        <EmptyState
          icon="⚠"
          title="트윈 데이터를 불러오지 못했습니다"
          description={geo.message}
          action={
            <Button variant="secondary" onClick={onRetry}>
              다시 시도
            </Button>
          }
        />
      </section>
    );
  }

  if (geo.geometry.length === 0) {
    return (
      <section className="surface-card twin-empty">
        <EmptyState
          icon="🧊"
          title="등록된 세대 geometry가 없습니다"
          description="설정 > 동/호수 관리에서 units.json을 업로드하면 3D 트윈이 표시됩니다."
          action={
            <Link className="twin-empty__link" href="/settings/households">
              동/호수 관리로 이동
            </Link>
          }
        />
      </section>
    );
  }

  return (
    <section className="surface-card twin-stage">
      <TwinDeck
        geometry={geo.geometry}
        overlay={overlay}
        overlayKind={overlayKind}
        onSelectHousehold={onSelectHousehold}
      />
    </section>
  );
}
