"""민원 데모 시드 데이터 — 첫마을 4단지 가상 입주민·민원 30건 (시연용).

가공 데이터다(실제 접수 민원 아님). facility는 seed_facilities_kapt가 적재한 시설
`name`과 **정확히 일치**해야 한다 — 못 찾으면 시드가 중단된다(조용한 skip 금지).

status 분포: received 6 · assigned 8 · in_progress 8 · done 8.
reassign=True인 건은 첫 배정 며칠 뒤 다른 담당자로 재배정된 이력을 남긴다.
"""

from __future__ import annotations

from typing import NamedTuple

# 가상 입주민: (이름, 이메일 로컬파트 번호) — 이메일은 demo-r01@example.com 형식.
RESIDENT_NAMES: tuple[str, ...] = (
    "이서연",
    "박민준",
    "김지우",
    "최현우",
    "정하은",
    "강도윤",
    "윤서준",
    "임수아",
    "한지호",
    "오유진",
)


class InquirySeed(NamedTuple):
    """민원 1건. facility는 DB 실존 시설명(없으면 None), reply는 done 건의 담당자 답변."""

    title: str
    body: str
    category: str  # INQUIRY_CATEGORY 라벨(설비·하자·소음·주차·공용부·보안·기타)
    facility: str | None
    priority: str  # urgent|normal|low
    days_ago: int
    status: str  # received|assigned|in_progress|done
    reassign: bool
    reply: str | None = None


# --- 시설 정식 연결 10건(전부 category "설비") ---
_WITH_FACILITY: tuple[InquirySeed, ...] = (
    InquirySeed(
        title="401동 1호기 승강기에서 쇠 긁히는 소리가 납니다",
        body=(
            "며칠 전부터 401동 1호기 엘리베이터가 올라갈 때 쇠 긁히는 소리가 크게 납니다. "
            "특히 10층을 지날 때쯤 소리가 심해지고 살짝 흔들리기도 합니다. "
            "아이들이랑 같이 타는데 불안해서 점검 부탁드립니다."
        ),
        category="설비",
        facility="401동 1호기 승강기",
        priority="urgent",
        days_ago=12,
        status="in_progress",
        reassign=True,
    ),
    InquirySeed(
        title="403동 2호기 승강기 문이 늦게 닫힙니다",
        body=(
            "403동 2호기 엘리베이터 문이 닫히는 데 10초 넘게 걸립니다. "
            "닫히다가 다시 열리는 경우도 하루에 몇 번씩 있습니다. 출근 시간에 많이 밀려요."
        ),
        category="설비",
        facility="403동 2호기 승강기",
        priority="normal",
        days_ago=9,
        status="assigned",
        reassign=False,
    ),
    InquirySeed(
        title="온수가 미지근하게만 나옵니다",
        body=(
            "지난주부터 저녁 시간대에 온수를 틀면 미지근한 물만 나옵니다. "
            "5분 정도 틀어놔도 온도가 올라가지 않네요. 옆집도 같은 증상이라고 합니다. "
            "지역난방 쪽 문제인지 확인 부탁드립니다."
        ),
        category="설비",
        facility="지역난방 열교환기",
        priority="normal",
        days_ago=41,
        status="done",
        reassign=True,
        reply=(
            "기계실 지역난방 열교환기 2차측 순환펌프 압력이 떨어져 있어 조정하고 "
            "스트레이너를 청소했습니다. 급탕 온도 55도 정상 확인했습니다. "
            "다시 미지근하면 바로 연락 주세요."
        ),
    ),
    InquirySeed(
        title="밤에 기계실 펌프 소리가 방까지 들립니다",
        body=(
            "저층이라 그런지 새벽에 급수펌프 돌아가는 소리가 방 안까지 울립니다. "
            "예전에는 이 정도가 아니었는데 최근 한 달 사이에 소리가 부쩍 커졌습니다."
        ),
        category="설비",
        facility="부스타 급수펌프",
        priority="normal",
        days_ago=22,
        status="in_progress",
        reassign=False,
    ),
    InquirySeed(
        title="전기차 충전기 3번기가 충전이 안 됩니다",
        body=(
            "지상주차장 충전기 3번기에 케이블을 꽂으면 인증까지는 되는데 충전이 시작되지 "
            "않습니다. 화면에 오류 코드가 뜨고 바로 종료됩니다. 다른 기기는 정상입니다."
        ),
        category="설비",
        facility="EV 완속충전기 8기(스탠드형·서울씨엔지)",
        priority="normal",
        days_ago=35,
        status="done",
        reassign=False,
        reply=(
            "충전기 운영사(서울씨엔지)에 접수해 3번기 통신모듈을 교체했습니다. "
            "현장에서 충전 개시·종료까지 확인했고 요금 오과금 건은 없었습니다."
        ),
    ),
    InquirySeed(
        title="공동현관 카드가 자주 인식되지 않습니다",
        body=(
            "공동현관에서 출입카드를 대면 세 번에 한 번꼴로 인식이 안 됩니다. "
            "비 오는 날에는 더 심합니다. 아이가 밖에서 한참 서 있던 적도 있어요."
        ),
        category="설비",
        facility="공동현관 출입시스템",
        priority="urgent",
        days_ago=6,
        status="assigned",
        reassign=False,
    ),
    InquirySeed(
        title="지하주차장 기둥 뒤쪽이 CCTV에 안 잡히는 것 같습니다",
        body=(
            "지하 2층 기둥 뒤 구역은 카메라가 향하는 방향이 아니어서 사각지대로 보입니다. "
            "그쪽에 주차한 차가 문콕을 당했는데 확인이 어렵다고 들었습니다. 각도 조정 부탁드립니다."
        ),
        category="설비",
        facility="CCTV 통합시스템(78대)",
        priority="low",
        days_ago=4,
        status="received",
        reassign=False,
    ),
    InquirySeed(
        title="놀이터 그네 체인이 많이 닳았습니다",
        body=(
            "어린이놀이터 그네 두 개 중 왼쪽 그네 체인 연결부가 눈에 띄게 닳아 있습니다. "
            "흔들 때마다 삐걱 소리도 납니다. 아이들이 매일 타는 곳이라 빨리 봐주셨으면 합니다."
        ),
        category="설비",
        facility="어린이놀이터",
        priority="urgent",
        days_ago=15,
        status="in_progress",
        reassign=True,
    ),
    InquirySeed(
        title="지하주차장에 매연이 오래 남아 있습니다",
        body=(
            "퇴근 시간대에 지하주차장에 내려가면 매연 냄새가 심하고 눈이 따갑습니다. "
            "환기팬이 도는 소리가 잘 안 들리는데 정상 가동 중인지 확인 부탁드립니다."
        ),
        category="설비",
        facility="지하주차장 환기팬",
        priority="normal",
        days_ago=18,
        status="assigned",
        reassign=False,
    ),
    InquirySeed(
        title="월패드에서 엘리베이터 호출이 안 됩니다",
        body=(
            "월패드 화면은 켜지는데 엘리베이터 호출 버튼을 눌러도 반응이 없습니다. "
            "가스밸브 확인 같은 다른 기능도 오류가 납니다. 언제 복구되는지 알려주세요."
        ),
        category="설비",
        facility="홈네트워크 서버",
        priority="normal",
        days_ago=28,
        status="done",
        reassign=True,
        reply=(
            "방재실 홈네트워크 서버 하드웨어 고장으로 교체 작업을 완료했습니다. "
            "승강기 호출·원격검침 기능 정상 동작을 세대에서 함께 확인했습니다."
        ),
    ),
)

