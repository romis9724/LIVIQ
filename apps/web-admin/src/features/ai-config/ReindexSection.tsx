// 재색인 섹션(H15-3) — 전 단지 문서·공지 재인제스트 enqueue + 진행 현황 폴링.
// 저장 폼과 무관한 별개 액션이라 폼 밖에 둔다(중첩 form 금지).

import { useCallback, useEffect, useState } from "react";
import { Button } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import { ApiError } from "@/lib/api";
import { getReindexStatus, isReindexRunning, startReindex, type ReindexStatus } from "./data";

const POLL_INTERVAL_MS = 5000;

const CONFIRM_MESSAGE =
  "전 단지의 문서·공지를 다시 색인합니다. 완료까지 검색 품질이 일시적으로 낮아질 수 있습니다. 시작할까요?";

interface ReindexSectionProps {
  showToast: (message: string, tone?: ToastTone) => void;
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

export function ReindexSection({ showToast }: ReindexSectionProps) {
  const [status, setStatus] = useState<ReindexStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getReindexStatus());
      setStatusError(null);
    } catch (err) {
      setStatusError(errorMessage(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // 진행 중일 때만 5초 뒤 재조회 — status 변화가 다음 타이머를 예약한다.
  useEffect(() => {
    if (!status || !isReindexRunning(status)) return;
    const timer = setTimeout(() => void refresh(), POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [status, refresh]);

  async function start() {
    if (!window.confirm(CONFIRM_MESSAGE)) return;
    setStarting(true);
    try {
      const result = await startReindex();
      showToast(
        `재색인을 시작했습니다 — 문서 ${result.enqueuedDocuments}건 · 공지 ${result.enqueuedNotices}건 대기열에 넣었습니다.`,
      );
      await refresh();
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setStarting(false);
    }
  }

  return (
    <section className="surface-card ai-cfg" aria-labelledby="ai-cfg-reindex-h">
      <h2 id="ai-cfg-reindex-h" className="ai-cfg__title">
        재색인
      </h2>
      <p className="ai-cfg__lede">
        임베딩·청크 설정을 바꾼 뒤 기존 색인을 새 설정으로 다시 만듭니다.
      </p>

      <p className="ai-cfg__notice ai-cfg__notice--warn">
        대상: 전 단지의 문서·공지 전량. 완료까지 검색 품질이 일시적으로 낮아질 수 있습니다.
      </p>

      <div className="ai-cfg__fields">
        {statusError ? (
          <p className="ai-cfg__result ai-cfg__result--fail" role="alert">
            색인 현황을 불러오지 못했습니다 — {statusError}
          </p>
        ) : status ? (
          <p className="ai-cfg__status" role="status">
            대기 {status.pending} · 진행 {status.indexing} · 완료 {status.indexed} · 실패{" "}
            {status.failed} / {status.total}
          </p>
        ) : null}

        <div className="ai-cfg__actions">
          <Button type="button" variant="secondary" disabled={starting} onClick={() => void start()}>
            {starting ? "시작 중…" : "재색인 시작"}
          </Button>
        </div>
      </div>
    </section>
  );
}
