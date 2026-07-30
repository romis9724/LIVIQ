"""첫마을 4단지 그래프 시드 상수 (G1b — GraphRAG 비교 pgvector vs Neo4j).

회의록 정합 장애·정비 이력 + 세대기기→설비 LINKED_TO 배선 매핑. 전부 실재 회의록
근거이고 난수가 없다(재실행 재현). 설계 단일 출처는
`evals/fixtures/chetmaeul-v2/SEED-PLAN.md` §1·§2·§4·§5.

facility는 **이름으로 해석**한다 — code는 서버가 자동 부여해 스크립트 순서로 추론하면
드리프트하므로(SEED-PLAN §6 두 리뷰 공통 오탐), 이름을 커밋 상수 단일 출처로 삼는다.

occurred_at은 장애 **실발생일**(회의 보고일 아님, SEED-PLAN 머리말). 인과 연쇄에서
결과는 원인보다 앞설 수 없다 — seed_graph.py·test_graph_seed_data.py가 assert로 강제.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IncidentSeed:
    """장애 1건. `key`는 인과 연쇄 배선용 문자열 식별자(DB에는 저장 안 함)."""

    key: str
    facility_name: str
    symptom: str
    root_cause: str
    resolution: str
    occurred_at: datetime.date
    caused_by: str | None  # 원인 incident의 key(없으면 None)


@dataclass(frozen=True)
class MaintenanceSeed:
    """정비 이력 1건."""

    facility_name: str
    work: str
    performed_at: datetime.date
    performer: str | None = None
    parts: dict[str, Any] | None = None


# --- incidents 16건 = 회의록 14건(#1~#14) + 인과 선행 2건(#4b·#6b) (SEED-PLAN §1) ---
INCIDENTS: tuple[IncidentSeed, ...] = (
    IncidentSeed(
        key="1",
        facility_name="401동 1호기 승강기",
        symptom="401동 1호기 승강기 주로프 마모 진행",
        root_cause="사용 경년·마모율 6.8→7.2%",
        resolution="주로프 교체",
        occurred_at=datetime.date(2024, 10, 24),
        caused_by=None,
    ),
    IncidentSeed(
        key="2",
        facility_name="404동 2호기 승강기",
        symptom="404동 2호기 승강기 주로프 마모",
        root_cause="마모율 7.1% 교체구간 도달",
        resolution="주로프 교체(2025-04 완료)",
        occurred_at=datetime.date(2024, 10, 24),
        caused_by=None,
    ),
    IncidentSeed(
        key="3",
        facility_name="402동 2호기 승강기",
        symptom="402동 2호기 승강기 도어 인터록 오류",
        root_cause="인터록 접점 마모",
        resolution="부품 교체",
        occurred_at=datetime.date(2026, 2, 26),
        caused_by=None,
    ),
    IncidentSeed(
        key="4",
        facility_name="부스타 급수펌프",
        symptom="부스터펌프 1호기 진동 증가",
        root_cause="임펠러 마모·베어링 노후(13년)",
        resolution="정비 후 교체 의결",
        occurred_at=datetime.date(2025, 8, 21),
        caused_by="4b",
    ),
    IncidentSeed(
        key="5",
        facility_name="지역난방 열교환기",
        symptom="열교환기 2차측 차압조절밸브 오작동",
        root_cause="밸브 고착",
        resolution="정비로 해소",
        occurred_at=datetime.date(2026, 2, 26),
        caused_by=None,
    ),
    IncidentSeed(
        key="6",
        facility_name="화재수신반(R형)",
        symptom="R형 화재수신반 중계기 통신 불량 반복",
        root_cause="중계기 노후(12년)·통신경보 6회",
        resolution="중계기 4개 교체",
        occurred_at=datetime.date(2025, 10, 23),
        caused_by="6b",
    ),
    IncidentSeed(
        key="7",
        facility_name="소방펌프",
        symptom="지하1층 소화펌프 압력스위치 불량",
        root_cause="압력스위치 노후",
        resolution="교체 완료",
        occurred_at=datetime.date(2025, 12, 18),
        caused_by=None,
    ),
    IncidentSeed(
        key="8",
        facility_name="스프링클러 시스템",
        symptom="스프링클러 헤드 누수·손상",
        root_cause="헤드 3개 노후",
        resolution="헤드 교체",
        occurred_at=datetime.date(2024, 11, 21),
        caused_by=None,
    ),
    IncidentSeed(
        key="9",
        facility_name="지하주차장 환기팬",
        symptom="환기팬 3호기 소음",
        root_cause="베어링 손상",
        resolution="임시 정지 후 정비",
        occurred_at=datetime.date(2025, 5, 28),
        caused_by=None,
    ),
    IncidentSeed(
        key="10",
        facility_name="홈네트워크 서버",
        symptom="홈네트워크 서버 고장·월패드 간헐 중단",
        root_cause="서버 하드웨어 노후",
        resolution="미해소 — 임시 우회 운영 중, 8월 서버 교체 예정(as_of 2026-07-30)",
        occurred_at=datetime.date(2026, 6, 20),
        caused_by=None,
    ),
    IncidentSeed(
        key="11",
        facility_name="홈네트워크 서버",
        symptom="월패드 승강기 호출 기능 불능",
        root_cause="홈넷 서버 고장 연쇄",
        resolution="미해소 — 하드웨어 발주 상태, 우회 중",
        occurred_at=datetime.date(2026, 6, 20),
        caused_by="10",
    ),
    IncidentSeed(
        key="12",
        facility_name="어린이놀이터",
        symptom="조합놀이대 미끄럼틀 이음부 유격",
        root_cause="이음부 체결 이완",
        resolution="보수 완료",
        occurred_at=datetime.date(2026, 3, 26),
        caused_by=None,
    ),
    IncidentSeed(
        key="13",
        facility_name="EV 완속충전기 8기(스탠드형·서울씨엔지)",
        symptom="EV충전기 3번기 통신 오류",
        root_cause="통신모듈 이상",
        resolution="서울씨엔지 복구",
        occurred_at=datetime.date(2025, 1, 22),
        caused_by=None,
    ),
    IncidentSeed(
        key="14",
        facility_name="부스타 급수펌프",
        symptom="부스터펌프 1호기 진동 재발",
        root_cause="정비 후 재발(교체 필요)",
        resolution="1·2호기 동시 교체",
        occurred_at=datetime.date(2026, 2, 26),
        caused_by="4",
    ),
    # 선행 2건 — 인과 연쇄 다단계 입증용(SEED-PLAN §1 인과 엣지 표).
    IncidentSeed(
        key="4b",
        facility_name="저수조",
        symptom="저수조 수위센서 오작동",
        root_cause="급수 계통 상류 이상",
        resolution="센서 교정·급수 정상화",
        occurred_at=datetime.date(2025, 7, 10),
        caused_by=None,
    ),
    IncidentSeed(
        key="6b",
        facility_name="화재수신반(R형)",
        symptom="중계기 통신불량 최초 징후",
        root_cause="중계기 노후 초기",
        resolution="경보 확인·모니터링",
        occurred_at=datetime.date(2024, 12, 19),
        caused_by=None,
    ),
)


# --- maintenance_logs 22건 = 대응 정비 14 + 정기 정비 8 (SEED-PLAN §2) ---
MAINTENANCE: tuple[MaintenanceSeed, ...] = (
    # 대응 정비 14건(#1~#14 각 조치의 작업 레코드).
    MaintenanceSeed(
        facility_name="401동 1호기 승강기",
        work="401동 1호기 주로프 교체",
        performed_at=datetime.date(2024, 11, 15),
        performer="코리아엘리베이터",
        parts={"item": "주로프", "qty": 1},
    ),
    MaintenanceSeed(
        facility_name="404동 2호기 승강기",
        work="404동 2호기 주로프 교체",
        performed_at=datetime.date(2025, 4, 30),
        performer="코리아엘리베이터",
        parts={"item": "주로프", "qty": 1},
    ),
    MaintenanceSeed(
        facility_name="402동 2호기 승강기",
        work="402동 2호기 도어 인터록 부품 교체",
        performed_at=datetime.date(2026, 3, 5),
    ),
    MaintenanceSeed(
        facility_name="부스타 급수펌프",
        work="부스터펌프 1호기 정비",
        performed_at=datetime.date(2025, 8, 25),
    ),
    MaintenanceSeed(
        facility_name="지역난방 열교환기",
        work="차압조절밸브 정비",
        performed_at=datetime.date(2026, 3, 2),
    ),
    MaintenanceSeed(
        facility_name="화재수신반(R형)",
        work="중계기 4개 교체",
        performed_at=datetime.date(2025, 10, 25),
        parts={"item": "중계기", "qty": 4},
    ),
    MaintenanceSeed(
        facility_name="소방펌프",
        work="소화펌프 압력스위치 교체",
        performed_at=datetime.date(2025, 12, 20),
        parts={"item": "압력스위치", "qty": 1},
    ),
    MaintenanceSeed(
        facility_name="스프링클러 시스템",
        work="스프링클러 헤드 3개 교체",
        performed_at=datetime.date(2024, 11, 25),
        parts={"item": "스프링클러 헤드", "qty": 3},
    ),
    MaintenanceSeed(
        facility_name="지하주차장 환기팬",
        work="환기팬 3호기 베어링 정비",
        performed_at=datetime.date(2025, 6, 2),
    ),
    MaintenanceSeed(
        facility_name="홈네트워크 서버",
        work="홈네트워크 서버 임시 우회 조치",
        performed_at=datetime.date(2026, 6, 25),
    ),
    MaintenanceSeed(
        facility_name="홈네트워크 서버",
        work="월패드 승강기 호출 기능 임시 우회 조치",
        performed_at=datetime.date(2026, 6, 25),
    ),
    MaintenanceSeed(
        facility_name="어린이놀이터",
        work="미끄럼틀 이음부 보수",
        performed_at=datetime.date(2026, 4, 1),
    ),
    MaintenanceSeed(
        facility_name="EV 완속충전기 8기(스탠드형·서울씨엔지)",
        work="EV충전기 3번기 통신모듈 복구",
        performed_at=datetime.date(2025, 1, 25),
        performer="서울씨엔지",
    ),
    MaintenanceSeed(
        facility_name="부스타 급수펌프",
        work="부스터펌프 1·2호기 동시 교체",
        performed_at=datetime.date(2026, 3, 10),
    ),
    # 정기 정비 8건(회의록 정합 — 2025년 해당 월 확정).
    MaintenanceSeed(
        facility_name="401동 1호기 승강기",
        work="승강기 자체점검(분기)",
        performed_at=datetime.date(2025, 3, 15),
    ),
    MaintenanceSeed(
        facility_name="저수조",
        work="저수조 청소(5월)",
        performed_at=datetime.date(2025, 5, 15),
    ),
    MaintenanceSeed(
        facility_name="저수조",
        work="저수조 청소(11월)",
        performed_at=datetime.date(2025, 11, 15),
    ),
    MaintenanceSeed(
        facility_name="지역난방 열교환기",
        work="열교환기 세관(10월)",
        performed_at=datetime.date(2025, 10, 15),
    ),
    MaintenanceSeed(
        facility_name="수전설비(2250kW·단일계약)",
        work="수변전 연차점검",
        performed_at=datetime.date(2025, 6, 15),
    ),
    MaintenanceSeed(
        facility_name="화재수신반(R형)",
        work="소방 종합정밀점검",
        performed_at=datetime.date(2025, 12, 10),
    ),
    MaintenanceSeed(
        facility_name="어린이놀이터",
        work="놀이터 모래 소독",
        performed_at=datetime.date(2025, 5, 20),
    ),
    MaintenanceSeed(
        facility_name="지하주차장 환기팬",
        work="환기설비 점검",
        performed_at=datetime.date(2025, 9, 15),
    ),
)


# --- LINKED_TO 배선: 세대기기 device_type → 대표 설비 이름 (SEED-PLAN §4) ---
# FK는 단일이라 계통에 설비가 여럿이면 대표 1개만 잇는다(탐색은 도구가 런타임 계통 확장).
# 미매핑 4종(가스밸브·에어컨 배관·경량칸막이·room)은 대응 공용 계통이 없어 NULL 유지
# ("미모델링" — "이력 없음"과 구분, §4). 절대 배선하지 않는다.
LINKED_TO_MAP: dict[str, str] = {
    "화재감지기": "화재수신반(R형)",
    "소화기": "화재수신반(R형)",
    "콘센트": "수전설비(2250kW·단일계약)",
    "분전함": "수전설비(2250kW·단일계약)",
    "수도 차단밸브": "부스타 급수펌프",
    "난방 분배기": "지역난방 열교환기",
    "보일러": "지역난방 열교환기",
    "온도조절기": "지역난방 열교환기",
    "월패드": "홈네트워크 서버",
    "통신단자함": "홈네트워크 서버",
    "TV·인터넷 단자": "홈네트워크 서버",
}

# 배선에서 제외되는 세대기기(NULL 유지 — 계통 미모델링).
UNMAPPED_DEVICE_TYPES: frozenset[str] = frozenset({"가스밸브", "에어컨 배관", "경량칸막이", "room"})