# --- 시설 미연결 20건 ---
_WITHOUT_FACILITY: tuple[InquirySeed, ...] = (
    InquirySeed(
        title="지하 2층 조명이 계속 깜빡입니다",
        body=(
            "지하 2층 나열 구역 형광등 서너 개가 몇 초 간격으로 깜빡입니다. "
            "어두워서 주차선이 잘 안 보이고 눈도 피로합니다. 안정기 교체가 필요해 보입니다."
        ),
        category="공용부",
        facility=None,
        priority="normal",
        days_ago=20,
        status="in_progress",
        reassign=False,
    ),
    InquirySeed(
        title="위층 아이들 뛰는 소리가 밤 11시까지 이어집니다",
        body=(
            "평일 밤 10시가 넘어도 위층에서 아이들이 뛰는 소리가 계속됩니다. "
            "직접 말씀드리기가 조심스러워 관리사무소를 통해 안내 부탁드립니다."
        ),
        category="소음",
        facility=None,
        priority="normal",
        days_ago=3,
        status="received",
        reassign=False,
    ),
    InquirySeed(
        title="이중주차 차량 때문에 출차를 못 했습니다",
        body=(
            "오늘 아침 지하 1층에서 앞을 막은 이중주차 차량 때문에 30분 넘게 기다렸습니다. "
            "연락처도 안 붙어 있었습니다. 이중주차 시 연락처 부착 안내를 다시 해주세요."
        ),
        category="주차",
        facility=None,
        priority="normal",
        days_ago=30,
        status="done",
        reassign=False,
        reply=(
            "차량 번호로 세대를 확인해 개별 안내했고, 이중주차 연락처 부착 안내문을 "
            "각 동 게시판과 승강기 내부에 다시 게시했습니다."
        ),
    ),
    InquirySeed(
        title="분리수거장에서 냄새가 심하게 납니다",
        body=(
            "요즘 날이 더워져서인지 분리수거장 음식물 쪽에서 악취가 심합니다. "
            "근처 1층 세대는 창문을 못 열 정도입니다. 수거 주기를 늘리거나 세척을 부탁드립니다."
        ),
        category="공용부",
        facility=None,
        priority="normal",
        days_ago=17,
        status="in_progress",
        reassign=True,
    ),
    InquirySeed(
        title="복도에 자전거가 몇 달째 세워져 있습니다",
        body=(
            "우리 층 복도 끝에 자전거 두 대가 몇 달째 방치되어 있습니다. "
            "먼지가 쌓인 걸 보면 안 타는 것 같습니다. 대피 통로라 정리가 필요해 보입니다."
        ),
        category="공용부",
        facility=None,
        priority="low",
        days_ago=11,
        status="assigned",
        reassign=False,
    ),
    InquirySeed(
        title="어린이집 앞으로 과속하는 차량이 많습니다",
        body=(
            "등원 시간에 어린이집 앞 진입로를 빠르게 지나가는 차량이 많습니다. "
            "과속방지턱이나 서행 안내 표지가 있으면 좋겠습니다."
        ),
        category="기타",
        facility=None,
        priority="urgent",
        days_ago=5,
        status="received",
        reassign=False,
    ),
    InquirySeed(
        title="욕실 천장에서 물이 떨어집니다",
        body=(
            "며칠 전부터 욕실 천장 점검구 주변이 젖어 있고 물방울이 떨어집니다. "
            "위층에 여쭤보니 특별히 물을 많이 쓴 적은 없다고 합니다. "
            "배관 누수인지 확인 부탁드립니다."
        ),
        category="하자",
        facility=None,
        priority="urgent",
        days_ago=25,
        status="in_progress",
        reassign=True,
    ),
    InquirySeed(
        title="현관 도어록 건전지는 어디서 교체하나요",
        body=(
            "현관 도어록에서 건전지 부족 경고음이 계속 납니다. "
            "관리사무소에서 교체를 도와주시는지, 아니면 개별로 불러야 하는지 알려주세요."
        ),
        category="기타",
        facility=None,
        priority="low",
        days_ago=45,
        status="done",
        reassign=False,
        reply=(
            "도어록 건전지는 세대 부담이며 관리사무소에서 여분(AA 4개)을 판매하고 있습니다. "
            "직접 교체가 어려우시면 방문 도와드리니 내선으로 연락 주세요."
        ),
    ),
    InquirySeed(
        title="베란다 창틀에 결로와 곰팡이가 생겼습니다",
        body=(
            "겨울부터 베란다 창틀 아래쪽에 물이 맺히더니 지금은 곰팡이가 번졌습니다. "
            "닦아내도 며칠이면 다시 생깁니다. 하자 보수 대상인지 확인 부탁드립니다."
        ),
        category="하자",
        facility=None,
        priority="normal",
        days_ago=13,
        status="assigned",
        reassign=False,
    ),
    InquirySeed(
        title="동 출입구 앞 흡연 때문에 냄새가 들어옵니다",
        body=(
            "동 출입구 화단 쪽에서 담배를 피우는 분들이 많아 저층 세대로 연기가 들어옵니다. "
            "금연 안내문 부착이나 순찰 시 안내를 부탁드립니다."
        ),
        category="기타",
        facility=None,
        priority="normal",
        days_ago=7,
        status="received",
        reassign=False,
    ),
    InquirySeed(
        title="택배가 배송 완료로 뜨는데 없습니다",
        body=(
            "어제 오후 배송 완료 알림을 받았는데 무인택배함과 문 앞 어디에도 물건이 없습니다. "
            "해당 시간대 출입구 CCTV 확인이 가능한지 문의드립니다."
        ),
        category="보안",
        facility=None,
        priority="urgent",
        days_ago=33,
        status="done",
        reassign=True,
        reply=(
            "요청하신 시간대 출입구 영상을 입회 하에 확인했고, 배송기사가 옆 동에 잘못 "
            "배송한 것으로 확인되어 물품을 회수해 전달드렸습니다."
        ),
    ),
    InquirySeed(
        title="방문 차량 등록은 어떻게 하나요",
        body=(
            "주말에 부모님이 오시는데 방문 차량 등록 방법을 모르겠습니다. "
            "미리 등록해야 하는지, 몇 시간까지 무료인지 알려주세요."
        ),
        category="주차",
        facility=None,
        priority="low",
        days_ago=50,
        status="done",
        reassign=False,
        reply=(
            "방문 차량은 관리사무소 또는 경비실에 차량번호를 남기시면 등록됩니다. "
            "1일 6시간까지 무료이며 초과 시 시간당 1,000원이 부과됩니다."
        ),
    ),
    InquirySeed(
        title="놀이터에서 늦은 시간까지 떠드는 소리가 납니다",
        body=(
            "밤 10시가 넘어서도 놀이터에 청소년들이 모여 큰 소리로 떠듭니다. "
            "인근 동 저층 세대는 창문을 열 수가 없습니다. 야간 순찰을 부탁드립니다."
        ),
        category="소음",
        facility=None,
        priority="normal",
        days_ago=8,
        status="received",
        reassign=False,
    ),
    InquirySeed(
        title="승강기 안에 광고 전단이 계속 붙습니다",
        body=(
            "승강기 내부 게시판이 아닌 벽면에 전단지가 계속 붙습니다. "
            "떼어낸 자국도 지저분합니다. 무단 부착 방지 안내가 필요해 보입니다."
        ),
        category="공용부",
        facility=None,
        priority="low",
        days_ago=14,
        status="assigned",
        reassign=False,
    ),
    InquirySeed(
        title="계단실 비상등 몇 개가 꺼져 있습니다",
        body=(
            "비상계단으로 내려가다 보니 중간 층 비상등 두어 개가 완전히 꺼져 있습니다. "
            "야간에는 계단이 거의 보이지 않습니다. 점검 부탁드립니다."
        ),
        category="설비",
        facility=None,
        priority="urgent",
        days_ago=19,
        status="in_progress",
        reassign=False,
    ),
    InquirySeed(
        title="세대 차단기가 자주 내려갑니다",
        body=(
            "에어컨과 전자레인지를 같이 쓰면 차단기가 내려갑니다. "
            "예전에는 괜찮았는데 최근 들어 일주일에 두세 번씩 그렇습니다. 점검 가능할까요."
        ),
        category="설비",
        facility=None,
        priority="normal",
        days_ago=10,
        status="assigned",
        reassign=False,
    ),
    InquirySeed(
        title="옥상 출입문이 열려 있는 것을 봤습니다",
        body=(
            "어제 저녁 옥상 출입문이 열려 있는 것을 보았습니다. "
            "평소 잠겨 있는 곳이라 안전상 확인이 필요할 것 같아 알려드립니다."
        ),
        category="보안",
        facility=None,
        priority="urgent",
        days_ago=60,
        status="done",
        reassign=False,
        reply=(
            "확인 결과 소방 점검 중 개방 후 잠금이 누락된 건이었습니다. "
            "즉시 시건하고 자동개폐장치 동작을 재확인했습니다. 알려주셔서 감사합니다."
        ),
    ),
    InquirySeed(
        title="지상주차장 바닥에 균열이 커지고 있습니다",
        body=(
            "지상주차장 입구 쪽 아스팔트 균열이 점점 벌어지고 있습니다. "
            "비가 오면 물이 고이고 유모차 바퀴가 걸립니다. 보수 계획이 있는지 궁금합니다."
        ),
        category="하자",
        facility=None,
        priority="normal",
        days_ago=16,
        status="assigned",
        reassign=True,
    ),
    InquirySeed(
        title="우편함 잠금장치가 부서져 있습니다",
        body=(
            "저희 세대 우편함 문이 닫히지 않고 잠금장치가 부서져 있습니다. "
            "우편물이 밖으로 떨어져 있기도 했습니다. 교체 부탁드립니다."
        ),
        category="공용부",
        facility=None,
        priority="low",
        days_ago=10,
        status="received",
        reassign=False,
    ),
    InquirySeed(
        title="단지 산책로 가로등 일부가 안 켜집니다",
        body=(
            "놀이터에서 후문으로 가는 산책로 가로등 세 개가 저녁에도 켜지지 않습니다. "
            "그 구간만 유독 어두워서 밤에 다니기 무섭습니다."
        ),
        category="공용부",
        facility=None,
        priority="normal",
        days_ago=23,
        status="in_progress",
        reassign=False,
    ),
)

INQUIRIES: tuple[InquirySeed, ...] = _WITH_FACILITY + _WITHOUT_FACILITY
