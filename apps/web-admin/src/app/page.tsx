// 관리자 진입점 — 역할별 첫 진입은 AdminShell이 /me로 판단해 라우팅한다(H7-2).
// 여기서 서버 리다이렉트하지 않는 이유: 역할(세션)을 서버 컴포넌트가 알 수 없어서다.
export default function AdminIndex() {
  return null;
}
