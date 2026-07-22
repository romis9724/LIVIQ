"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Dialog, EmptyState, Skeleton, Toast } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  createCode,
  createCodeGroup,
  deleteCode,
  deleteCodeGroup,
  listCodeGroups,
  updateCode,
  updateCodeGroup,
  type Code,
  type CodeGroup,
  type CreateCodeGroupInput,
  type CreateCodeInput,
  type UpdateCodeGroupInput,
  type UpdateCodeInput,
} from "@/lib/api";
import { GroupPanel } from "./GroupPanel";
import { CodePanel } from "./CodePanel";
import "./settings.css";

const TOAST_DURATION_MS = 3200;

type ToastState = { message: string; tone: ToastTone };

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function CodeRegistry() {
  const [groups, setGroups] = useState<CodeGroup[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [groupDeleteTarget, setGroupDeleteTarget] = useState<CodeGroup | null>(null);
  const [codeDeleteTarget, setCodeDeleteTarget] = useState<Code | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    setToast({ message, tone });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_DURATION_MS);
  }, []);

  const load = useCallback(async () => {
    try {
      const next = await listCodeGroups();
      setGroups(next);
      setLoadError(null);
      // 첫 로드 시 첫 그룹 자동 선택(선택 유지, 삭제된 선택은 초기화).
      setSelectedId((prev) =>
        prev && next.some((g) => g.id === prev) ? prev : (next[0]?.id ?? null),
      );
    } catch (err) {
      setLoadError(errorMessage(err));
      setGroups([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(
    () => () => {
      if (toastTimer.current) clearTimeout(toastTimer.current);
    },
    [],
  );

  // 뮤테이션 공통 래퍼 — 성공 시 목록 재로드·토스트, 실패 시 danger 토스트. 성공 여부 반환.
  const run = useCallback(
    async (action: () => Promise<unknown>, successMessage: string): Promise<boolean> => {
      setBusy(true);
      try {
        await action();
        await load();
        showToast(successMessage);
        return true;
      } catch (err) {
        showToast(errorMessage(err), "danger");
        return false;
      } finally {
        setBusy(false);
      }
    },
    [load, showToast],
  );

  const handleCreateGroup = useCallback(
    (input: CreateCodeGroupInput) => run(() => createCodeGroup(input), "코드 그룹을 추가했습니다."),
    [run],
  );

  const handleUpdateGroup = useCallback(
    (id: string, input: UpdateCodeGroupInput) =>
      run(() => updateCodeGroup(id, input), "코드 그룹을 수정했습니다."),
    [run],
  );

  const handleCreateCode = useCallback(
    (input: CreateCodeInput) => run(() => createCode(input), "코드를 추가했습니다."),
    [run],
  );

  const handleUpdateCode = useCallback(
    (id: string, input: UpdateCodeInput) => run(() => updateCode(id, input), "코드를 수정했습니다."),
    [run],
  );

  async function confirmGroupDelete() {
    if (!groupDeleteTarget) return;
    const ok = await run(() => deleteCodeGroup(groupDeleteTarget.id), "코드 그룹을 삭제했습니다.");
    if (ok) setGroupDeleteTarget(null);
  }

  async function confirmCodeDelete() {
    if (!codeDeleteTarget) return;
    const ok = await run(() => deleteCode(codeDeleteTarget.id), "코드를 삭제했습니다.");
    if (ok) setCodeDeleteTarget(null);
  }

  const selected = groups?.find((g) => g.id === selectedId) ?? null;

  return (
    <>
      <header className="admin-page__header">
        <h1 id="main" className="admin-page__title">
          코드 관리
        </h1>
        <p className="admin-page__lede">
          관리비 항목·시설 유형처럼 여러 화면에서 공통으로 쓰는 선택지를 그룹으로 묶어 관리합니다.
          🔒 시스템 그룹은 삭제·키 변경이 잠겨 있고, 그 안의 코드만 다듬을 수 있습니다.
        </p>
      </header>

      <main className="admin-page__main codes-layout">
        {loadError ? (
          <EmptyState icon="⚠" title="코드를 불러오지 못했습니다" description={loadError} />
        ) : groups === null ? (
          <div className="codes-layout__grid">
            <Skeleton height="320px" />
            <Skeleton height="320px" />
          </div>
        ) : (
          <div className="codes-layout__grid">
            <GroupPanel
              groups={groups}
              selectedId={selectedId}
              busy={busy}
              onSelect={setSelectedId}
              onCreate={handleCreateGroup}
            />
            <CodePanel
              group={selected}
              busy={busy}
              onUpdateGroup={handleUpdateGroup}
              onDeleteGroup={setGroupDeleteTarget}
              onCreateCode={handleCreateCode}
              onUpdateCode={handleUpdateCode}
              onDeleteCode={setCodeDeleteTarget}
            />
          </div>
        )}
      </main>

      <Dialog
        open={groupDeleteTarget !== null}
        title="코드 그룹을 삭제할까요?"
        description={`"${groupDeleteTarget?.name ?? ""}" 그룹과 그 안의 모든 코드가 함께 삭제됩니다. 이 작업은 되돌릴 수 없습니다.`}
        confirmLabel="삭제"
        cancelLabel="취소"
        danger
        onConfirm={() => void confirmGroupDelete()}
        onCancel={() => setGroupDeleteTarget(null)}
      />

      <Dialog
        open={codeDeleteTarget !== null}
        title="코드를 삭제할까요?"
        description={`"${codeDeleteTarget?.label ?? ""}" 코드를 삭제합니다. 하위 코드가 있거나 다른 화면에서 사용 중이면 삭제할 수 없습니다.`}
        confirmLabel="삭제"
        cancelLabel="취소"
        danger
        onConfirm={() => void confirmCodeDelete()}
        onCancel={() => setCodeDeleteTarget(null)}
      />

      {toast ? (
        <div className="codes-toast">
          <Toast tone={toast.tone} message={toast.message} />
        </div>
      ) : null}
    </>
  );
}
