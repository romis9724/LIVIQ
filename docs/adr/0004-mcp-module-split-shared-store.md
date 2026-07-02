# ADR-0004: mcp 관리 에이전트 모듈 분할 + 공유 store

- 상태: Accepted
- 날짜: 2026-07-02
- 관련: [mcp/CLAUDE.md](../../mcp/CLAUDE.md), [mcp/fee_agent/](../../mcp/fee_agent)

## 맥락

`mcp/management_agent.py`가 406줄 단일 파일로, 설정·시트 파싱·메일·툴·에이전트·엔트리가
한데 섞여 있었다(god file). 전역 가변 상태(`MGMT_ROWS`·`RESIDENT_ROWS`·`HO_LIST`)를
`global` 재할당으로 관리해, 모듈 분할 시 참조가 깨지는 위험이 있었다.

## 결정

기능별로 `fee_agent/` 패키지(config·store·sheets·mailer·tools·agent)로 분할하고,
전역 재할당 대신 **단일 가변 객체 `FeeStore`를 모듈 간 참조로 공유**한다.
`management_agent.py`는 얇은 엔트리(로딩·샘플 폴백·대화 루프)만 남긴다.

## 대안

- **전역 변수를 그대로 두고 파일만 분리**: `from sheets import MGMT_ROWS`는 import 시점
  참조를 복사 → `load_sheet_data`의 재할당이 전파되지 않음. 버그 유발. 기각.
- **분할하지 않음**: 406줄은 800 상한 미만이나 응집도 낮고 AI 탐색·수정 비용 큼. 기각.

## 결과

- 최대 파일 147줄, 엔트리 114줄. 300줄 초과 0건.
- 툴은 `make_tools(store)` 클로저로 store 바인딩 — 전역 의존 제거.
- 동작 보존: 로직 라인 단위 이전, `py_compile`·AST 통과. deps(langchain·mcp) 미설치라
  런타임 실행은 로컬 env 필요.
- 재검토 신호: 툴이 늘어 `tools.py`가 다시 비대해지면 툴별 파일로 재분할.
