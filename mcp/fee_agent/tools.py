"""LangChain 툴 정의. store 를 클로저로 바인딩해 make_tools 로 생성한다."""

import asyncio

from langchain.tools import tool

from .config import BUILDING_NAME, BILLING_PERIOD, OFFICE_PHONE
from .mailer import send_gmail
from .sheets import build_detail
from .store import FeeStore


def make_tools(store: FeeStore):
    """store 에 바인딩된 3개 툴 리스트 반환."""

    @tool
    def query_ho_fee(ho: str) -> str:
        """
        특정 호실의 관리비 상세 내역을 조회합니다.
        예시 입력: "101호" 또는 "102호"
        관리비 시트에서 항목별 금액과 합계를 반환합니다.
        """
        ho = ho.strip()
        if not ho.endswith("호"):
            ho = ho + "호"

        result = build_detail(store, ho)
        print(f"[query_ho_fee 툴 작동] 호실: {ho}")
        return result

    @tool
    def query_average_fee(dummy: str = "") -> str:
        """
        전체 호실의 관리비 합계와 평균을 계산하여 반환합니다.
        입력값은 무시해도 됩니다.
        """
        totals = {
            ho: sum(row.get(ho, 0) or 0 for row in store.mgmt_rows)
            for ho in store.ho_list
        }
        avg = sum(totals.values()) / len(totals) if totals else 0

        lines = ["[전체 관리비 현황]"]
        for ho, fee in sorted(totals.items()):
            lines.append(f"  {ho}: {fee:,}원")
        lines.append(f"\n평균 관리비: {avg:,.0f}원")

        result = "\n".join(lines)
        print(f"[query_average_fee 툴 작동] 평균: {avg:,.0f}원")
        return result

    @tool
    def send_fee_email(ho: str) -> str:
        """
        특정 호실 입주민에게 관리비 안내 메일을 발송합니다.
        주민정보 시트에서 이름과 이메일을 조회한 뒤 Gmail MCP로 전송합니다.
        예시 입력: "101호"
        """
        ho = ho.strip()
        if not ho.endswith("호"):
            ho = ho + "호"

        resident = next((r for r in store.resident_rows if r["ho"] == ho), None)
        if not resident:
            return f"❌ {ho} 주민정보 없음"

        name = resident["name"]
        email = resident["email"]
        detail = build_detail(store, ho)

        subject = f"[관리비 안내] {ho} {name} 님의 {BILLING_PERIOD} 관리비"
        body = (
            f"{name} 님 안녕하세요.\n\n"
            f"{BUILDING_NAME} {ho} {BILLING_PERIOD} 관리비 안내드립니다.\n\n"
            f"{detail}\n\n"
            f"납부 기한 내에 납부해 주시기 바랍니다.\n"
            f"문의: 관리사무소 ☎ {OFFICE_PHONE}\n\n"
            f"감사합니다.\n관리사무소 드림"
        )

        print(f"[send_fee_email 툴 작동] {ho} → {name} ({email})")
        try:
            send_result = asyncio.run(send_gmail(to=email, subject=subject, body=body))
            return f"✅ {name} ({email}) 메일 발송 완료\n결과: {send_result}"
        except Exception as e:
            return f"❌ 메일 발송 실패: {e}"

    return [query_ho_fee, query_average_fee, send_fee_email]
