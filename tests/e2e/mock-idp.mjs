// E2E 전용 mock OAuth IdP — 실제 구글 대신 즉시 로그인 성공을 흉내낸다 (H6-1).
//
// api oauth.py는 토큰 엔드포인트 응답의 id_token payload를 base64 디코드만 한다(서명 미검증 —
// HTTPS 토큰 채널을 신뢰). 따라서 무서명 JWT(header.payload.sig)로 충분하다.
//   GET  /authorize → redirect_uri?code=...&state=... 로 즉시 302(사용자 동의 화면 생략)
//   POST /token     → { id_token, access_token } (sub·email 클레임)
//   GET  /health    → 200(webServer 준비 확인용)

import http from "node:http";

const PORT = Number(process.env.MOCK_IDP_PORT ?? 9099);
const SUB = process.env.MOCK_IDP_SUB ?? "e2e-google-sub-0001";
const EMAIL = process.env.MOCK_IDP_EMAIL ?? "e2e@example.com";

/** base64url(JSON) — 무서명 JWT 세그먼트. */
function seg(obj) {
  return Buffer.from(JSON.stringify(obj)).toString("base64url");
}
const ID_TOKEN = `${seg({ alg: "none", typ: "JWT" })}.${seg({ sub: SUB, email: EMAIL })}.sig`;

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
    const to = `${redirectUri}?code=mock-code&state=${encodeURIComponent(state)}`;
    res.writeHead(302, { Location: to });
    res.end();
    return;
  }

  if (url.pathname === "/token" && req.method === "POST") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ id_token: ID_TOKEN, access_token: "discarded", token_type: "Bearer" }));
    return;
  }

  res.writeHead(404);
  res.end();
});

server.listen(PORT, () => {
  // eslint-disable-next-line no-console
  console.log(`[mock-idp] listening on http://localhost:${PORT}`);
});
