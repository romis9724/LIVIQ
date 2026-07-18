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
// 명시 override가 없으면 sub에서 파생(sub@demo.liviq) — 계정마다 다른 이메일 클레임.
// 콜백은 email을 저장하지 않으므로(sub만 신원 확정) 값은 표시용에 가깝다.
const EMAIL_OVERRIDE = process.env.MOCK_IDP_EMAIL ?? null;
// 수동 통합테스트 계정 선택 화면 토글. 미설정 시 기존 즉시 302(E2E 무회귀).
const INTERACTIVE = process.env.MOCK_IDP_INTERACTIVE === "1";

const CODE_PREFIX = "mock-code.";

// 계정 선택 화면 목록 — apps/api/scripts/seed_demo.py 의 ACTIVE_ACCOUNTS·ROSTER_PEOPLE 와 일치.
// 신규 가입용 sub(demo-signup-*)는 users에 없음 → 로그인 시 온보딩 여정으로 진입한다.
const ACCOUNTS = [
  { sub: "demo-manager", label: "김소장", hint: "관리소장 (MANAGER)" },
  { sub: "demo-staff", label: "박직원", hint: "일반직원 (STAFF)" },
  { sub: "demo-facility", label: "이기사", hint: "시설기사 (FACILITY)" },
  { sub: "demo-resident", label: "최주민", hint: "입주민 (RESIDENT)" },
  { sub: "demo-signup-1", label: "정가입", hint: "신규 가입 — 명부 대조 (정가입)" },
  { sub: "demo-signup-2", label: "한신규", hint: "신규 가입 — 명부 대조 (한신규)" },
];

/** HTML 특수문자 이스케이프(속성·본문 삽입 안전). */
function esc(value) {
  return String(value).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

/** 구글식 계정 선택 페이지 — 각 계정/직접 입력이 같은 /authorize 로 sub를 실어 재요청. */
function accountPickerHtml(redirectUri, state) {
  const hidden = `<input type="hidden" name="redirect_uri" value="${esc(redirectUri)}"><input type="hidden" name="state" value="${esc(state)}">`;
  const rows = ACCOUNTS.map(
    (a) => `
      <form method="GET" action="/authorize" class="row">
        ${hidden}
        <button type="submit" name="sub" value="${esc(a.sub)}" class="acct">
          <span class="avatar">${esc(a.label[0])}</span>
          <span class="meta"><b>${esc(a.label)}</b><small>${esc(a.hint)} · ${esc(a.sub)}@demo.liviq</small></span>
        </button>
      </form>`,
  ).join("");
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>계정 선택 — LIVIQ mock IdP</title>
<style>
  body{font-family:system-ui,sans-serif;background:#f6f8fc;margin:0;padding:2rem;color:#202124}
  .card{max-width:420px;margin:0 auto;background:#fff;border:1px solid #dadce0;border-radius:12px;overflow:hidden}
  h1{font-size:1.25rem;padding:1.5rem 1.5rem 0.5rem;margin:0}
  p.sub{padding:0 1.5rem 1rem;margin:0;color:#5f6368;font-size:.9rem}
  .acct{display:flex;align-items:center;gap:12px;width:100%;padding:12px 1.5rem;border:0;border-top:1px solid #ecedef;background:#fff;text-align:left;cursor:pointer;font:inherit}
  .acct:hover{background:#f1f3f4}
  .avatar{width:36px;height:36px;border-radius:50%;background:#1a73e8;color:#fff;display:grid;place-items:center;font-weight:600}
  .meta{display:flex;flex-direction:column}
  .meta small{color:#5f6368;font-size:.8rem}
  .custom{display:flex;gap:8px;padding:12px 1.5rem;border-top:1px solid #ecedef}
  .custom input{flex:1;padding:8px;border:1px solid #dadce0;border-radius:6px;font:inherit}
  .custom button{padding:8px 12px;border:0;border-radius:6px;background:#1a73e8;color:#fff;cursor:pointer}
</style></head><body>
  <div class="card">
    <h1>계정 선택</h1>
    <p class="sub">LIVIQ mock IdP — 계속하려면 계정을 선택하세요.</p>
    ${rows}
    <form method="GET" action="/authorize" class="custom">
      ${hidden}
      <input type="text" name="sub" placeholder="직접 입력 (sub)" aria-label="sub 직접 입력">
      <button type="submit">로그인</button>
    </form>
  </div>
</body></html>`;
}

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
  const email = EMAIL_OVERRIDE ?? `${sub}@demo.liviq`;
  return `${seg({ alg: "none", typ: "JWT" })}.${seg({ sub, email })}.sig`;
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
    const chosenSub = url.searchParams.get("sub")?.trim();
    // INTERACTIVE 모드 + 아직 계정 미선택 → 계정 선택 화면(사람이 직접 고르는 여정).
    if (INTERACTIVE && !chosenSub) {
      res.writeHead(200, { "Content-Type": "text/html; charset=utf-8" });
      res.end(accountPickerHtml(redirectUri, state));
      return;
    }
    // 선택된 sub(폼) 우선, 없으면 기존 경로(mock_sub 쿠키 → 기본 SUB) — E2E 무회귀.
    const sub = chosenSub || readCookie(req.headers.cookie, "mock_sub") || SUB;
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
