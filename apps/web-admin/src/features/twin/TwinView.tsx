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

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; geometry: TwinGeometryItem[]; overlay: Record<string, number> };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function TwinView() {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const load = useCallback(async () => {
    setState({ kind: "loading" });
    try {
      // geometry·오버레이는 서로 독립 — 병렬로 받아 왕복을 줄인다.
      const [geometry, overlay] = await Promise.all([
        listTwinGeometry(),
        getTwinOverlay("occupancy"),
      ]);
      setState({ kind: "ready", geometry, overlay });
    } catch (err) {
      setState({ kind: "error", message: errorMessage(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          단지 트윈
        </h1>
        <p className="admin-page__lede">
          세대 3D 모형에 세대원 수(occupancy)를 색으로 겹쳐 봅니다. 확정 데이터만 표시하며 AI는
          개입하지 않습니다.
        </p>
      </header>

      <main className="admin-page__main">
        <TwinBody state={state} onRetry={() => void load()} />
      </main>
    </>
  );
}

function TwinBody({ state, onRetry }: { state: LoadState; onRetry: () => void }) {
  if (state.kind === "loading") {
    return (
      <section className="surface-card twin-stage">
        <div className="twin-canvas twin-canvas--loading" role="status" aria-live="polite">
          불러오는 중…
        </div>
      </section>
    );
  }

  if (state.kind === "error") {
    return (
      <section className="surface-card twin-empty">
        <EmptyState
          icon="⚠"
          title="트윈 데이터를 불러오지 못했습니다"
          description={state.message}
          action={
            <Button variant="secondary" onClick={onRetry}>
              다시 시도
            </Button>
          }
        />
      </section>
    );
  }

  if (state.geometry.length === 0) {
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
      <TwinDeck geometry={state.geometry} overlay={state.overlay} />
    </section>
  );
}
