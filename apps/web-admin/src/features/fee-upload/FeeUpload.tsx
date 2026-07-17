"use client";

import { useState } from "react";
import { UploadWizard } from "./UploadWizard";
import { StatusPanel } from "./StatusPanel";
import "./fee-upload.css";

type Tab = "upload" | "status";

const TABS: { id: Tab; label: string }[] = [
  { id: "upload", label: "업로드" },
  { id: "status", label: "부과 현황" },
];

export function FeeUpload() {
  const [tab, setTab] = useState<Tab>("upload");

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          관리비 관리
        </h1>
        <p className="admin-page__lede">
          관리비는 업로드한 엑셀이 단일 출처입니다. AI는 내역 설명만 하며 계산·부과에 관여하지
          않습니다.
        </p>
        <div className="fu-tabs" role="tablist" aria-label="관리비 관리">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              id={`fu-tab-${t.id}`}
              aria-selected={tab === t.id}
              aria-controls={`fu-panel-${t.id}`}
              className="fu-tab"
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <main className="admin-page__main">
        <div
          role="tabpanel"
          id="fu-panel-upload"
          aria-labelledby="fu-tab-upload"
          hidden={tab !== "upload"}
        >
          {tab === "upload" ? <UploadWizard onApplied={() => setTab("status")} /> : null}
        </div>
        <div
          role="tabpanel"
          id="fu-panel-status"
          aria-labelledby="fu-tab-status"
          hidden={tab !== "status"}
        >
          {tab === "status" ? <StatusPanel /> : null}
        </div>
      </main>
    </>
  );
}
