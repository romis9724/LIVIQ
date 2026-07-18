// E2E 전용 mock OAuth IdP — 실제 구글 대신 즉시 로그인 성공을 흉내낸다 (H6-1).
//
// api oauth.py는 토큰 엔드포인트 응답의 id_token payload를 base64 디코드만 한다(서명 미검증 —
// HTTPS 토큰 채널을 신뢰). 따라서 무서명 JWT(header.payload.sig)로 충분하다.
//   GET  /authorize → redirect_uri?code=...&state=... 로 즉시 302(사용자 동의 화면 생략)
//   POST /token     → { id_token, access_token } (sub·email 클레임)
//   GET  /health    → 200(webServer 준비 확인용)
//
// 다중 신원(H6-4): api는 /authorize URL에 커스텀 파라미터를 실어주지 않으므로, 브라우저가
// mock 오리진(localhost:9099)에 보내는 `mock_sub` 쿠키로 sub를 지정한다. /authorize가 그 sub를
// code에 실어 302하고, /token은 code에서 sub를 복원한다(api→/token은 서버 호출이라 쿠키 없음).
// 쿠키가 없으면 MOCK_IDP_SUB(기본=시드 활성 사용자) — 기존 auth.setup 회귀 없음.

import http from "node:http";

const PORT = Number(process.env.MOCK_IDP_PORT ?? 9099);
const SUB = process.env.MOCK_IDP_SUB ?? "e2e-google-sub-0001";
const EMAIL = process.env.MOCK_IDP_EMAIL ?? "e2e@example.com";

const CODE_PREFIX = "mock-code.";

/** base64url(JSON) — 무서명 JWT 세그먼트. */
function seg(obj) {
  return Buffer.from(JSON.stringify(obj)).toString("base64url");
}

/** Cookie 헤더에서 이름=값 파싱(mock 전용, 단순). */
function readCookie(header, name) {
  for (const part of (header ?? "").split(";")) {
    const [k, ...v] = part.trim().split("=");
    if (k === name) return decodeURIComponent(v.join("="));
  }
  return null;
}

/** sub를 code에 base64url로 실어 왕복시킨다(브라우저 code → api → /token). */
function encodeCode(sub) {
  return CODE_PREFIX + Buffer.from(sub, "utf-8").toString("base64url");
}
function decodeCode(code) {
  if (!code || !code.startsWith(CODE_PREFIX)) return SUB;
  return Buffer.from(code.slice(CODE_PREFIX.length), "base64url").toString(
    "utf-8",
  );
}

function idToken(sub) {
  return `${seg({ alg: "none", typ: "JWT" })}.${seg({ sub, email: EMAIL })}.sig`;
}

async function readBody(req) {
  let data = "";
  for await (const chunk of req) data += chunk;
  return data;
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://localhost:${PORT}`);

  if (url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("ok");
    return;
  }

  if (url.pathname === "/authorize") {
    const redirectUri = url.searchParams.get("redirect_uri");
    const state = url.searchParams.get("state") ?? "";
    if (!redirectUri) {
      res.writeHead(400);
      res.end("redirect_uri required");
      return;
    }
    const sub = readCookie(req.headers.cookie, "mock_sub") ?? SUB;
    const to = `${redirectUri}?code=${encodeCode(sub)}&state=${encodeURIComponent(state)}`;
    res.writeHead(302, { Location: to });
    res.end();
    return;
  }

  if (url.pathname === "/token" && req.method === "POST") {
    void readBody(req).then((body) => {
      const code = new URLSearchParams(body).get("code");
      const token = idToken(decodeCode(code));
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(
        JSON.stringify({
          id_token: token,
          access_token: "discarded",
          token_type: "Bearer",
        }),
      );
    });
    return;
  }

  res.writeHead(404);
  res.end();
});

server.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`[mock-idp] listening on http://localhost:${PORT}`);
});
