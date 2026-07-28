/**
 * SSE 호출·파싱 공용 헬퍼 — adapter.mjs(하드룰 러너)와 rag500.mjs(품질 측정)가 공유한다.
 *
 * 계약: postSse(url, body, headers) → { text, citations, done, ttftMs, totalMs }
 *   - text: token 이벤트 누적 · citations: citation 이벤트 배열 · done: done 이벤트 payload
 *   - ttftMs: 첫 SSE 이벤트까지(ms) · totalMs: 스트림 종료까지(ms)
 * non-ok 응답은 `err.status`를 담아 throw(호출자가 pending/error로 처리).
 */

/** POST SSE → 파싱 결과. non-ok는 status 담은 에러로 throw. */
export async function postSse(url, body, headers) {
  const startedAt = Date.now();
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const err = new Error(`${url} ${response.status}`);
    err.status = response.status;
    throw err;
  }
  return consumeSse(response, startedAt);
}

/** SSE 프레임 소비 — sse-starlette CRLF를 정규화(docs/09 §1.1 이벤트 4종). */
export async function consumeSse(response, startedAt = Date.now()) {
  const citations = [];
  let text = "";
  let done = null;
  let ttftMs = null;
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done: streamDone, value } = await reader.read();
    if (streamDone) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
    buffer = parts.pop() ?? "";
    for (const block of parts) {
      let event = "message";
      const dataLines = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
      }
      if (dataLines.length === 0) continue;
      if (ttftMs === null) ttftMs = Date.now() - startedAt;
      const data = JSON.parse(dataLines.join("\n"));
      if (event === "citation") citations.push(data);
      else if (event === "token") text += data.text ?? "";
      else if (event === "done") done = data;
    }
  }
  return { text, citations, done, ttftMs, totalMs: Date.now() - startedAt };
}
