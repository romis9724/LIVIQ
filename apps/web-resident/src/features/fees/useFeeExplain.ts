"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type FeeCitation,
  type FeeExplainDone,
  type ExplainStage,
  streamFeeExplain,
} from "./api";

export interface FeeExplainState {
  active: boolean; // 설명 요청이 시작됨(스트리밍 or 완료)
  streaming: boolean;
  stage: ExplainStage;
  text: string;
  citations: FeeCitation[];
  result: FeeExplainDone | null;
  error: boolean;
}

const INITIAL: FeeExplainState = {
  active: false,
  streaming: false,
  stage: "searching",
  text: "",
  citations: [],
  result: null,
  error: false,
};

/** 관리비 "왜 올랐나요?" 전용 얇은 SSE 소비 훅(대화 영속 없음). */
export function useFeeExplain() {
  const [state, setState] = useState<FeeExplainState>(INITIAL);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const explain = useCallback(async (period: string) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setState({ ...INITIAL, active: true, streaming: true });

    try {
      for await (const event of streamFeeExplain(period, controller.signal)) {
        switch (event.type) {
          case "status":
            setState((s) => ({ ...s, stage: event.stage }));
            break;
          case "token":
            setState((s) => ({ ...s, text: s.text + event.text }));
            break;
          case "citation":
            setState((s) => ({ ...s, citations: [...s.citations, event.citation] }));
            break;
          case "done":
            setState((s) => ({ ...s, streaming: false, result: event.result }));
            break;
        }
      }
    } catch {
      if (!controller.signal.aborted) {
        setState((s) => ({ ...s, streaming: false, error: true }));
      }
    } finally {
      if (abortRef.current === controller) {
        setState((s) => ({ ...s, streaming: false }));
      }
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(INITIAL);
  }, []);

  return { state, explain, reset };
}
