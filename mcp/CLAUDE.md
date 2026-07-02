# mcp

Python MCP 서버 · 관리 에이전트. 외부 시스템(Gmail·아파트 관리) 연동 계층.
TypeScript 모노레포와 분리된 Python 트리 — pnpm/turbo가 관리하지 않음.

## 구조

```text
gmail_mcp_server.py     Gmail MCP 서버
apt_mcp_server.py       아파트 관리(apt) MCP 서버
management_agent.py     관리 에이전트 (406줄 — 분할 대상, 아래 참조)
reauth_gmail.py         Gmail OAuth 재인증 스크립트
```

## 핵심 파일

- `management_agent.py` — 에이전트 엔트리(main·대화 루프·샘플 폴백). 실로직은 `fee_agent/` 패키지로 분할됨.
- `fee_agent/` — `config`·`store`·`sheets`·`mailer`·`tools`·`agent` 모듈
- `gmail_mcp_server.py` / `apt_mcp_server.py` — 각 MCP 서버 엔트리

## 의존성 (상세 그래프: [../ARCHITECTURE.md](../ARCHITECTURE.md))

- 의존: 외부 — Gmail API(OAuth) · Google Sheets(서비스 계정) · Ollama 로컬 LLM
- 피의존: 없음 (독립 실행 · TS 워크스페이스와 코드 공유 없음)
- 계약: MCP 프로토콜(stdio)로만. 변경 파급은 MCP 서버 인터페이스 경계에 국한

## 규칙 (Why · CRITICAL)

- `service-credential.json` · `tokens.json` 은 **시크릿**. `.gitignore`로 차단됨 —
  절대 커밋·로그 출력 금지. Why: 루트 절대규칙 2·시크릿 하드코딩 금지.
- 개인정보를 외부 LLM에 넘기기 전 마스킹, 실패 시 호출 중단(fail-closed). Why: 절대규칙 2.
- MCP 툴 출력이 권한·발송 등 부수효과를 직접 트리거하지 않음. Why: 절대규칙 8.
- 답변 근거 없으면 담당자 연결 폴백. Why: 절대규칙 1.

## 명령 (Python · TS 파이프라인 밖)

```bash
pip install ruff mypy
ruff check .     # 린트
ruff format .    # 포맷
mypy .           # 타입체크
```

설정: `pyproject.toml`. CI: `.github/workflows/python-mcp.yml`.
