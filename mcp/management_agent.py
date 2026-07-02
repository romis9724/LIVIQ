# ─────────────────────────────────────────────────────────────────────────────
# 아파트 관리비 AI 에이전트 (엔트리)
#
# 시나리오:
#   1. "101호 관리비는 얼마야?"
#   2. "전체 관리비 평균은 얼마야?"
#   3. "101호 관리비 정보를 입주민에게 메일로 보내줘"
#
# LLM      : Ollama 로컬 (기본 gemma4:e4b, OLLAMA_MODEL 로 변경)
# 프레임워크: LangChain @tool + create_agent
# 데이터    : Google Sheets MCP (xing5/mcp-google-sheets, stdio) - 서비스 계정 인증
# 메일      : 로컬 Gmail MCP (gmail_mcp_server.py, stdio) - tokens.json OAuth
# Claude X  : Anthropic API 미사용
#
# 실로직은 fee_agent/ 패키지로 분할:
#   config(설정·자격증명·MCP·LLM) · store(상태) · sheets(데이터) ·
#   mailer(메일) · tools(툴) · agent(생성)
#
# 자격증명 (mcp/ 디렉토리, .gitignore 처리됨):
#   service-credential.json  Google 서비스 계정 키 (Sheets 읽기)
#   tokens.json              Gmail OAuth 토큰 (메일 발송)
#
# 실행:
#   # uv 설치 (Sheets MCP 서버 구동용): https://docs.astral.sh/uv/
#   pip install langchain langchain-ollama "mcp[cli]" \
#               google-auth google-api-python-client
#   ollama pull gemma4:e4b   # 또는 OLLAMA_MODEL 로 보유 모델 지정
#   python management_agent.py
# ─────────────────────────────────────────────────────────────────────────────

import os

from fee_agent.agent import build_agent
from fee_agent.config import build_llm
from fee_agent.sheets import load_sheet_data
from fee_agent.store import FeeStore
from fee_agent.tools import make_tools


def _populate_sample(store: FeeStore) -> None:
    """MCP 로드 실패 시 사용할 샘플 데이터. PII는 하드코딩하지 않는다."""
    store.mgmt_rows.extend([
        {"구분":"공용관리비",  "항목":"일반관리비",    "단위":"원","101호":8500, "102호":8500, "103호":8500, "104호":8500, "105호":8500, "합계":42500},
        {"구분":"공용관리비",  "항목":"청소비",        "단위":"원","101호":5200, "102호":5200, "103호":5200, "104호":5200, "105호":5200, "합계":26000},
        {"구분":"공용관리비",  "항목":"경비비",        "단위":"원","101호":15000,"102호":15000,"103호":15000,"104호":15000,"105호":15000,"합계":75000},
        {"구분":"장기수선충당금","항목":"장기수선충당금","단위":"원","101호":12000,"102호":12000,"103호":12000,"104호":12000,"105호":12000,"합계":60000},
        {"구분":"사용료",      "항목":"난방비",        "단위":"원","101호":45000,"102호":38000,"103호":52000,"104호":41000,"105호":47000,"합계":223000},
        {"구분":"개별사용료",  "항목":"전기료(세대)",  "단위":"원","101호":32000,"102호":28000,"103호":41000,"104호":35000,"105호":29000,"합계":165000},
        {"구분":"개별사용료",  "항목":"수도료(세대)",  "단위":"원","101호":18000,"102호":15000,"103호":22000,"104호":19000,"105호":16000,"합계":90000},
        {"구분":"개별사용료",  "항목":"인터넷 사용료", "단위":"원","101호":11000,"102호":11000,"103호":11000,"104호":11000,"105호":11000,"합계":55000},
        {"구분":"기타",        "항목":"주차장관리비",  "단위":"원","101호":5000, "102호":5000, "103호":0,    "104호":5000, "105호":5000, "합계":20000},
    ])
    # 샘플 수신자 주소는 env SAMPLE_EMAIL 로 주입 (PII 하드코딩 금지)
    sample_email = os.environ.get("SAMPLE_EMAIL", "test@example.com")
    store.resident_rows.extend([
        {"ho":"101호","name":"홍길동","email":sample_email},
        {"ho":"102호","name":"손흥민","email":sample_email},
        {"ho":"103호","name":"박지성","email":sample_email},
        {"ho":"104호","name":"이강인","email":sample_email},
        {"ho":"105호","name":"김민재","email":sample_email},
    ])
    store.ho_list.extend(["101호","102호","103호","104호","105호"])


def run_scenario(agent, label: str, question: str):
    print("=" * 55)
    print(f"시나리오 : {label}")
    print(f"질문     : {question}")
    print("=" * 55)
    response = agent.invoke({"messages": [("user", question)]})
    print("ai: ", response["messages"][-1].content)
    print()


def main():
    store = FeeStore()
    llm = build_llm()

    # ── 데이터 로딩 ───────────────────────────────────────────────
    print("📋 Google Sheets MCP 데이터 로딩 중...")
    try:
        load_sheet_data(store)
        print(f"   ✅ 관리비 항목: {len(store.mgmt_rows)}개  호실: {store.ho_list}")
        print(f"   ✅ 주민정보: {len(store.resident_rows)}명\n")
    except Exception as e:
        print(f"   ⚠ MCP 로드 실패 ({e}) → 샘플 데이터 사용\n")
        _populate_sample(store)

    tools = make_tools(store)
    agent = build_agent(llm, tools)

    # ── 시나리오 3개 실행 (필요 시 주석 해제) ─────────────────────
#    run_scenario(agent, "특정 호실 관리비 조회",       "101호 관리비는 얼마야?")
#    run_scenario(agent, "전체 관리비 평균 조회",       "전체 관리비의 평균은 얼마야?")
#    run_scenario(agent, "입주민에게 관리비 메일 발송", "101호 관리비 정보를 입주민에게 메일로 보내줘")

    # ── 대화형 루프 ───────────────────────────────────────────────
    print("─" * 55)
    print("🏢 대화형 모드 시작  (종료: q)")
    print("─" * 55)
    while True:
        user_input = input("질문: ").strip()
        if not user_input:
            continue
        if user_input.lower() in ("q", "quit", "exit"):
            print("에이전트를 종료합니다.")
            break
        response = agent.invoke({"messages": [("user", user_input)]})
        print("ai: ", response["messages"][-1].content)
        print("-" * 55)


if __name__ == "__main__":
    main()
