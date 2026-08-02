// @vitest-environment jsdom
// 복원 경로의 상태 전이만 본다(SSE·질의는 대상 아님) — `restored` 는 호출부의 브리핑
// 게이트가 걸린 계약이라 "언제 true 가 되는가"가 전부다(ADR-0028 결정 2 개정, H20-3).
import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RestoredThread } from "./assistant-restore";
import type { FetchLike } from "./assistant-events";
import { useAssistantStream, type ChatMessage } from "./useAssistantStream";

const KEY = "liviq.test.restore.thread";

/** 복원 경로는 fetch 를 쓰지 않는다 — 불려 나가면 테스트가 터지도록 둔다. */
const apiFetch: FetchLike = () => Promise.reject(new Error("호출되면 안 된다"));

function options(fetchLatest?: () => Promise<RestoredThread>) {
  return { askUrl: "/ask", apiFetch, storageKey: KEY, fetchLatest };
}

const STORED: ChatMessage[] = [{ id: "s1", role: "user", text: "저장된 질문" }];

afterEach(() => window.sessionStorage.clear());

describe("useAssistantStream 복원", () => {
  it("탭 저장본이 있으면 서버를 부르지 않고 복원 완료", async () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ messages: STORED, conversationId: "c1" }));
    const fetchLatest = vi.fn();

    const { result } = renderHook(() => useAssistantStream(options(fetchLatest)));

    await waitFor(() => expect(result.current.restored).toBe(true));
    expect(result.current.messages).toHaveLength(1);
    expect(fetchLatest).not.toHaveBeenCalled();
  });

  it("'새 대화' 마커(0건 저장)도 복원 완료 — 서버 복원은 건너뛴다", async () => {
    window.sessionStorage.setItem(KEY, JSON.stringify({ messages: [], conversationId: null }));
    const fetchLatest = vi.fn();

    const { result } = renderHook(() => useAssistantStream(options(fetchLatest)));

    await waitFor(() => expect(result.current.restored).toBe(true));
    expect(result.current.messages).toEqual([]);
    expect(fetchLatest).not.toHaveBeenCalled();
  });

  it("서버 복원이 없는 화면도 복원 완료", async () => {
    const { result } = renderHook(() => useAssistantStream(options()));

    await waitFor(() => expect(result.current.restored).toBe(true));
    expect(result.current.messages).toEqual([]);
  });

  it("서버 복원 성공이면 메시지와 함께 복원 완료", async () => {
    const fetchLatest = () =>
      Promise.resolve({ conversationId: "c9", messages: [...STORED] } satisfies RestoredThread);

    const { result } = renderHook(() => useAssistantStream(options(fetchLatest)));

    await waitFor(() => expect(result.current.restored).toBe(true));
    expect(result.current.messages).toHaveLength(1);
  });

  it("서버 복원이 빈 응답이어도 복원 완료 — 호출부는 '정말 빈 대화'로 판정해야 한다", async () => {
    const fetchLatest = () =>
      Promise.resolve({ conversationId: null, messages: [] } satisfies RestoredThread);

    const { result } = renderHook(() => useAssistantStream(options(fetchLatest)));

    await waitFor(() => expect(result.current.restored).toBe(true));
    expect(result.current.messages).toEqual([]);
  });

  it("서버 복원 실패도 복원 완료 — 화면을 막지 않는다", async () => {
    const fetchLatest = () => Promise.reject(new Error("네트워크"));

    const { result } = renderHook(() => useAssistantStream(options(fetchLatest)));

    await waitFor(() => expect(result.current.restored).toBe(true));
    expect(result.current.messages).toEqual([]);
  });
});

describe("useAssistantStream ask", () => {
  const sse = () =>
    new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            'event: done\ndata: {"conversation_id":"c1","status":"answered","confidence":0.9,"needs_review":false}\n\n',
          ),
        );
        controller.close();
      },
    });

  it("extraBody 를 요청 body 에 얹는다 — 자동 발화의 allow_clarify:false(H20-3)", async () => {
    // Arrange
    const bodies: string[] = [];
    const capturing: FetchLike = async (_url, init) => {
      bodies.push(String(init?.body));
      return new Response(sse());
    };
    const { result } = renderHook(() =>
      useAssistantStream({ askUrl: "/ask", apiFetch: capturing, storageKey: KEY }),
    );
    await waitFor(() => expect(result.current.restored).toBe(true));

    // Act — 두 번째 ask 는 pending 이 풀린 뒤라야 실행된다(훅의 중복 전송 가드).
    await act(async () => {
      await result.current.ask("브리핑", { allow_clarify: false });
    });
    await waitFor(() => expect(result.current.pending).toBe(false));
    await act(async () => {
      await result.current.ask("직접 친 질문");
    });

    // Assert — 안 주면 종전 그대로(필드 없음).
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(JSON.parse(bodies[0]!)).toMatchObject({ question: "브리핑", allow_clarify: false });
    expect(JSON.parse(bodies[1]!)).not.toHaveProperty("allow_clarify");
  });
});
